"""Unit tests for GitService — branch validation and commit prefix."""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.services.git_service import GitService


svc = GitService()


def test_push_blocks_main():
    from pathlib import Path
    # We don't need a real repo — push_branch checks the name first.
    result = svc.push_branch(repo_path=Path("."), branch_name="main")
    assert "blocked" in result.lower()


def test_push_blocks_master():
    from pathlib import Path
    result = svc.push_branch(repo_path=Path("."), branch_name="master")
    assert "blocked" in result.lower()


def test_push_blocks_no_suffix():
    from pathlib import Path
    result = svc.push_branch(repo_path=Path("."), branch_name="my_branch")
    assert "blocked" in result.lower()


def test_push_blocks_bad_format():
    from pathlib import Path
    result = svc.push_branch(repo_path=Path("."), branch_name="bad-format_AI_Fix")
    assert "blocked" in result.lower()


def test_auth_url_with_token():
    os.environ["GITHUB_TOKEN"] = "ghp_test123"
    url = GitService._auth_repo_url("https://github.com/org/repo.git")
    assert "ghp_test123@" in url
    del os.environ["GITHUB_TOKEN"]


def test_auth_url_no_token():
    os.environ.pop("GITHUB_TOKEN", None)
    url = GitService._auth_repo_url("https://github.com/org/repo.git")
    assert url == "https://github.com/org/repo.git"
