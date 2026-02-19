from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.agents.cicd_monitor import CICDMonitorAgent
from backend.services.docker_service import DockerService


class TestRunnerAgent:
    """Executes tests inside isolated Docker containers.

    Two modes:
    - ``run`` – volume-mount mode; fast local testing during the fix-retry loop.
    - ``run_sandbox`` – GitHub-clone mode; no host filesystem access; used for
      final post-push verification.
    """

    def __init__(self, docker_service: DockerService) -> None:
        self.docker_service = docker_service
        self.monitor = CICDMonitorAgent()

    def run(
        self,
        repo_path: Path,
        framework: str,
        timeline: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Run tests by mounting a local repo path into an isolated container."""
        result = self.docker_service.run_tests(repo_path=repo_path, framework=framework)
        self.monitor.record(
            timeline,
            "test_runner",
            "tests_executed",
            {
                "framework": framework,
                "exit_code": result["exit_code"],
                "duration": result["duration"],
                "sandbox_mode": result.get("sandbox_mode", "volume_mount"),
            },
        )
        return result

    def run_sandbox(
        self,
        repo_url: str,
        branch_name: str,
        framework: str,
        timeline: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Run tests by cloning directly from GitHub inside a fresh container.

        No host paths are mounted.  This is the true sandbox verification used
        after the AI fix branch has been pushed to GitHub.
        """
        result = self.docker_service.run_sandbox_from_url(
            repo_url=repo_url,
            branch_name=branch_name,
            framework=framework,
        )
        self.monitor.record(
            timeline,
            "test_runner",
            "sandbox_verification",
            {
                "framework": framework,
                "exit_code": result["exit_code"],
                "duration": result["duration"],
                "branch": result.get("branch", branch_name),
                "sandbox_mode": "url_clone",
            },
        )
        return result

