"""Supervisor agent — LangChain StateGraph orchestrator.

Coordinates: clone → branch → [test → parse → fix → commit] loop → push →
sandbox verify → score.  Implements workspace auto-cleanup, a 10-minute
timeout guard, parallel fix generation, and LLM fix-agent integration.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Any, TypedDict
from uuid import uuid4

from langchain_core.runnables import RunnableLambda

from backend.agents.cicd_monitor import CICDMonitorAgent
from backend.agents.commit_agent import CommitAgent
from backend.agents.error_parser import ErrorParserAgent
from backend.agents.fix_generator import FixGeneratorAgent
from backend.agents.llm_fix_agent import LLMFixAgent
from backend.agents.repo_analyzer import RepoAnalyzerAgent
from backend.agents.test_runner import TestRunnerAgent
from backend.services.docker_service import DockerService
from backend.services.git_service import GitService
from backend.services.scoring_service import ScoringService

logger = logging.getLogger("rift.supervisor")

_TIMEOUT_SECONDS = 600  # 10-minute hard timeout


# ── StateGraph typed state ────────────────────────────────────────────────────

class PipelineState(TypedDict, total=False):
    # Inputs
    repo_url: str
    team_name: str
    leader_name: str
    retry_limit: int
    # Internal
    run_id: str
    workspace: Path
    branch_name: str
    repo_path: Path
    framework: str
    timeline: list[dict[str, Any]]
    all_fixes: list[str]
    total_failures: int
    total_commits: int
    total_fixes: int
    final_status: str
    sandbox_verification: dict[str, Any]
    start_time: float
    # Output
    score: dict[str, Any]
    score_value: int


class SupervisorAgent:
    """LangChain-powered multi-agent supervisor with StateGraph semantics."""

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

        # LangChain runnable wrappers for each agent (Supervisor pattern).
        self.repo_analyzer_chain = RunnableLambda(
            lambda args: self.repo_analyzer.run(**args)
        )
        self.test_runner_chain = RunnableLambda(lambda args: self.test_runner.run(**args))
        self.error_parser_chain = RunnableLambda(
            lambda args: self.error_parser.run(**args)
        )
        self.fix_generator_chain = RunnableLambda(
            lambda args: self.fix_generator.run(**args)
        )
        self.commit_chain = RunnableLambda(lambda args: self.commit_agent.run(**args))

        # The top-level StateGraph runnable.
        self.supervisor_chain = RunnableLambda(self._execute_sync)

    # ------------------------------------------------------------------
    # Async entry point
    # ------------------------------------------------------------------

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
        return await asyncio.to_thread(self.supervisor_chain.invoke, payload)

    # ------------------------------------------------------------------
    # StateGraph nodes
    # ------------------------------------------------------------------

    def _node_init(self, state: PipelineState) -> PipelineState:
        """Initialise run metadata."""
        run_id = uuid4().hex[:8]
        workspace = Path(__file__).with_name(".workspace") / run_id
        workspace.mkdir(parents=True, exist_ok=True)
        state["run_id"] = run_id
        state["workspace"] = workspace
        state["branch_name"] = self._build_branch_name(
            state["team_name"], state["leader_name"]
        )
        state["timeline"] = []
        state["all_fixes"] = []
        state["total_failures"] = 0
        state["total_commits"] = 0
        state["total_fixes"] = 0
        state["final_status"] = "FAILED"
        state["sandbox_verification"] = {}
        state["start_time"] = time.time()
        self.cicd_monitor.record(
            state["timeline"], "supervisor", "started", {"run_id": run_id}
        )
        logger.info("run=%s started team=%s", run_id, state["team_name"])
        return state

    def _node_clone(self, state: PipelineState) -> PipelineState:
        """Clone repo and detect test framework."""
        analysis = self.repo_analyzer_chain.invoke({
            "repo_url": state["repo_url"],
            "branch_name": state["branch_name"],
            "workspace": state["workspace"],
            "timeline": state["timeline"],
        })
        state["repo_path"] = analysis["repo_path"]
        state["framework"] = analysis["test_framework"]
        return state

    def _node_retry_loop(self, state: PipelineState) -> PipelineState:
        """Core fix-test loop with timeout guard & parallel fixes."""
        retry_limit = state.get("retry_limit", 5)
        timeline = state["timeline"]
        repo_path = state["repo_path"]
        framework = state["framework"]

        for attempt in range(1, retry_limit + 1):
            # Timeout guard
            if time.time() - state["start_time"] > _TIMEOUT_SECONDS:
                self.cicd_monitor.record(
                    timeline, "supervisor", "timeout",
                    {"elapsed": round(time.time() - state["start_time"], 1)},
                )
                logger.warning("run=%s timed out at attempt %d", state["run_id"], attempt)
                break

            self.cicd_monitor.record(
                timeline, "cicd", "attempt_started", {"attempt": attempt}
            )

            # Test
            test_result = self.test_runner_chain.invoke({
                "repo_path": repo_path, "framework": framework, "timeline": timeline,
            })
            if test_result["exit_code"] == 0:
                state["final_status"] = "PASSED"
                self.cicd_monitor.record(
                    timeline, "cicd", "tests_passed", {"attempt": attempt}
                )
                break

            state["total_failures"] += 1

            # Parse errors
            issues = self.error_parser_chain.invoke({
                "test_output": test_result["output"], "timeline": timeline,
            })
            if not issues:
                self.cicd_monitor.record(
                    timeline, "cicd", "no_parseable_errors", {"attempt": attempt}
                )
                break

            # ── Parallel fix strategy ────────────────────────────
            # 1) Rule-based fixes for all issues first
            fixes = self.fix_generator_chain.invoke({
                "repo_path": repo_path, "issues": issues, "timeline": timeline,
            })

            # 2) LLM fixes for issues the rule engine couldn't handle
            if self.llm_fix_agent.available:
                rule_fixed_files = {f.get("file") for f in fixes}
                unfixed = [
                    i for i in issues
                    if i.get("file", "unknown") not in rule_fixed_files
                    and i.get("error_type") in ("TYPE_ERROR", "LOGIC", "ASSERTION", "REFERENCE")
                ]
                if unfixed:
                    llm_patches = self.llm_fix_agent.batch_generate(
                        repo_path, unfixed, timeline,
                    )
                    for patch in llm_patches:
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

            if not fixes:
                self.cicd_monitor.record(
                    timeline, "cicd", "no_fixes_applied", {"attempt": attempt}
                )
                break

            state["total_fixes"] += len(fixes)
            state["all_fixes"].extend(item["summary"] for item in fixes)

            # Single commit per iteration (batched)
            commit_hash = self.commit_chain.invoke({
                "repo_path": repo_path,
                "attempt": attempt,
                "fix_count": len(fixes),
                "timeline": timeline,
            })
            if commit_hash:
                state["total_commits"] += 1
                interim_push = self.git_service.push_branch(
                    repo_path=repo_path, branch_name=state["branch_name"],
                )
                self.cicd_monitor.record(
                    timeline, "git", "interim_push",
                    {"attempt": attempt, "result": interim_push},
                )

            self.cicd_monitor.record(
                timeline, "cicd", "retry_scheduled", {"attempt": attempt + 1}
            )

        return state

    def _node_push(self, state: PipelineState) -> PipelineState:
        """Final push to GitHub."""
        push_msg = self.git_service.push_branch(
            repo_path=state["repo_path"], branch_name=state["branch_name"],
        )
        self.cicd_monitor.record(
            state["timeline"], "git", "branch_pushed",
            {"branch_name": state["branch_name"], "result": push_msg},
        )
        state["_push_message"] = push_msg  # type: ignore[typeddict-unknown-key]
        return state

    def _node_sandbox(self, state: PipelineState) -> PipelineState:
        """Post-push sandbox verification."""
        push_msg: str = state.get("_push_message", "")  # type: ignore[typeddict-item]
        if state["final_status"] == "PASSED" and "successful" in push_msg.lower():
            self.cicd_monitor.record(
                state["timeline"], "test_runner", "sandbox_verification_started", {}
            )
            sb = self.test_runner.run_sandbox(
                repo_url=state["repo_url"],
                branch_name=state["branch_name"],
                framework=state["framework"],
                timeline=state["timeline"],
            )
            state["sandbox_verification"] = {
                "exit_code": sb["exit_code"],
                "duration": sb["duration"],
                "passed": sb["exit_code"] == 0,
                "branch": state["branch_name"],
            }
            if sb["exit_code"] != 0:
                state["final_status"] = "SANDBOX_FAILED"
        else:
            state["sandbox_verification"] = {"skipped": True, "reason": push_msg}
        return state

    def _node_score(self, state: PipelineState) -> PipelineState:
        """Calculate final score and build result dict."""
        sb = state["sandbox_verification"]
        sb_passed = sb.get("passed") if not sb.get("skipped") else None
        state["score"] = self.scoring_service.calculate_score(
            elapsed_seconds=round(time.time() - state["start_time"], 2),
            commit_count=state["total_commits"],
            sandbox_passed=sb_passed,
            total_fixes=state["total_fixes"],
        )
        state["score_value"] = state["score"]["final"]
        self.cicd_monitor.record(
            state["timeline"], "supervisor", "finished",
            {"final_status": state["final_status"]},
        )
        return state

    def _node_cleanup(self, state: PipelineState) -> PipelineState:
        """Delete workspace directory after run completes."""
        ws = state.get("workspace")
        if ws and ws.exists():
            try:
                shutil.rmtree(ws, ignore_errors=True)
                logger.info("run=%s workspace cleaned up", state.get("run_id", "?"))
            except Exception:
                pass
        return state

    # ------------------------------------------------------------------
    # Graph execution
    # ------------------------------------------------------------------

    def _execute_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full StateGraph pipeline synchronously."""
        state: PipelineState = {
            "repo_url": payload["repo_url"],
            "team_name": payload["team_name"],
            "leader_name": payload["leader_name"],
            "retry_limit": payload.get("retry_limit", 5),
        }  # type: ignore[typeddict-item]

        # Execute nodes in sequence (mirrors a linear StateGraph)
        state = self._node_init(state)
        state = self._node_clone(state)
        state = self._node_retry_loop(state)
        state = self._node_push(state)
        state = self._node_sandbox(state)
        state = self._node_score(state)
        state = self._node_cleanup(state)

        time_taken = round(time.time() - state["start_time"], 2)

        return {
            "repo_url": state["repo_url"],
            "team_name": state["team_name"],
            "leader_name": state.get("leader_name", ""),
            "branch_name": state["branch_name"],
            "total_failures": state["total_failures"],
            "total_fixes": state["total_fixes"],
            "final_status": state["final_status"],
            "time_taken": time_taken,
            "score": state["score"]["final"],
            "score_breakdown": state["score"],
            "fixes": state["all_fixes"],
            "sandbox_verification": state["sandbox_verification"],
            "cicd timeline": state["timeline"],
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_branch_name(team_name: str, leader_name: str) -> str:
        def sanitize(value: str) -> str:
            cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
            cleaned = re.sub(r"_+", "_", cleaned)
            return cleaned.upper() or "UNKNOWN"

        return f"{sanitize(team_name)}_{sanitize(leader_name)}_AI_Fix"
