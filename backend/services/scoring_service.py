from __future__ import annotations


class ScoringService:
    def calculate_score(self, elapsed_seconds: float, commit_count: int) -> int:
        score = 100
        if elapsed_seconds < 300:
            score += 10
        if commit_count > 20:
            score -= 2 * (commit_count - 20)
        return max(0, score)

