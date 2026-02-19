from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.agents.cicd_monitor import CICDMonitorAgent
from backend.services.git_service import GitService


class RepoAnalyzerAgent:
    def __init__(self, git_service: GitService) -> None:
        self.git_service = git_service
        self.monitor = CICDMonitorAgent()

    def run(
        self,
        repo_url: str,
        branch_name: str,
        workspace: Path,
        timeline: list[dict[str, Any]],
    ) -> dict[str, Any]:
        repo_path = workspace / "repo"
        self.git_service.clone_repo(repo_url=repo_url, target_path=repo_path)
        self.git_service.checkout_new_branch(repo_path=repo_path, branch_name=branch_name)
        framework = self._detect_test_framework(repo_path)

        self.monitor.record(
            timeline,
            "repo_analyzer",
            "repo_ready",
            {"repo_path": str(repo_path), "test_framework": framework},
        )
        return {"repo_path": repo_path, "test_framework": framework}

    @staticmethod
    def _detect_test_framework(repo_path: Path) -> str:
        if (repo_path / "package.json").exists():
            return "npm"
        if (repo_path / "pytest.ini").exists():
            return "pytest"
        if (repo_path / "pyproject.toml").exists():
            content = (repo_path / "pyproject.toml").read_text(encoding="utf-8", errors="ignore")
            if "pytest" in content.lower():
                return "pytest"
        if (repo_path / "requirements.txt").exists():
            content = (repo_path / "requirements.txt").read_text(
                encoding="utf-8", errors="ignore"
            )
            if "pytest" in content.lower():
                return "pytest"
        tests_dir = repo_path / "tests"
        if tests_dir.exists():
            return "pytest"
        return "unittest"

