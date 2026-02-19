"""Supervisor agent — **LangGraph StateGraph** orchestrator.

Graph topology
--------------
::

    init → clone → test ⟶ parse_errors → generate_fixes → commit ↺ test
                     │                          │                │
                     └─(pass)────→ push ←───────┘─(no fixes)─────┘
                                    │
                                 sandbox → score → cleanup → END

Every agent is invoked exclusively through a graph node — no legacy
``_execute_sync`` sequential path exists.  The retry loop is fully
controlled by conditional edges, not a manual ``for`` loop.

Features:
  • Per-node ``NODE_START`` / ``NODE_END`` structured logging
  • 10-minute hard timeout guard
  • Parallel rule-based + LLM fix generation
  • Graceful rollback when LLM patches corrupt files
  • ``validate_pipeline_execution()`` diagnostic report
  • Automatic ``results/run_<ts>_audit.md`` generation
"""

from __future__ import annotations

import asyncio
import logging
import operator
import re
import shutil
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, TypedDict
from uuid import uuid4

try:
    from langgraph.graph import END, StateGraph
except ImportError:
    raise ImportError(
        "langgraph is required for the RIFT StateGraph supervisor.\n"
        "Install it with:  pip install langgraph"
    )

from backend.agents.cicd_monitor import CICDMonitorAgent
from backend.agents.commit_agent import CommitAgent
from backend.agents.error_parser import ErrorParserAgent
from backend.agents.fix_generator import FixGeneratorAgent
from backend.agents.llm_fix_agent import LLMFixAgent
from backend.agents.repo_analyzer import RepoAnalyzerAgent
from backend.agents.test_runner import TestRunnerAgent
from backend.config import get_settings
from backend.services.docker_service import DockerService
from backend.services.git_service import GitService
from backend.services.scoring_service import ScoringService

logger = logging.getLogger("rift.supervisor")

_TIMEOUT_SECONDS = 600  # 10-minute hard timeout
_RESULTS_DIR = Path(__file__).resolve().parent / "results"


# ── helpers ──────────────────────────────────────────────────────────────────


def _event(stage: str, status: str, details: dict | None = None) -> dict:
    """Create a single immutable timeline event."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "status": status,
        "details": details or {},
    }


# ── Typed state ──────────────────────────────────────────────────────────────
#
# Fields annotated with ``Annotated[list, operator.add]`` use *append*
# semantics: each node returns **new items only** and the graph merges them
# via ``operator.add``.  All other fields use last-write-wins (overwrite).


class PipelineState(TypedDict, total=False):
    # Inputs
    repo_url: str
    team_name: str
    leader_name: str
    retry_limit: int

    # Run metadata
    run_id: str
    workspace: str
    branch_name: str
    repo_path: str
    framework: str
    start_time: float

    # Accumulating lists (reducer = operator.add)
    timeline: Annotated[list, operator.add]
    all_fixes: Annotated[list, operator.add]
    nodes_executed: Annotated[list, operator.add]
    container_ids: Annotated[list, operator.add]
    errors_encountered: Annotated[list, operator.add]

    # Counters (overwrite each iteration)
    total_failures: int
    total_commits: int
    total_fixes_count: int
    attempt: int

    # Per-iteration scratch (overwrite)
    test_exit_code: int
    test_output: str
    current_issues: list
    current_fixes: list

    # Results
    final_status: str
    push_message: str
    sandbox_verification: dict
    score: dict
    score_value: int


# ── Supervisor ───────────────────────────────────────────────────────────────


class SupervisorAgent:
    """LangGraph StateGraph-powered multi-agent supervisor.

    All agent invocations happen **inside** graph nodes.  There is no
    alternative sequential execution path.
    """

    def __init__(self) -> None:
        self.git_service = GitService()
        self.docker_service = DockerService()
        self.scoring_service = ScoringService()

        self.repo_analyzer = RepoAnalyzerAgent(git_service=self.git_service)
        self.test_runner = TestRunnerAgent(docker_service=self.docker_service)
        self.error_parser = ErrorParserAgent()
        self.fix_generator = FixGeneratorAgent()
        self.llm_fix_agent = LLMFixAgent()
        self.commit_agent = CommitAgent(git_service=self.git_service)
        self.cicd_monitor = CICDMonitorAgent()

        # Compile the StateGraph once at init time.
        self.app = self._build_graph()

    # ──────────────────────────────────────────────────────────────────────
    # Graph construction
    # ──────────────────────────────────────────────────────────────────────

    def _build_graph(self) -> Any:
        """Build and compile the LangGraph StateGraph."""
        graph = StateGraph(PipelineState)

        # ── Add every pipeline node ──
        graph.add_node("init", self._node_init)
        graph.add_node("clone", self._node_clone)
        graph.add_node("test", self._node_test)
        graph.add_node("parse_errors", self._node_parse_errors)
        graph.add_node("generate_fixes", self._node_generate_fixes)
        graph.add_node("commit", self._node_commit)
        graph.add_node("push", self._node_push)
        graph.add_node("sandbox", self._node_sandbox)
        graph.add_node("score", self._node_score)
        graph.add_node("cleanup", self._node_cleanup)

        # ── Sequential edges ──
        graph.set_entry_point("init")
        graph.add_edge("init", "clone")
        graph.add_edge("clone", "test")

        # ── Conditional retry loop ──
        graph.add_conditional_edges(
            "test",
            self._route_after_test,
            {"parse_errors": "parse_errors", "push": "push"},
        )
        graph.add_conditional_edges(
            "parse_errors",
            self._route_after_parse,
            {"generate_fixes": "generate_fixes", "push": "push"},
        )
        graph.add_conditional_edges(
            "generate_fixes",
            self._route_after_fix,
            {"commit": "commit", "push": "push"},
        )
        graph.add_conditional_edges(
            "commit",
            self._route_after_commit,
            {"test": "test", "push": "push"},
        )

        # ── Post-loop linear path ──
        graph.add_edge("push", "sandbox")
        graph.add_edge("sandbox", "score")
        graph.add_edge("score", "cleanup")
        graph.add_edge("cleanup", END)

        return graph.compile()

    # ──────────────────────────────────────────────────────────────────────
    # Async entry point (called from FastAPI)
    # ──────────────────────────────────────────────────────────────────────

    async def execute(
        self,
        repo_url: str,
        team_name: str,
        leader_name: str,
        retry_limit: int = 5,
    ) -> dict[str, Any]:
        payload = {
            "repo_url": repo_url,
            "team_name": team_name,
            "leader_name": leader_name,
            "retry_limit": retry_limit,
        }
        return await asyncio.to_thread(self._run_graph, payload)

    # ──────────────────────────────────────────────────────────────────────
    # Graph runner (blocking — runs inside asyncio.to_thread)
    # ──────────────────────────────────────────────────────────────────────

    def _run_graph(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Invoke the compiled StateGraph and format the output dict."""
        initial_state: dict[str, Any] = {
            # Inputs
            "repo_url": payload["repo_url"],
            "team_name": payload["team_name"],
            "leader_name": payload["leader_name"],
            "retry_limit": payload.get("retry_limit", 5),
            # Accumulating lists (start empty)
            "timeline": [],
            "all_fixes": [],
            "nodes_executed": [],
            "container_ids": [],
            "errors_encountered": [],
            # Counters
            "total_failures": 0,
            "total_commits": 0,
            "total_fixes_count": 0,
            "attempt": 0,
            # Per-iteration scratch
            "test_exit_code": -1,
            "test_output": "",
            "current_issues": [],
            "current_fixes": [],
            # Result defaults
            "final_status": "FAILED",
            "push_message": "",
            "sandbox_verification": {},
            "score": {},
            "score_value": 0,
        }

        # ── Execute the graph via graph.invoke() ──
        try:
            final_state = self.app.invoke(initial_state)
        except Exception as exc:
            logger.exception("StateGraph invocation failed")
            return {
                "repo_url": payload.get("repo_url", ""),
                "team_name": payload.get("team_name", ""),
                "leader_name": payload.get("leader_name", ""),
                "branch_name": "",
                "total_failures": 0,
                "total_fixes": 0,
                "final_status": "FAILED",
                "time_taken": 0,
                "score": 0,
                "score_breakdown": {},
                "fixes": [],
                "sandbox_verification": {},
                "cicd timeline": [],
                "audit_file": None,
                "pipeline_validation": {"error": str(exc)},
            }

        time_taken = round(
            time.time() - final_state.get("start_time", time.time()), 2
        )

        # ── Post-run artefacts ──
        audit_path = self._generate_audit(final_state, time_taken)
        validation = self.validate_pipeline_execution(final_state)

        # ── Build backward-compatible response ──
        # Include last 3 KB of test output so failures are debuggable without
        # access to the (already-cleaned) container logs.
        raw_output: str = final_state.get("test_output", "")
        last_test_output = raw_output[-3000:] if raw_output else ""

        return {
            "repo_url": final_state.get("repo_url", ""),
            "team_name": final_state.get("team_name", ""),
            "leader_name": final_state.get("leader_name", ""),
            "branch_name": final_state.get("branch_name", ""),
            "total_failures": final_state.get("total_failures", 0),
            "total_fixes": final_state.get("total_fixes_count", 0),
            "final_status": final_state.get("final_status", "FAILED"),
            "time_taken": time_taken,
            "score": final_state.get("score", {}).get("final", 0),
            "score_breakdown": final_state.get("score", {}),
            "fixes": final_state.get("all_fixes", []),
            "sandbox_verification": final_state.get("sandbox_verification", {}),
            "cicd timeline": final_state.get("timeline", []),
            # Debugging helpers — frontend ignores unknown keys
            "last_test_output": last_test_output,
            "audit_file": audit_path.name if audit_path else None,
            "pipeline_validation": validation,
        }

    # ──────────────────────────────────────────────────────────────────────
    # Graph nodes  (each returns a *partial* state update dict)
    # ──────────────────────────────────────────────────────────────────────

    def _node_init(self, state: PipelineState) -> dict:
        """Initialise run metadata and check prerequisites."""
        logger.info("NODE_START: init")
        run_id = uuid4().hex[:8]
        workspace = Path(__file__).with_name(".workspace") / run_id
        workspace.mkdir(parents=True, exist_ok=True)
        branch_name = self._build_branch_name(
            state["team_name"], state["leader_name"]
        )

        # ── Hardening: early prerequisite checks ──
        errors: list[str] = []
        settings = get_settings()
        if not settings.github_token:
            msg = "GITHUB_TOKEN is not set — clone and push will fail"
            errors.append(msg)
            logger.error(msg)
        if self.docker_service.client is None:
            msg = f"Docker daemon not available: {self.docker_service.init_error}"
            errors.append(msg)
            logger.error(msg)

        logger.info(
            "NODE_END: init  run_id=%s branch=%s errors=%d",
            run_id, branch_name, len(errors),
        )
        return {
            "run_id": run_id,
            "workspace": str(workspace),
            "branch_name": branch_name,
            "start_time": time.time(),
            "timeline": [_event("supervisor", "started", {"run_id": run_id})],
            "nodes_executed": ["init"],
            "errors_encountered": errors,
        }

    def _node_clone(self, state: PipelineState) -> dict:
        """Clone repo and detect test framework."""
        logger.info("NODE_START: clone")
        local_tl: list[dict] = []      # agents mutate this; returned to graph
        errors: list[str] = []

        try:
            analysis = self.repo_analyzer.run(
                repo_url=state["repo_url"],
                branch_name=state["branch_name"],
                workspace=Path(state["workspace"]),
                timeline=local_tl,
            )
            repo_path = str(analysis["repo_path"])
            framework = analysis["test_framework"]
        except Exception as exc:
            error_msg = f"Clone failed: {exc}"
            logger.error(error_msg)
            errors.append(error_msg)
            local_tl.append(
                _event("repo_analyzer", "clone_failed", {"error": str(exc)})
            )
            logger.info("NODE_END: clone  (FAILED)")
            return {
                "repo_path": "",
                "framework": "pytest",
                "timeline": local_tl,
                "nodes_executed": ["clone"],
                "errors_encountered": errors,
            }

        logger.info("NODE_END: clone  repo=%s framework=%s", repo_path, framework)
        return {
            "repo_path": repo_path,
            "framework": framework,
            "timeline": local_tl,
            "nodes_executed": ["clone"],
        }

    def _node_test(self, state: PipelineState) -> dict:
        """Run tests inside a Docker container (volume-mount mode)."""
        logger.info("NODE_START: test")
        attempt = state.get("attempt", 0) + 1
        local_tl: list[dict] = []
        container_ids: list[str] = []

        repo_path = state.get("repo_path", "")
        if not repo_path:
            logger.warning("NODE_END: test  (no repo path — skipped)")
            return {
                "attempt": attempt,
                "test_exit_code": 1,
                "test_output": "No repository path available (clone may have failed)",
                "timeline": [
                    _event("cicd", "attempt_started", {"attempt": attempt}),
                    _event("test_runner", "skipped", {"reason": "no repo path"}),
                ],
                "nodes_executed": ["test"],
                "total_failures": state.get("total_failures", 0) + 1,
            }

        local_tl.append(_event("cicd", "attempt_started", {"attempt": attempt}))

        result = self.test_runner.run(
            repo_path=Path(repo_path),
            framework=state.get("framework", "pytest"),
            timeline=local_tl,
        )

        cid = result.get("container_id")
        if cid:
            container_ids.append(cid)

        exit_code = result["exit_code"]
        new_status = state.get("final_status", "FAILED")
        total_failures = state.get("total_failures", 0)

        if exit_code == 0:
            new_status = "PASSED"
            local_tl.append(_event("cicd", "tests_passed", {"attempt": attempt}))
        else:
            total_failures += 1

        logger.info(
            "NODE_END: test  attempt=%d exit_code=%d", attempt, exit_code,
        )
        return {
            "attempt": attempt,
            "test_exit_code": exit_code,
            "test_output": result.get("output", ""),
            "final_status": new_status,
            "total_failures": total_failures,
            "timeline": local_tl,
            "nodes_executed": ["test"],
            "container_ids": container_ids,
        }

    def _node_parse_errors(self, state: PipelineState) -> dict:
        """Parse test output into structured issue dicts."""
        logger.info("NODE_START: parse_errors")
        local_tl: list[dict] = []

        issues = self.error_parser.run(
            test_output=state.get("test_output", ""),
            timeline=local_tl,
        )

        if not issues:
            local_tl.append(
                _event("cicd", "no_parseable_errors",
                       {"attempt": state.get("attempt", 0)})
            )

        logger.info("NODE_END: parse_errors  count=%d", len(issues))
        return {
            "current_issues": issues,
            "timeline": local_tl,
            "nodes_executed": ["parse_errors"],
        }

    def _node_generate_fixes(self, state: PipelineState) -> dict:
        """Apply rule-based + LLM fixes with graceful rollback."""
        logger.info("NODE_START: generate_fixes")
        local_tl: list[dict] = []
        errors: list[str] = []
        repo_path = Path(state["repo_path"])
        issues = state.get("current_issues", [])

        # ── 1) Rule-based fixes for all issues ──
        fixes: list[dict] = self.fix_generator.run(
            repo_path=repo_path,
            issues=issues,
            timeline=local_tl,
        )

        # ── 2) LLM fixes for remaining issues ──
        if self.llm_fix_agent.available:
            rule_fixed_files = {f.get("file") for f in fixes}
            unfixed = [
                i for i in issues
                if i.get("file", "unknown") not in rule_fixed_files
                and i.get("error_type") in (
                    "TYPE_ERROR", "LOGIC", "ASSERTION", "REFERENCE",
                )
            ]
            if unfixed:
                llm_patches = self.llm_fix_agent.batch_generate(
                    repo_path, unfixed, local_tl,
                )
                for patch in llm_patches:
                    # ── Backup for graceful rollback ──
                    file_path = patch.get("file_path")
                    backup: str | None = None
                    if file_path and Path(file_path).exists():
                        backup = Path(file_path).read_text(
                            encoding="utf-8", errors="ignore",
                        )

                    if self.llm_fix_agent.apply_fix(patch):
                        fixes.append({
                            "bug_type": patch["error_type"],
                            "file": patch["file"],
                            "line": patch["line"],
                            "description": patch["explanation"],
                            "summary": (
                                f"{patch['error_type']} error in {patch['file']} "
                                f"line {patch['line']} → Fix: {patch['explanation']}"
                            ),
                        })
                    else:
                        # Revert corrupted file
                        if backup is not None and file_path:
                            try:
                                Path(file_path).write_text(
                                    backup, encoding="utf-8",
                                )
                                logger.info(
                                    "Rolled back %s after failed LLM patch",
                                    file_path,
                                )
                            except Exception:
                                pass
                        errors.append(
                            f"LLM fix failed for {patch.get('file', 'unknown')}"
                        )

        all_fix_summaries = [f["summary"] for f in fixes]
        total_fixes = state.get("total_fixes_count", 0) + len(fixes)

        if not fixes:
            local_tl.append(
                _event("cicd", "no_fixes_applied",
                       {"attempt": state.get("attempt", 0)})
            )

        logger.info("NODE_END: generate_fixes  count=%d", len(fixes))
        return {
            "current_fixes": fixes,
            "all_fixes": all_fix_summaries,
            "total_fixes_count": total_fixes,
            "timeline": local_tl,
            "nodes_executed": ["generate_fixes"],
            "errors_encountered": errors,
        }

    def _node_commit(self, state: PipelineState) -> dict:
        """Commit all staged changes and perform an interim push."""
        logger.info("NODE_START: commit")
        local_tl: list[dict] = []

        repo_path = Path(state["repo_path"])
        attempt = state.get("attempt", 0)
        fixes = state.get("current_fixes", [])

        commit_hash = self.commit_agent.run(
            repo_path=repo_path,
            attempt=attempt,
            fix_count=len(fixes),
            timeline=local_tl,
        )

        total_commits = state.get("total_commits", 0)
        if commit_hash:
            total_commits += 1
            # ── Interim push after each commit ──
            interim_push = self.git_service.push_branch(
                repo_path=repo_path,
                branch_name=state["branch_name"],
            )
            local_tl.append(
                _event("git", "interim_push",
                       {"attempt": attempt, "result": interim_push})
            )

        logger.info(
            "NODE_END: commit  hash=%s total_commits=%d",
            commit_hash, total_commits,
        )
        return {
            "total_commits": total_commits,
            "timeline": local_tl,
            "nodes_executed": ["commit"],
        }

    def _node_push(self, state: PipelineState) -> dict:
        """Final push to GitHub with clear error reporting."""
        logger.info("NODE_START: push")
        local_tl: list[dict] = []
        errors: list[str] = []

        repo_path = state.get("repo_path", "")
        branch_name = state.get("branch_name", "")

        if not repo_path or not branch_name:
            push_msg = "Push skipped: no repo path or branch name"
            errors.append(push_msg)
            logger.warning(push_msg)
        else:
            push_msg = self.git_service.push_branch(
                repo_path=Path(repo_path),
                branch_name=branch_name,
            )
            if "failed" in push_msg.lower() or "blocked" in push_msg.lower():
                errors.append(f"Push error: {push_msg}")
                logger.error("Push failed: %s", push_msg)

        local_tl.append(
            _event("git", "branch_pushed",
                   {"branch_name": branch_name, "result": push_msg})
        )

        logger.info("NODE_END: push  result='%s'", push_msg)
        return {
            "push_message": push_msg,
            "timeline": local_tl,
            "nodes_executed": ["push"],
            "errors_encountered": errors,
        }

    def _node_sandbox(self, state: PipelineState) -> dict:
        """Post-push sandbox verification (always triggered if PASSED)."""
        logger.info("NODE_START: sandbox")
        local_tl: list[dict] = []
        container_ids: list[str] = []

        push_msg = state.get("push_message", "")
        final_status = state.get("final_status", "FAILED")

        if final_status == "PASSED" and "successful" in push_msg.lower():
            local_tl.append(
                _event("test_runner", "sandbox_verification_started", {})
            )

            sb = self.test_runner.run_sandbox(
                repo_url=state["repo_url"],
                branch_name=state["branch_name"],
                framework=state.get("framework", "pytest"),
                timeline=local_tl,
            )

            cid = sb.get("container_id")
            if cid:
                container_ids.append(cid)

            sandbox_verification = {
                "exit_code": sb["exit_code"],
                "duration": sb["duration"],
                "passed": sb["exit_code"] == 0,
                "branch": state["branch_name"],
            }

            new_status = final_status
            if sb["exit_code"] != 0:
                new_status = "SANDBOX_FAILED"

            logger.info("NODE_END: sandbox  exit_code=%d", sb["exit_code"])
            return {
                "sandbox_verification": sandbox_verification,
                "final_status": new_status,
                "timeline": local_tl,
                "nodes_executed": ["sandbox"],
                "container_ids": container_ids,
            }

        # Sandbox skipped — explain why clearly
        if final_status != "PASSED":
            reason = (
                f"{final_status}: tests did not pass after all retry attempts — "
                "no verified fixes to deploy; sandbox verification skipped"
            )
        else:
            reason = f"Push did not succeed ({push_msg!r}) — sandbox skipped"
        sandbox_verification = {"skipped": True, "reason": reason}
        logger.info("NODE_END: sandbox  (skipped — %s)", final_status)
        return {
            "sandbox_verification": sandbox_verification,
            "timeline": [
                _event("cicd", "sandbox_skipped", {
                    "reason": final_status,
                    "detail": "Sandbox only runs when tests pass after AI fixes",
                }),
            ],
            "nodes_executed": ["sandbox"],
        }

    def _node_score(self, state: PipelineState) -> dict:
        """Calculate final score with full breakdown."""
        logger.info("NODE_START: score")

        sb = state.get("sandbox_verification", {})
        sb_passed = sb.get("passed") if not sb.get("skipped") else None

        score = self.scoring_service.calculate_score(
            elapsed_seconds=round(
                time.time() - state.get("start_time", time.time()), 2,
            ),
            commit_count=state.get("total_commits", 0),
            sandbox_passed=sb_passed,
            total_fixes=state.get("total_fixes_count", 0),
            final_status=state.get("final_status", "FAILED"),
        )

        logger.info("NODE_END: score  final=%d", score["final"])
        return {
            "score": score,
            "score_value": score["final"],
            "timeline": [
                _event("supervisor", "finished", {
                    "final_status": state.get("final_status", "FAILED"),
                    "score": score["final"],
                }),
            ],
            "nodes_executed": ["score"],
        }

    def _node_cleanup(self, state: PipelineState) -> dict:
        """Delete workspace directory after run completes."""
        logger.info("NODE_START: cleanup")
        ws = state.get("workspace", "")
        if ws and Path(ws).exists():
            try:
                shutil.rmtree(ws, ignore_errors=True)
                logger.info("Workspace cleaned: %s", ws)
            except Exception:
                pass

        logger.info("NODE_END: cleanup")
        return {"nodes_executed": ["cleanup"]}

    # ──────────────────────────────────────────────────────────────────────
    # Conditional-edge routing functions
    # ──────────────────────────────────────────────────────────────────────

    def _route_after_test(self, state: PipelineState) -> str:
        """After test: PASSED → push | exhausted/timeout → push | else → parse."""
        if state.get("test_exit_code") == 0:
            return "push"
        if state.get("attempt", 0) >= state.get("retry_limit", 5):
            logger.info(
                "Retry limit reached (%d/%d) — proceeding to push",
                state.get("attempt", 0), state.get("retry_limit", 5),
            )
            return "push"
        if time.time() - state.get("start_time", 0) > _TIMEOUT_SECONDS:
            logger.warning("Timeout exceeded — proceeding to push")
            return "push"
        if not state.get("repo_path"):
            return "push"
        return "parse_errors"

    @staticmethod
    def _route_after_parse(state: PipelineState) -> str:
        """After parse: issues found → generate_fixes | else → push."""
        if not state.get("current_issues"):
            return "push"
        return "generate_fixes"

    @staticmethod
    def _route_after_fix(state: PipelineState) -> str:
        """After fix: fixes applied → commit | else → push."""
        if not state.get("current_fixes"):
            return "push"
        return "commit"

    def _route_after_commit(self, state: PipelineState) -> str:
        """After commit: retry → test | exhausted/timeout → push."""
        if state.get("attempt", 0) >= state.get("retry_limit", 5):
            return "push"
        if time.time() - state.get("start_time", 0) > _TIMEOUT_SECONDS:
            logger.warning("Timeout exceeded after commit — proceeding to push")
            return "push"
        return "test"

    # ──────────────────────────────────────────────────────────────────────
    # Pipeline validation (Phase 3)
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def validate_pipeline_execution(state: dict) -> dict:
        """Return a diagnostic report confirming each stage executed."""
        nodes = state.get("nodes_executed", [])
        container_ids = state.get("container_ids", [])
        required = {"init", "clone", "test", "push", "score", "cleanup"}
        executed = set(nodes)

        return {
            "all_required_nodes_executed": required.issubset(executed),
            "nodes_executed": nodes,
            "node_execution_order": " → ".join(nodes),
            "missing_nodes": sorted(required - executed),
            "docker_containers_used": len(container_ids),
            "container_ids": container_ids,
            "branch_created": bool(state.get("branch_name")),
            "push_attempted": "push" in executed,
            "push_status": state.get("push_message", "not attempted"),
            "sandbox_ran": "sandbox" in executed,
            "sandbox_result": state.get("sandbox_verification", {}),
            "total_attempts": state.get("attempt", 0),
            "errors": state.get("errors_encountered", []),
        }

    # ──────────────────────────────────────────────────────────────────────
    # Execution audit markdown (Phase 5)
    # ──────────────────────────────────────────────────────────────────────

    def _generate_audit(
        self, state: dict, time_taken: float,
    ) -> Path | None:
        """Write ``results/run_<ts>_audit.md`` with a full execution trace."""
        try:
            _RESULTS_DIR.mkdir(exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            audit_path = _RESULTS_DIR / f"run_{ts}_audit.md"

            nodes = state.get("nodes_executed", [])
            container_ids = state.get("container_ids", [])
            timeline = state.get("timeline", [])
            fixes = state.get("all_fixes", [])
            errors = state.get("errors_encountered", [])
            validation = self.validate_pipeline_execution(state)

            lines = [
                f"# RIFT Execution Audit — {ts}",
                "",
                "## Run Metadata",
                "",
                "| Field | Value |",
                "|---|---|",
                f"| Run ID | `{state.get('run_id', 'N/A')}` |",
                f"| Team | {state.get('team_name', 'N/A')} |",
                f"| Leader | {state.get('leader_name', 'N/A')} |",
                f"| Repository | {state.get('repo_url', 'N/A')} |",
                f"| Branch | `{state.get('branch_name', 'N/A')}` |",
                f"| Framework | {state.get('framework', 'N/A')} |",
                f"| Total Runtime | {time_taken}s |",
                f"| Final Status | **{state.get('final_status', 'FAILED')}** |",
                f"| Score | {state.get('score', {}).get('final', 0)} |",
                "",
                "## Execution Graph Trace",
                "",
                f"Nodes executed in order: `{'` → `'.join(nodes)}`",
                "",
                f"Total retry attempts: {state.get('attempt', 0)}",
                "",
                "## Docker Containers",
                "",
            ]

            if container_ids:
                for cid in container_ids:
                    lines.append(f"- `{cid}`")
            else:
                lines.append("- No containers recorded")

            lines += [
                "",
                "## Push Status",
                "",
                f"- {state.get('push_message', 'N/A')}",
                "",
                "## Sandbox Verification",
                "",
            ]

            sb = state.get("sandbox_verification", {})
            if sb.get("skipped"):
                lines.append(f"- Skipped: {sb.get('reason', 'N/A')}")
            else:
                lines.append(f"- Exit code: {sb.get('exit_code', 'N/A')}")
                lines.append(f"- Duration: {sb.get('duration', 'N/A')}s")
                lines.append(f"- Passed: {sb.get('passed', 'N/A')}")
                lines.append(f"- Branch: `{sb.get('branch', 'N/A')}`")

            lines += ["", "## Fixes Applied", ""]
            if fixes:
                for i, fix in enumerate(fixes, 1):
                    lines.append(f"{i}. {fix}")
            else:
                lines.append("- No fixes applied")

            # ── Last test output (truncated for readability) ──
            raw_output = state.get("test_output", "")
            if raw_output:
                snippet = raw_output[-2000:]
                lines += [
                    "",
                    "## Last Test Output (tail)",
                    "",
                    "```",
                    snippet,
                    "```",
                ]

            lines += ["", "## Score Breakdown", ""]
            score = state.get("score", {})
            for k, v in score.items():
                lines.append(f"- **{k}**: {v}")

            lines += ["", "## Errors Encountered", ""]
            if errors:
                for err in errors:
                    lines.append(f"- ⚠ {err}")
            else:
                lines.append("- None")

            lines += ["", "## Pipeline Validation", ""]
            for k, v in validation.items():
                lines.append(f"- **{k}**: {v}")

            lines += [
                "",
                "## Full Timeline",
                "",
                "| # | Timestamp | Stage | Status | Details |",
                "|---|-----------|-------|--------|---------|",
            ]
            for i, ev in enumerate(timeline, 1):
                ts_str = ev.get("timestamp", "")[:19]
                details_str = str(ev.get("details", {}))[:80]
                lines.append(
                    f"| {i} | {ts_str} | {ev.get('stage', '')} "
                    f"| {ev.get('status', '')} | {details_str} |"
                )

            lines += [
                "",
                "---",
                "*Generated by RIFT Autonomous CI/CD Healing Agent*",
            ]

            audit_path.write_text("\n".join(lines), encoding="utf-8")
            logger.info("Audit written to %s", audit_path)
            return audit_path

        except Exception as exc:
            logger.warning("Failed to write audit markdown: %s", exc)
            return None

    # ──────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_branch_name(team_name: str, leader_name: str) -> str:
        def sanitize(value: str) -> str:
            cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
            cleaned = re.sub(r"_+", "_", cleaned)
            return cleaned.upper() or "UNKNOWN"

        return f"{sanitize(team_name)}_{sanitize(leader_name)}_AI_Fix"
