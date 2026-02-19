from __future__ import annotations

from pathlib import Path

from git import GitCommandError, Repo


class GitService:
    def clone_repo(self, repo_url: str, target_path: Path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        Repo.clone_from(repo_url, target_path)

    def checkout_new_branch(self, repo_path: Path, branch_name: str) -> None:
        repo = Repo(repo_path)
        existing = {head.name for head in repo.heads}
        if branch_name in existing:
            repo.git.checkout(branch_name)
            return
        repo.git.checkout("-b", branch_name)

    def commit_all(self, repo_path: Path, message: str) -> str | None:
        repo = Repo(repo_path)
        repo.git.add(A=True)
        if not repo.is_dirty(untracked_files=True):
            return None
        commit = repo.index.commit(message)
        return commit.hexsha

    def push_branch(self, repo_path: Path, branch_name: str) -> str:
        repo = Repo(repo_path)
        if not repo.remotes:
            return "No remote configured"
        remote = repo.remotes.origin
        try:
            remote.push(refspec=f"{branch_name}:{branch_name}", set_upstream=True)
            return "Push successful"
        except GitCommandError as exc:
            return f"Push failed: {exc}"
