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
    openai_api_key: str
    max_retries: int


def get_settings() -> Settings:
    return Settings(
        github_token=os.getenv("GITHUB_TOKEN", "").strip(),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        max_retries=_clamp_retry(os.getenv("MAX_RETRIES"), default=5),
    )

