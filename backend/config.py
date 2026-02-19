from __future__ import annotations

import os
from dataclasses import dataclass


def _clamp_retry(value: str | None, default: int = 5) -> int:
    try:
        parsed = int(value or default)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, 50))


@dataclass(frozen=True)
class Settings:
    github_token: str
    gemini_api_key: str
    max_retries: int
    rift_api_key: str = ""
    # Legacy field kept for backward compatibility with any existing callers.
    openai_api_key: str = ""


def get_settings() -> Settings:
    return Settings(
        github_token=os.getenv("GITHUB_TOKEN", "").strip(),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        max_retries=_clamp_retry(os.getenv("MAX_RETRIES"), default=5),
        rift_api_key=os.getenv("RIFT_API_KEY", "").strip(),
    )

