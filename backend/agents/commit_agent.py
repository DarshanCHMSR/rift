from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.agents.cicd_monitor import CICDMonitorAgent
from backend.services.git_service import GitService


class CommitAgent:
    def __init__(self, git_service: GitService) -> None:
        self.git_service = git_service
        self.monitor = CICDMonitorAgent()

    def run(
        self,
        repo_path: Path,
        attempt: int,
        fix_count: int,
        timeline: list[dict[str, Any]],
    ) -> str | None:
        message = f"[AI-AGENT] Attempt {attempt}: applied {fix_count} fixes"
        commit_hash = self.git_service.commit_all(repo_path=repo_path, message=message)
        self.monitor.record(
            timeline,
            "commit_agent",
            "commit_attempted",
            {"attempt": attempt, "commit_hash": commit_hash},
        )
        return commit_hash

