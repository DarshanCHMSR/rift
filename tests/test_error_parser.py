"""Unit tests for ErrorParserAgent — Python, JS, TS, assertion, and fallback."""

import sys
import os

# Ensure the project root is on sys.path so `backend.*` imports resolve.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.agents.error_parser import ErrorParserAgent


parser = ErrorParserAgent()
_timeline: list = []


# ── Python traceback ─────────────────────────────────────────────────────────

def test_python_traceback():
    output = (
        'Traceback (most recent call last):\n'
        '  File "app/main.py", line 42, in run\n'
        "TypeError: 'NoneType' object is not callable\n"
    )
    issues = parser._extract_issues(output)
    assert len(issues) >= 1
    issue = issues[0]
    assert issue["file"] == "app/main.py"
    assert issue["line"] == 42
    assert issue["error_type"] == "TYPE_ERROR"
    assert issue["confidence"] >= 0.8


def test_pytest_short_format():
    output = "tests/test_math.py:10: AssertionError: assert 1 == 2\n"
    issues = parser._extract_issues(output)
    assert len(issues) >= 1
    assert issues[0]["line"] == 10


# ── JS stack trace ───────────────────────────────────────────────────────────

def test_js_stack_trace():
    output = (
        "ReferenceError: foo is not defined\n"
        "    at Object.<anonymous> (src/index.js:15:3)\n"
        "    at Module._compile (node:internal/modules/cjs/loader:1356:14)\n"
    )
    issues = parser._extract_issues(output)
    assert any(i["file"] == "src/index.js" and i["line"] == 15 for i in issues)


# ── TypeScript compiler error ────────────────────────────────────────────────

def test_ts_error():
    output = "src/utils.ts(25,10): error TS2339: Property 'foo' does not exist on type 'Bar'.\n"
    issues = parser._extract_issues(output)
    assert len(issues) >= 1
    assert issues[0]["file"] == "src/utils.ts"
    assert issues[0]["line"] == 25
    assert issues[0]["error_type"] == "TYPE_ERROR"


# ── Classification ───────────────────────────────────────────────────────────

def test_classify_indentation():
    assert parser._classify("IndentationError: unexpected indent") == "INDENTATION"


def test_classify_import():
    assert parser._classify("ModuleNotFoundError: No module named 'foo'") == "IMPORT"


def test_classify_syntax():
    assert parser._classify("SyntaxError: expected ':'") == "SYNTAX"


def test_classify_assertion():
    assert parser._classify("AssertionError: 1 != 2") == "ASSERTION"


def test_classify_logic_fallback():
    assert parser._classify("something unexpected happened") == "LOGIC"


# ── Confidence & raw_snippet ─────────────────────────────────────────────────

def test_confidence_and_snippet():
    output = (
        'File "a.py", line 5\n'
        "IndentationError: unexpected indent\n"
    )
    issues = parser._extract_issues(output)
    assert issues[0]["confidence"] > 0
    assert "raw_snippet" in issues[0]


# ── Fallback ─────────────────────────────────────────────────────────────────

def test_fallback_unknown():
    issues = parser._extract_issues("some random output with no patterns")
    assert len(issues) == 1
    assert issues[0]["file"] == "unknown"
    assert issues[0]["confidence"] <= 0.5
