"""Gemini LLM service for AI-powered code repair.

Used by ``FixGeneratorAgent`` to fix bug types that cannot be handled by
deterministic rules (TYPE_ERROR, LOGIC, and any unrecognised error category).

The service is intentionally stateless: each call creates a fresh model
instance so settings changes are picked up without restarting the server.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

_IMPORT_ERROR: str | None = None
try:
    import google.generativeai as genai  # type: ignore[import-untyped]
except ImportError as _exc:
    genai = None  # type: ignore[assignment]
    _IMPORT_ERROR = str(_exc)

# The Gemini model to use.  gemini-1.5-flash is fast and free-tier friendly.
_MODEL_NAME = "gemini-1.5-flash"

# Safety: cap the context we send to Gemini to avoid huge token bills.
_MAX_FILE_CHARS = 8_000   # ~2 000 tokens
_MAX_OUTPUT_CHARS = 4_000  # generous ceiling for the patched snippet


def _build_prompt(
    file_content: str,
    file_path_hint: str,
    line_no: int,
    error_type: str,
    error_message: str,
) -> str:
    truncated = file_content[:_MAX_FILE_CHARS]
    if len(file_content) > _MAX_FILE_CHARS:
        truncated += "\n# ... (truncated)"

    return textwrap.dedent(f"""\
        You are an expert Python/JavaScript code repair assistant.

        TASK
        ----
        Fix the bug described below in the source file.  Return ONLY the
        complete corrected file content — no explanations, no markdown fences,
        no extra commentary.  The output will be written directly back to disk.

        BUG DETAILS
        -----------
        File      : {file_path_hint}
        Line      : {line_no}
        Error type: {error_type}
        Message   : {error_message}

        SOURCE FILE (current state)
        ---------------------------
        {truncated}
    """)


class GeminiService:
    """Thin wrapper around the Google Generative AI SDK for code repair."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._available = bool(api_key and genai is not None)

    @property
    def available(self) -> bool:
        return self._available

    def repair_file(
        self,
        file_path: Path,
        line_no: int,
        error_type: str,
        error_message: str,
    ) -> str | None:
        """Ask Gemini to fix the given file and overwrite it with the result.

        Returns a short human-readable description of the fix on success, or
        ``None`` if the service is unavailable or the request fails.
        """
        if not self._available:
            return None

        if not file_path.exists():
            return None

        original = file_path.read_text(encoding="utf-8", errors="ignore")
        if not original.strip():
            return None

        try:
            genai.configure(api_key=self._api_key)  # type: ignore[attr-defined]
            model = genai.GenerativeModel(_MODEL_NAME)  # type: ignore[attr-defined]
            prompt = _build_prompt(
                file_content=original,
                file_path_hint=file_path.name,
                line_no=line_no,
                error_type=error_type,
                error_message=error_message,
            )
            response = model.generate_content(prompt)
            fixed_content: str = response.text  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            # Never crash the agent pipeline on Gemini errors.
            return f"Gemini unavailable: {exc}"

        if not fixed_content or not fixed_content.strip():
            return None

        # Strip accidental markdown fences that some models add despite instructions.
        fixed_content = _strip_fences(fixed_content)

        # Safety: don't overwrite if Gemini returned something suspiciously short.
        if len(fixed_content.strip()) < 10:
            return None

        file_path.write_text(fixed_content[:_MAX_OUTPUT_CHARS], encoding="utf-8")
        return f"Gemini-repaired {error_type.lower()} bug at line {line_no}"

    def explain_error(self, error_type: str, error_message: str, snippet: str) -> str:
        """Return a one-sentence explanation of the error (used for logging)."""
        if not self._available:
            return ""
        try:
            genai.configure(api_key=self._api_key)  # type: ignore[attr-defined]
            model = genai.GenerativeModel(_MODEL_NAME)  # type: ignore[attr-defined]
            prompt = (
                f"In one sentence, explain what caused this {error_type} error:\n"
                f"Message: {error_message}\nCode snippet:\n{snippet[:500]}"
            )
            return model.generate_content(prompt).text.strip()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return ""


def _strip_fences(text: str) -> str:
    """Remove leading/trailing markdown code fences from LLM output."""
    lines = text.splitlines()
    start = 0
    end = len(lines)
    if lines and lines[0].startswith("```"):
        start = 1
    if lines and lines[-1].strip() == "```":
        end -= 1
    return "\n".join(lines[start:end])


def build_gemini_service() -> GeminiService:
    """Factory that reads the API key from settings at call time."""
    from backend.config import get_settings  # local import avoids circular deps
    return GeminiService(api_key=get_settings().gemini_api_key)
