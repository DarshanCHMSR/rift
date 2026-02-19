"""Unit tests for ScoringService — enhanced scoring logic."""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.services.scoring_service import ScoringService


svc = ScoringService()


def test_base_score():
    result = svc.calculate_score(elapsed_seconds=400, commit_count=5)
    assert result["base"] == 100
    assert result["speed_bonus"] == 0
    assert result["final"] == 100


def test_speed_bonus():
    result = svc.calculate_score(elapsed_seconds=200, commit_count=5)
    assert result["speed_bonus"] == 10
    assert result["final"] == 110


def test_commit_penalty():
    result = svc.calculate_score(elapsed_seconds=400, commit_count=25)
    assert result["commit_penalty"] == 10
    assert result["final"] == 90


def test_sandbox_penalty():
    result = svc.calculate_score(
        elapsed_seconds=400, commit_count=5, sandbox_passed=False
    )
    assert result["sandbox_penalty"] == 20
    assert result["final"] == 80


def test_zero_fix_bonus():
    result = svc.calculate_score(
        elapsed_seconds=400, commit_count=5, total_fixes=0, sandbox_passed=True
    )
    assert result["zero_fix_bonus"] == 5
    assert result["final"] == 105


def test_cap_at_120():
    # speed + zero_fix should still cap at 120
    result = svc.calculate_score(
        elapsed_seconds=100, commit_count=0, total_fixes=0, sandbox_passed=True
    )
    assert result["final"] <= 120


def test_floor_at_zero():
    result = svc.calculate_score(
        elapsed_seconds=600, commit_count=100, sandbox_passed=False
    )
    assert result["final"] >= 0
