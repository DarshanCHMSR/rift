from __future__ import annotations

import shlex
import time
from pathlib import Path
from typing import Any

import docker
from docker.errors import DockerException, ImageNotFound

from backend.config import get_settings

# Resource limits applied to every sandbox container.
_MEM_LIMIT = "1g"
_NANO_CPUS = 1_000_000_000  # 1 vCPU


def _safe_remove(container: Any) -> None:
    """Force-remove a container, silently ignoring errors."""
    try:
        container.remove(force=True)
    except DockerException:
        pass


class DockerService:
    """Manages isolated Docker sandbox containers for test execution.

    Two execution modes are provided:

    * ``run_tests`` – mounts a *local* repo path into the container (fast;
      used during the fix-retry loop where changes live on the host).
    * ``run_sandbox_from_url`` – clones the repository *inside* the container
      directly from GitHub with no host filesystem access (true isolation; used
      for final post-push verification).
    """

    def __init__(self) -> None:
        self.client = None
        self.init_error = ""
        try:
            self.client = docker.from_env()
            self.client.ping()
        except DockerException as exc:
            self.init_error = str(exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_tests(self, repo_path: Path, framework: str, timeout: int = 900) -> dict[str, Any]:
        """Run tests against a *locally cloned* repository via volume mount.

        The repo is mounted read-only at ``/seed/repo`` and cloned inside the
        container so the sandbox never writes back to the host.  The container
        is unconditionally removed on completion.
        """
        if self.client is None:
            return {
                "exit_code": 1,
                "output": f"Docker not available: {self.init_error}",
                "duration": 0.0,
                "sandbox_mode": "volume_mount",
            }

        image, command = self._command_for_framework(framework)
        started = time.time()
        container = None

        try:
            container = self._create_container(
                image=image,
                command=command,
                volumes={
                    str(repo_path.resolve()): {"bind": "/seed/repo", "mode": "ro"}
                },
                environment={"OPENAI_API_KEY": get_settings().openai_api_key},
            )
            result = container.wait(timeout=timeout)
            logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
            return {
                "exit_code": int(result.get("StatusCode", 1)),
                "output": logs,
                "duration": round(time.time() - started, 2),
                "container_id": container.id[:12],
                "sandbox_mode": "volume_mount",
            }
        except DockerException as exc:
            return {
                "exit_code": 1,
                "output": f"Docker execution failed: {exc}",
                "duration": round(time.time() - started, 2),
                "sandbox_mode": "volume_mount",
            }
        finally:
            if container is not None:
                _safe_remove(container)

    def run_sandbox_from_url(
        self,
        repo_url: str,
        branch_name: str,
        framework: str,
        timeout: int = 900,
    ) -> dict[str, Any]:
        """Run tests by cloning *directly from GitHub inside a fresh container*.

        No host filesystem paths are mounted.  The GitHub token is injected via
        an environment variable and never written to disk.  The container is
        unconditionally destroyed after the run.

        Args:
            repo_url: Public or private GitHub HTTPS URL.
            branch_name: Branch to checkout after cloning.
            framework: One of ``pytest``, ``unittest``, ``npm``.
            timeout: Seconds before forcibly killing the container.
        """
        if self.client is None:
            return {
                "exit_code": 1,
                "output": f"Docker not available: {self.init_error}",
                "duration": 0.0,
                "sandbox_mode": "url_clone",
            }

        settings = get_settings()
        authed_url = self._inject_token(repo_url, settings.github_token)
        image, test_cmd = self._test_commands_for_framework(framework)

        # Build the full bash script: install git if missing → clone → test
        script = (
            "set -e; "
            "if ! command -v git >/dev/null 2>&1; then "
            "apt-get update -qq && apt-get install -y --no-install-recommends git ca-certificates >/dev/null 2>&1; "
            "fi; "
            f"git clone --depth 1 --branch {shlex.quote(branch_name)} "
            f"{shlex.quote(authed_url)} /sandbox/repo >/tmp/clone.log 2>&1 "
            "|| git clone --depth 1 "
            f"{shlex.quote(authed_url)} /sandbox/repo >/tmp/clone.log 2>&1 "
            "|| (cat /tmp/clone.log && exit 1); "
            "cd /sandbox/repo; "
            + test_cmd
        )
        command = "sh -lc " + shlex.quote(script)

        started = time.time()
        container = None
        try:
            container = self._create_container(
                image=image,
                command=command,
                volumes={},  # No host filesystem access
                environment={
                    "OPENAI_API_KEY": settings.openai_api_key,
                    "GIT_TERMINAL_PROMPT": "0",  # Prevent interactive prompts
                },
            )
            result = container.wait(timeout=timeout)
            logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
            return {
                "exit_code": int(result.get("StatusCode", 1)),
                "output": logs,
                "duration": round(time.time() - started, 2),
                "container_id": container.id[:12],
                "sandbox_mode": "url_clone",
                "branch": branch_name,
            }
        except DockerException as exc:
            return {
                "exit_code": 1,
                "output": f"Sandbox execution failed: {exc}",
                "duration": round(time.time() - started, 2),
                "sandbox_mode": "url_clone",
            }
        finally:
            if container is not None:
                _safe_remove(container)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_container(
        self,
        image: str,
        command: str,
        volumes: dict,
        environment: dict,
    ) -> Any:
        """Pull image if needed, then create + start a resource-limited container."""
        try:
            return self.client.containers.run(
                image=image,
                command=command,
                working_dir="/",
                volumes=volumes,
                environment=environment,
                detach=True,
                stderr=True,
                stdout=True,
                network_disabled=False,
                mem_limit=_MEM_LIMIT,
                nano_cpus=_NANO_CPUS,
                # Security: drop all Linux capabilities; run as non-root
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                read_only=False,  # /workspace needs writes inside container
                auto_remove=False,  # We remove explicitly for reliable cleanup
            )
        except ImageNotFound:
            self.client.images.pull(image)
            return self.client.containers.run(
                image=image,
                command=command,
                working_dir="/",
                volumes=volumes,
                environment=environment,
                detach=True,
                stderr=True,
                stdout=True,
                network_disabled=False,
                mem_limit=_MEM_LIMIT,
                nano_cpus=_NANO_CPUS,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                read_only=False,
                auto_remove=False,
            )

    @staticmethod
    def _inject_token(repo_url: str, token: str) -> str:
        """Embed the GitHub token into an HTTPS URL, if available."""
        if not token:
            return repo_url
        if repo_url.startswith("https://github.com/"):
            return repo_url.replace("https://", f"https://{token}@", 1)
        return repo_url

    @staticmethod
    def _test_commands_for_framework(framework: str) -> tuple[str, str]:
        """Return (docker_image, bash_test_snippet) for the given framework.

        The snippet assumes the working directory is already the repo root.
        """
        if framework == "npm":
            return (
                "node:20-bookworm-slim",
                "if [ -f package-lock.json ]; then npm ci --silent || npm install --silent; "
                "else npm install --silent; fi; "
                "npm test -- --watch=false",
            )
        if framework == "unittest":
            return (
                "python:3.11-slim",
                "if [ -f requirements.txt ]; then "
                "pip install --no-cache-dir -r requirements.txt >/dev/null 2>&1 || true; "
                "fi; python -m unittest discover",
            )
        # Default: pytest
        return (
            "python:3.11-slim",
            "if [ -f requirements.txt ]; then "
            "pip install --no-cache-dir -r requirements.txt >/dev/null 2>&1 || true; "
            "fi; pip install --no-cache-dir pytest >/dev/null 2>&1; pytest -q",
        )

    @staticmethod
    def _command_for_framework(framework: str) -> tuple[str, str]:
        """Return (docker_image, full_shell_command) for a volume-mount run.

        The volume mount places the host repo at ``/seed/repo`` (read-only).
        The container clones it internally to ``/workspace/repo`` so the test
        process always runs inside the container's own filesystem.
        """
        clone_step = (
            "set -e; "
            "if ! command -v git >/dev/null 2>&1; then "
            "apt-get update -qq && apt-get install -y --no-install-recommends git ca-certificates >/dev/null 2>&1; "
            "fi; "
            "rm -rf /workspace && mkdir -p /workspace; "
            "git clone /seed/repo /workspace/repo >/tmp/clone.log 2>&1 || (cat /tmp/clone.log && exit 1); "
            "cd /workspace/repo; "
        )
        image, test_cmd = DockerService._test_commands_for_framework(framework)
        return image, "sh -lc " + shlex.quote(clone_step + test_cmd)
