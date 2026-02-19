"""Structured JSON logging setup for RIFT.

Call ``setup_logging()`` once at startup to configure structured JSON output
on stderr and optional per-run file logging inside ``backend/logs/``.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_LOGS_DIR = Path(__file__).resolve().parent.parent / "backend" / "logs"
_LOGS_DIR.mkdir(exist_ok=True)


class JSONFormatter(logging.Formatter):
    """Emit each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)
        # Attach extra fields (e.g. run_id) if provided
        for key in ("run_id",):
            val = getattr(record, key, None)
            if val is not None:
                log_entry[key] = val
        return json.dumps(log_entry, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Configure root + rift logger with structured JSON formatter."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    root.addHandler(handler)

    # Silence noisy third-party loggers
    for noisy in ("httpx", "httpcore", "docker", "urllib3", "git"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_run_logger(run_id: str) -> logging.Logger:
    """Return a logger with a per-run file handler for persistent logs."""
    logger = logging.getLogger(f"rift.run.{run_id}")
    if not logger.handlers:
        fh = logging.FileHandler(_LOGS_DIR / f"{run_id}.log", encoding="utf-8")
        fh.setFormatter(JSONFormatter())
        logger.addHandler(fh)
    return logger
