from __future__ import annotations

import re
from typing import Any

from backend.agents.cicd_monitor import CICDMonitorAgent


class ErrorParserAgent:
    """Parses test / lint output into structured issue dicts.

    Supports Python tracebacks, pytest short format, JS / TS stack traces,
    and assertion errors.  Each issue carries a ``confidence`` score (0.0–1.0)
    and an optional ``raw_snippet`` with surrounding context lines.
    """

    def __init__(self) -> None:
        self.monitor = CICDMonitorAgent()

    def run(self, test_output: str, timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        issues = self._extract_issues(test_output)
        self.monitor.record(
            timeline,
            "error_parser",
            "errors_parsed",
            {"count": len(issues)},
        )
        return issues

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    def _extract_issues(self, output: str) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        lines = output.splitlines()

        # Compiled patterns
        traceback_re = re.compile(r'File "(.+?)", line (\d+)')
        pytest_re = re.compile(r"^(.+?):(\d+):\s*(.+)$")
        js_stack_re = re.compile(r"at\s+.+?\s+\((.+?):(\d+):\d+\)")
        ts_error_re = re.compile(r"^(.+?)\((\d+),\d+\):\s*error\s+TS\d+:\s*(.+)$")
        assertion_re = re.compile(r"AssertionError|assert\s+.+==.+", re.IGNORECASE)

        seen: set[tuple[str, int]] = set()

        for idx, line in enumerate(lines):
            # ── Python traceback ──────────────────────────────────
            trace_match = traceback_re.search(line)
            if trace_match:
                fp = trace_match.group(1)
                ln = int(trace_match.group(2))
                key = (fp, ln)
                if key in seen:
                    continue
                seen.add(key)
                next_line = lines[idx + 1] if idx + 1 < len(lines) else line
                bug_type = self._classify(next_line)
                issues.append(self._make_issue(
                    fp, ln, bug_type, next_line.strip(),
                    confidence=0.9,
                    raw_snippet=self._snippet(lines, idx, span=2),
                ))
                continue

            # ── JS / Node stack trace ─────────────────────────────
            js_match = js_stack_re.search(line)
            if js_match:
                fp = js_match.group(1)
                ln = int(js_match.group(2))
                key = (fp, ln)
                if key in seen:
                    continue
                seen.add(key)
                # Look backwards for the error message line
                err_msg = line.strip()
                for back in range(max(0, idx - 3), idx):
                    if "Error" in lines[back]:
                        err_msg = lines[back].strip()
                        break
                issues.append(self._make_issue(
                    fp, ln, self._classify(err_msg), err_msg,
                    confidence=0.85,
                    raw_snippet=self._snippet(lines, idx, span=2),
                ))
                continue

            # ── TypeScript compiler error ────────────────────────
            ts_match = ts_error_re.search(line)
            if ts_match:
                fp = ts_match.group(1)
                ln = int(ts_match.group(2))
                msg = ts_match.group(3).strip()
                key = (fp, ln)
                if key in seen:
                    continue
                seen.add(key)
                issues.append(self._make_issue(
                    fp, ln, "TYPE_ERROR", msg,
                    confidence=0.9,
                    raw_snippet=line.strip(),
                ))
                continue

            # ── pytest short-form ─────────────────────────────────
            pytest_match = pytest_re.search(line)
            if pytest_match and any(
                tok in line for tok in ("Error", "E999", "F401", "E302", "assert")
            ):
                fp = pytest_match.group(1)
                ln = int(pytest_match.group(2))
                msg = pytest_match.group(3).strip()
                key = (fp, ln)
                if key in seen:
                    continue
                seen.add(key)
                issues.append(self._make_issue(
                    fp, ln, self._classify(msg), msg,
                    confidence=0.85,
                    raw_snippet=self._snippet(lines, idx, span=1),
                ))
                continue

            # ── Assertion error (standalone) ──────────────────────
            if assertion_re.search(line) and not any(i["message"] == line.strip() for i in issues):
                issues.append(self._make_issue(
                    "unknown", 1, "ASSERTION", line.strip(),
                    confidence=0.7,
                    raw_snippet=self._snippet(lines, idx, span=2),
                ))

        # Fallback: whole output
        if not issues and output.strip():
            issues.append(self._make_issue(
                "unknown", 1, self._classify(output),
                output.splitlines()[-1][:300],
                confidence=0.4,
                raw_snippet=output[:500],
            ))
        return issues

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_issue(
        file: str,
        line: int,
        error_type: str,
        message: str,
        *,
        confidence: float = 0.8,
        raw_snippet: str = "",
    ) -> dict[str, Any]:
        return {
            "file": file,
            "line": line,
            "error_type": error_type,
            "message": message,
            "confidence": confidence,
            "raw_snippet": raw_snippet,
        }

    @staticmethod
    def _snippet(lines: list[str], center: int, span: int = 2) -> str:
        start = max(0, center - span)
        end = min(len(lines), center + span + 1)
        return "\n".join(lines[start:end])

    @staticmethod
    def _classify(message: str) -> str:
        msg = message.lower()
        if "indentationerror" in msg or "taberror" in msg:
            return "INDENTATION"
        if "syntaxerror" in msg or "expected ':'" in msg:
            return "SYNTAX"
        if "importerror" in msg or "modulenotfounderror" in msg or "no module named" in msg:
            return "IMPORT"
        if "typeerror" in msg:
            return "TYPE_ERROR"
        if "assertionerror" in msg or "assert " in msg:
            return "ASSERTION"
        if any(x in msg for x in ("flake8", "lint", "f401", "e302", "trailing whitespace")):
            return "LINTING"
        if "referenceerror" in msg or "is not defined" in msg:
            return "REFERENCE"
        return "LOGIC"

