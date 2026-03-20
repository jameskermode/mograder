"""HTML callout parsing for marimo notebook exports.

This is a legacy fallback for notebooks that don't write a sidecar JSONL file
at runtime.  The primary extraction path is via ``MOGRADER_SIDECAR_PATH``
(see ``runner.py``).
"""

import re

from mograder.models import CheckResult

# Legacy pattern — matches any label starting with a letter (not just Q\d+).
CALLOUT_PATTERN = re.compile(
    r"([A-Za-z][A-Za-z0-9_ -]*):\s*([^\\\"<]+?)\\u0026lt;/strong\\u0026gt;\s*"
    r"\\u2014\s*(all checks passed|some checks failed|waiting[^\\]*)"
)

KIND_PATTERN = re.compile(
    r"data-kind='\\u0026quot;(success|danger|warn|info|neutral)\\u0026quot;'"
)


def parse_check_results(html_content: str) -> list[CheckResult]:
    """Extract check() callout results from exported HTML."""
    results = []
    seen = set()

    for match in CALLOUT_PATTERN.finditer(html_content):
        label_prefix = match.group(1).strip()
        label_rest = match.group(2).strip()
        status_text = match.group(3).strip()

        label = f"{label_prefix}: {label_rest}".rstrip("\\")

        if "all checks passed" in status_text:
            status = "success"
        elif "some checks failed" in status_text:
            status = "danger"
        elif "waiting" in status_text:
            status = "warn"
        else:
            status = "unknown"

        key = (label, status)
        if key not in seen:
            seen.add(key)
            results.append(CheckResult(label=label, status=status))

    results.sort(key=lambda r: r.label)
    return results


def count_cell_errors(html_content: str) -> int:
    """Count MarimoExceptionRaisedError occurrences in the HTML."""
    return html_content.count("MarimoExceptionRaisedError")
