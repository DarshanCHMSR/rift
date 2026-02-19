from __future__ import annotations

import re
from os import getenv
from pathlib import Path

from git import GitCommandError, Repo


class GitService:
    def clone_repo(self, repo_url: str, target_path: Path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        Repo.clone_from(self._auth_repo_url(repo_url), target_path)

    def checkout_new_branch(self, repo_path: Path, branch_name: str) -> None:
        repo = Repo(repo_path)
        existing = {head.name for head in repo.heads}
        if branch_name in existing:
            repo.git.checkout(branch_name)
            return
        repo.git.checkout("-b", branch_name)

    def commit_all(self, repo_path: Path, message: str) -> str | None:
        repo = Repo(repo_path)
        self._ensure_git_identity(repo)
        repo.git.add(A=True)
        if not repo.is_dirty(untracked_files=True):
            return None
        if not message.startswith("[AI-AGENT]"):
            message = f"[AI-AGENT] {message}"
        commit = repo.index.commit(message)
        return commit.hexsha

    def push_branch(self, repo_path: Path, branch_name: str) -> str:
        if branch_name in {"main", "master"}:
            return "Push blocked: protected branch"
        if not branch_name.endswith("_AI_Fix"):
            return "Push blocked: branch must end with _AI_Fix"
        if not re.fullmatch(r"[A-Z0-9_]+_AI_Fix", branch_name):
            return "Push blocked: invalid branch naming format"

        repo = Repo(repo_path)
        if not repo.remotes:
            return "No remote configured"
        repo.git.checkout(branch_name)
        remote = repo.remotes.origin
        try:
            remote.push(refspec=f"{branch_name}:{branch_name}", set_upstream=True)
            return "Push successful"
        except GitCommandError as exc:
            return f"Push failed: {exc}"

    @staticmethod
    def _auth_repo_url(repo_url: str) -> str:
        token = getenv("GITHUB_TOKEN", "").strip()
        if not token:
            return repo_url
        if repo_url.startswith("https://github.com/"):
            return repo_url.replace("https://", f"https://{token}@", 1)
        return repo_url

    @staticmethod
    def _ensure_git_identity(repo: Repo) -> None:
        with repo.config_writer() as writer:
            try:
                _ = repo.config_reader().get_value("user", "name")
            except Exception:
                writer.set_value("user", "name", "AI Agent")
            try:
                _ = repo.config_reader().get_value("user", "email")
            except Exception:
                writer.set_value("user", "email", "ai-agent@local")
