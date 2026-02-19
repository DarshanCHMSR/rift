from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.runnables import RunnableLambda

from backend.agents.cicd_monitor import CICDMonitorAgent
from backend.agents.commit_agent import CommitAgent
from backend.agents.error_parser import ErrorParserAgent
from backend.agents.fix_generator import FixGeneratorAgent
from backend.agents.repo_analyzer import RepoAnalyzerAgent
from backend.agents.test_runner import TestRunnerAgent
from backend.services.docker_service import DockerService
from backend.services.git_service import GitService
from backend.services.scoring_service import ScoringService


class SupervisorAgent:
    def __init__(self) -> None:
        self.git_service = GitService()
        self.docker_service = DockerService()
        self.scoring_service = ScoringService()

        self.repo_analyzer = RepoAnalyzerAgent(git_service=self.git_service)
        self.test_runner = TestRunnerAgent(docker_service=self.docker_service)
        self.error_parser = ErrorParserAgent()
        self.fix_generator = FixGeneratorAgent()
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

        # LangChain supervisor runnable orchestrating all sub-agents end-to-end.
        self.supervisor_chain = RunnableLambda(self._execute_sync)

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

    def _execute_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        start = time.time()

        repo_url = payload["repo_url"]
        team_name = payload["team_name"]
        leader_name = payload["leader_name"]
        retry_limit = payload.get("retry_limit", 5)

        branch_name = self._build_branch_name(team_name, leader_name)
        run_id = uuid4().hex[:8]
        workspace = Path(__file__).with_name(".workspace") / run_id
        workspace.mkdir(parents=True, exist_ok=True)

        timeline: list[dict[str, Any]] = []
        all_fixes: list[str] = []
        total_failures = 0
        total_commits = 0
        total_fixes = 0
        final_status = "FAILED"

        self.cicd_monitor.record(timeline, "supervisor", "started", {"run_id": run_id})

        analysis = self.repo_analyzer_chain.invoke(
            {
                "repo_url": repo_url,
                "branch_name": branch_name,
                "workspace": workspace,
                "timeline": timeline,
            }
        )
        repo_path = analysis["repo_path"]
        framework = analysis["test_framework"]

        for attempt in range(1, retry_limit + 1):
            self.cicd_monitor.record(
                timeline, "cicd", "attempt_started", {"attempt": attempt}
            )

            test_result = self.test_runner_chain.invoke(
                {"repo_path": repo_path, "framework": framework, "timeline": timeline}
            )
            if test_result["exit_code"] == 0:
                final_status = "PASSED"
                self.cicd_monitor.record(
                    timeline, "cicd", "tests_passed", {"attempt": attempt}
                )
                break

            total_failures += 1
            issues = self.error_parser_chain.invoke(
                {"test_output": test_result["output"], "timeline": timeline}
            )
            if not issues:
                self.cicd_monitor.record(
                    timeline,
                    "cicd",
                    "no_parseable_errors",
                    {"attempt": attempt},
                )
                break

            fixes = self.fix_generator_chain.invoke(
                {"repo_path": repo_path, "issues": issues, "timeline": timeline}
            )
            if not fixes:
                self.cicd_monitor.record(
                    timeline, "cicd", "no_fixes_applied", {"attempt": attempt}
                )
                break

            total_fixes += len(fixes)
            all_fixes.extend(item["summary"] for item in fixes)

            commit_hash = self.commit_chain.invoke(
                {
                    "repo_path": repo_path,
                    "attempt": attempt,
                    "fix_count": len(fixes),
                    "timeline": timeline,
                }
            )
            if commit_hash:
                total_commits += 1

            self.cicd_monitor.record(
                timeline,
                "cicd",
                "retry_scheduled",
                {"attempt": attempt + 1},
            )

        push_message = self.git_service.push_branch(repo_path=repo_path, branch_name=branch_name)
        self.cicd_monitor.record(
            timeline, "git", "branch_pushed", {"branch_name": branch_name, "result": push_message}
        )

        time_taken = round(time.time() - start, 2)
        score = self.scoring_service.calculate_score(
            elapsed_seconds=time_taken,
            commit_count=total_commits,
        )

        self.cicd_monitor.record(
            timeline, "supervisor", "finished", {"final_status": final_status}
        )
        return {
            "repo_url": repo_url,
            "team_name": team_name,
            "leader_name": leader_name,
            "branch_name": branch_name,
            "total_failures": total_failures,
            "total_fixes": total_fixes,
            "final_status": final_status,
            "time_taken": time_taken,
            "score": score,
            "fixes": all_fixes,
            "cicd timeline": timeline,
        }

    @staticmethod
    def _build_branch_name(team_name: str, leader_name: str) -> str:
        def sanitize(value: str) -> str:
            cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
            cleaned = re.sub(r"_+", "_", cleaned)
            return cleaned.upper() or "UNKNOWN"

        return f"{sanitize(team_name)}_{sanitize(leader_name)}_AI_Fix"
