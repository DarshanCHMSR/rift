from __future__ import annotations

from typing import Any


class ScoringService:
    """Enhanced scoring: base 100, speed bonus, penalties, cap 0–120.

    Breakdown dict is returned alongside the final score for the frontend.
    """

    def calculate_score(
        self,
        elapsed_seconds: float,
        commit_count: int,
        *,
        sandbox_passed: bool | None = None,
        total_fixes: int = 0,
        final_status: str = "",
    ) -> dict[str, Any]:
        base = 100
        speed_bonus = 10 if elapsed_seconds < 300 else 0
        commit_penalty = 2 * max(0, commit_count - 20)
        sandbox_penalty = 20 if sandbox_passed is False else 0
        # zero_fix_bonus: repo already passes tests with no AI intervention needed.
        # Do NOT award this when the run FAILED — that would reward broken repos.
        run_failed = final_status in ("FAILED", "SANDBOX_FAILED")
        zero_fix_bonus = 5 if total_fixes == 0 and sandbox_passed is not False and not run_failed else 0

        raw = base + speed_bonus + zero_fix_bonus - commit_penalty - sandbox_penalty
        final = max(0, min(120, raw))

        return {
            "base": base,
            "speed_bonus": speed_bonus,
            "commit_penalty": commit_penalty,
            "sandbox_penalty": sandbox_penalty,
            "zero_fix_bonus": zero_fix_bonus,
            "final": final,
        }

