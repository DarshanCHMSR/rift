from __future__ import annotations

import re
from typing import Any

from backend.agents.cicd_monitor import CICDMonitorAgent


class ErrorParserAgent:
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

    def _extract_issues(self, output: str) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        lines = output.splitlines()

        traceback_re = re.compile(r'File "(.+?)", line (\d+)')
        pytest_re = re.compile(r"^(.+?):(\d+):\s*(.+)$")

        for idx, line in enumerate(lines):
            trace_match = traceback_re.search(line)
            if trace_match:
                file_path = trace_match.group(1)
                line_no = int(trace_match.group(2))
                next_line = lines[idx + 1] if idx + 1 < len(lines) else line
                bug_type = self._classify(next_line)
                issues.append(
                    {
                        "file": file_path,
                        "line": line_no,
                        "error_type": bug_type,
                        "message": next_line.strip(),
                    }
                )
                continue

            pytest_match = pytest_re.search(line)
            if pytest_match and any(token in line for token in ("Error", "E999", "F401", "E302")):
                issues.append(
                    {
                        "file": pytest_match.group(1),
                        "line": int(pytest_match.group(2)),
                        "error_type": self._classify(pytest_match.group(3)),
                        "message": pytest_match.group(3).strip(),
                    }
                )

        if not issues and output.strip():
            issues.append(
                {
                    "file": "unknown",
                    "line": 1,
                    "error_type": self._classify(output),
                    "message": output.splitlines()[-1][:300],
                }
            )
        return issues

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
        if any(x in msg for x in ("flake8", "lint", "f401", "e302", "trailing whitespace")):
            return "LINTING"
        return "LOGIC"

