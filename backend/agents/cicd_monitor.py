from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class CICDMonitorAgent:
    def record(
        self,
        timeline: list[dict[str, Any]],
        stage: str,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        timeline.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "stage": stage,
                "status": status,
                "details": details or {},
            }
        )

