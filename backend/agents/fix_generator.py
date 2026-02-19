from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from backend.agents.cicd_monitor import CICDMonitorAgent
from backend.services.gemini_service import build_gemini_service


class FixGeneratorAgent:
    def __init__(self) -> None:
        self.monitor = CICDMonitorAgent()
        # GeminiService is constructed lazily so the agent can be instantiated
        # even before the API key is confirmed valid.
        self._gemini = build_gemini_service()

    def run(
        self,
        repo_path: Path,
        issues: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        fixes: list[dict[str, Any]] = []
        gemini_calls = 0

        for issue in issues:
            bug_type = issue.get("error_type", "LOGIC")
            file_path = self._resolve_file(repo_path, issue.get("file", ""))
            line_no = issue.get("line", 1)
            message = issue.get("message", "")

            if bug_type == "LINTING" and file_path:
                description = self._fix_linting(file_path, line_no, message)
            elif bug_type == "SYNTAX" and file_path:
                description = self._fix_syntax(file_path, line_no, message)
            elif bug_type == "INDENTATION" and file_path:
                description = self._fix_indentation(file_path)
            elif bug_type == "IMPORT":
                description = self._fix_import(repo_path, file_path, line_no, message)
            elif bug_type in ("TYPE_ERROR", "LOGIC") and file_path:
                # ── Gemini LLM repair path ─────────────────────────────────
                description = self._gemini.repair_file(
                    file_path=file_path,
                    line_no=line_no,
                    error_type=bug_type,
                    error_message=message,
                )
                if description:
                    gemini_calls += 1
            else:
                description = None

            if not description:
                continue

            path_text = self._display_path(repo_path, file_path)
            summary = (
                f"{bug_type} error in {path_text} line {line_no} → Fix: {description}"
            )
            fixes.append(
                {
                    "bug_type": bug_type,
                    "file": path_text,
                    "line": line_no,
                    "description": description,
                    "summary": summary,
                }
            )

        self.monitor.record(
            timeline,
            "fix_generator",
            "fixes_applied",
            {
                "count": len(fixes),
                "gemini_calls": gemini_calls,
                "gemini_available": self._gemini.available,
            },
        )
        return fixes

    @staticmethod
    def _resolve_file(repo_path: Path, file_hint: str) -> Path | None:
        if not file_hint or file_hint == "unknown":
            return None
        hint = Path(file_hint)
        if hint.is_absolute() and hint.exists():
            return hint
        candidate = repo_path / hint
        if candidate.exists():
            return candidate
        fallback = list(repo_path.rglob(hint.name))
        return fallback[0] if fallback else None

    @staticmethod
    def _display_path(repo_path: Path, file_path: Path | None) -> str:
        if not file_path:
            return "unknown"
        try:
            return str(file_path.relative_to(repo_path)).replace("\\", "/")
        except ValueError:
            return str(file_path)

    def _fix_linting(self, file_path: Path, line_no: int, message: str) -> str | None:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines()
        changed = False

        if 1 <= line_no <= len(lines):
            target = lines[line_no - 1]
            if "unused import" in message.lower() and target.lstrip().startswith(("import ", "from ")):
                del lines[line_no - 1]
                changed = True
                description = "remove the import statement"
            else:
                updated = target.rstrip()
                if updated != target:
                    lines[line_no - 1] = updated
                    changed = True
                    description = "remove trailing whitespace"
                else:
                    description = "normalize formatting"
        else:
            description = "normalize formatting"

        if not changed:
            trimmed = [line.rstrip() for line in lines]
            if trimmed != lines:
                lines = trimmed
                changed = True
                description = "remove trailing whitespace"

        if changed:
            file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return description
        return None

    def _fix_syntax(self, file_path: Path, line_no: int, message: str) -> str | None:
        lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if not (1 <= line_no <= len(lines)):
            return None

        line = lines[line_no - 1]
        stripped = line.strip()
        starts = ("if ", "elif ", "for ", "while ", "def ", "class ", "except ", "with ")
        needs_colon = stripped.startswith(starts) and not stripped.endswith(":")

        if needs_colon or "expected ':'" in message.lower():
            lines[line_no - 1] = line.rstrip() + ":"
            file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return "add missing colon"
        return None

    def _fix_indentation(self, file_path: Path) -> str | None:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        updated = content.replace("\t", "    ")
        if updated != content:
            file_path.write_text(updated, encoding="utf-8")
            return "replace tabs with spaces"
        return None

    def _fix_import(
        self,
        repo_path: Path,
        file_path: Path | None,
        line_no: int,
        message: str,
    ) -> str | None:
        module_match = re.search(r"No module named ['\"]([^'\"]+)['\"]", message)
        module_name = module_match.group(1) if module_match else None

        if file_path and 1 <= line_no <= len(file_path.read_text(encoding="utf-8", errors="ignore").splitlines()):
            lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            target = lines[line_no - 1]
            if target.lstrip().startswith(("import ", "from ")):
                lines[line_no - 1] = f"# {target}  # disabled by AI fixer"
                file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return "disable failing import statement"

        if module_name and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", module_name):
            stub = repo_path / f"{module_name}.py"
            if not stub.exists():
                stub.write_text("# Auto-generated stub module for CI healing.\n", encoding="utf-8")
                return f"create stub module {module_name}.py"
        return None

