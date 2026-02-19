from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import docker
from docker.errors import DockerException, ImageNotFound


class DockerService:
    def __init__(self) -> None:
        self.client = docker.from_env()

    def run_tests(self, repo_path: Path, framework: str, timeout: int = 600) -> dict[str, Any]:
        image, command = self._command_for_framework(framework)
        started = time.time()
        container = None

        try:
            try:
                container = self.client.containers.run(
                    image=image,
                    command=command,
                    working_dir="/workspace",
                    volumes={str(repo_path.resolve()): {"bind": "/workspace", "mode": "rw"}},
                    detach=True,
                    stderr=True,
                    stdout=True,
                    network_disabled=True,
                    mem_limit="1g",
                )
            except ImageNotFound:
                self.client.images.pull(image)
                container = self.client.containers.run(
                    image=image,
                    command=command,
                    working_dir="/workspace",
                    volumes={str(repo_path.resolve()): {"bind": "/workspace", "mode": "rw"}},
                    detach=True,
                    stderr=True,
                    stdout=True,
                    network_disabled=True,
                    mem_limit="1g",
                )

            result = container.wait(timeout=timeout)
            logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
            return {
                "exit_code": int(result.get("StatusCode", 1)),
                "output": logs,
                "duration": round(time.time() - started, 2),
            }
        except DockerException as exc:
            return {
                "exit_code": 1,
                "output": f"Docker execution failed: {exc}",
                "duration": round(time.time() - started, 2),
            }
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except DockerException:
                    pass

    @staticmethod
    def _command_for_framework(framework: str) -> tuple[str, str]:
        if framework == "npm":
            return (
                "node:20-alpine",
                "sh -lc \"npm install --silent || true; npm test -- --watch=false\"",
            )
        if framework == "unittest":
            return (
                "python:3.11-slim",
                (
                    "sh -lc \"pip install --no-cache-dir -r requirements.txt >/dev/null 2>&1 || true; "
                    "python -m unittest discover\""
                ),
            )
        return (
            "python:3.11-slim",
            (
                "sh -lc \"pip install --no-cache-dir -r requirements.txt >/dev/null 2>&1 || true; "
                "pip install --no-cache-dir pytest >/dev/null 2>&1; pytest -q\""
            ),
        )

