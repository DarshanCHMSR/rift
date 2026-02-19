from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.agents.cicd_monitor import CICDMonitorAgent
from backend.services.docker_service import DockerService


class TestRunnerAgent:
    def __init__(self, docker_service: DockerService) -> None:
        self.docker_service = docker_service
        self.monitor = CICDMonitorAgent()

    def run(
        self,
        repo_path: Path,
        framework: str,
        timeline: list[dict[str, Any]],
    ) -> dict[str, Any]:
        result = self.docker_service.run_tests(repo_path=repo_path, framework=framework)
        self.monitor.record(
            timeline,
            "test_runner",
            "tests_executed",
            {
                "framework": framework,
                "exit_code": result["exit_code"],
                "duration": result["duration"],
            },
        )
        return result

