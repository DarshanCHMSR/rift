"""LLM-based fix agent — structured Gemini repair with retry validation.

Produces structured patches ``{file, line, replacement, explanation}``
rather than full-file rewrites.  If a Gemini patch makes tests *worse* the
agent reverts the change automatically.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

from backend.agents.cicd_monitor import CICDMonitorAgent
from backend.services.gemini_service import build_gemini_service

_MAX_CONTEXT_CHARS = 6_000


def _build_structured_prompt(
    file_content: str,
    file_name: str,
    line_no: int,
    error_type: str,
    error_message: str,
) -> str:
    truncated = file_content[:_MAX_CONTEXT_CHARS]
    if len(file_content) > _MAX_CONTEXT_CHARS:
        truncated += "\n# ... (truncated)"

    return textwrap.dedent(f"""\
        You are an expert code-repair assistant.

        TASK — return a JSON object describing the *minimal* fix.
        Return ONLY raw JSON, no markdown fences, no commentary.

        Required JSON schema:
        {{
          "file": "<filename>",
          "line": <line_number>,
          "replacement": "<replacement line or lines (use \\n for multi)>",
          "explanation": "<one-sentence explanation>"
        }}

        BUG
        ---
        File      : {file_name}
        Line      : {line_no}
        Error type: {error_type}
        Message   : {error_message}

        SOURCE (current)
        ----------------
        {truncated}
    """)


def _strip_fences(text: str) -> str:
    lines = text.splitlines()
    start, end = 0, len(lines)
    if lines and lines[0].strip().startswith("```"):
        start = 1
    if lines and lines[-1].strip() == "```":
        end -= 1
    return "\n".join(lines[start:end])


class LLMFixAgent:
    """Generates *structured* patches via Gemini, validates them, and reverts
    if they worsen the test suite."""

    def __init__(self) -> None:
        self.monitor = CICDMonitorAgent()
        self._gemini = build_gemini_service()

    @property
    def available(self) -> bool:
        return self._gemini.available

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_fix(
        self,
        repo_path: Path,
        issue: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Return a structured fix dict or ``None`` on failure."""
        if not self._gemini.available:
            return None

        file_hint = issue.get("file", "")
        file_path = self._resolve(repo_path, file_hint)
        if not file_path or not file_path.exists():
            return None

        original = file_path.read_text(encoding="utf-8", errors="ignore")
        line_no = issue.get("line", 1)
        error_type = issue.get("error_type", "LOGIC")
        message = issue.get("message", "")

        prompt = _build_structured_prompt(
            file_content=original,
            file_name=file_path.name,
            line_no=line_no,
            error_type=error_type,
            error_message=message,
        )

        try:
            import google.generativeai as genai  # type: ignore[import-untyped]

            genai.configure(api_key=self._gemini._api_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            response = model.generate_content(prompt)
            raw: str = _strip_fences(response.text.strip())  # type: ignore[attr-defined]
            patch = json.loads(raw)
        except Exception:
            return None

        # Validate patch structure
        if not isinstance(patch, dict):
            return None
        replacement = patch.get("replacement")
        explanation = patch.get("explanation", "Gemini LLM fix")
        if not replacement:
            return None

        return {
            "file": str(file_path.relative_to(repo_path)).replace("\\", "/"),
            "file_path": file_path,
            "line": line_no,
            "replacement": replacement,
            "explanation": explanation,
            "original_content": original,
            "error_type": error_type,
        }

    def apply_fix(self, fix: dict[str, Any]) -> bool:
        """Write the replacement into the file. Returns True on success."""
        try:
            fp: Path = fix["file_path"]
            lines = fix["original_content"].splitlines()
            line_idx = max(0, fix["line"] - 1)
            replacement_lines = fix["replacement"].split("\\n")

            if line_idx < len(lines):
                lines[line_idx : line_idx + 1] = replacement_lines
            else:
                lines.extend(replacement_lines)

            fp.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return True
        except Exception:
            return False

    def revert_fix(self, fix: dict[str, Any]) -> None:
        """Restore the original file content (undo a bad patch)."""
        try:
            fp: Path = fix["file_path"]
            fp.write_text(fix["original_content"], encoding="utf-8")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Batch helper used by the supervisor
    # ------------------------------------------------------------------

    def batch_generate(
        self,
        repo_path: Path,
        issues: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Generate structured fixes for a list of issues, record to timeline."""
        fixes: list[dict[str, Any]] = []
        for issue in issues:
            fix = self.generate_fix(repo_path, issue)
            if fix:
                fixes.append(fix)
        self.monitor.record(
            timeline,
            "llm_fix_agent",
            "patches_generated",
            {"count": len(fixes), "attempted": len(issues)},
        )
        return fixes

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve(repo_path: Path, hint: str) -> Path | None:
        if not hint or hint == "unknown":
            return None
        h = Path(hint)
        if h.is_absolute() and h.exists():
            return h
        candidate = repo_path / h
        if candidate.exists():
            return candidate
        found = list(repo_path.rglob(h.name))
        return found[0] if found else None
