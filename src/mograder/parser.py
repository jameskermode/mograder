"""HTML callout parsing for marimo notebook exports."""

import re

from mograder.models import CheckResult

# Pattern to match callout elements in exported HTML.
# marimo renders callouts as <marimo-callout-output> custom elements with
# data-kind and content attributes that are HTML-entity-encoded.
CALLOUT_PATTERN = re.compile(
    r"(Q\d+):\s*([^\\\"<]+?)\\u0026lt;/strong\\u0026gt;\s*"
    r"\\u2014\s*(all checks passed|some checks failed|waiting[^\\]*)"
)

KIND_PATTERN = re.compile(
    r"data-kind='\\u0026quot;(success|danger|warn|neutral)\\u0026quot;'"
)


def parse_check_results(html_content: str) -> list[CheckResult]:
    """Extract check() callout results from exported HTML."""
    results = []
    seen = set()

    for match in CALLOUT_PATTERN.finditer(html_content):
        q_num = match.group(1)
        label_rest = match.group(2).strip()
        status_text = match.group(3).strip()

        label = f"{q_num}: {label_rest}".rstrip("\\")

        if "all checks passed" in status_text:
            status = "success"
        elif "some checks failed" in status_text:
            status = "danger"
        elif "waiting" in status_text:
            status = "warn"
        else:
            status = "unknown"

        key = (q_num, status)
        if key not in seen:
            seen.add(key)
            results.append(CheckResult(label=label, status=status))

    results.sort(key=lambda r: r.label)
    return results


def count_cell_errors(html_content: str) -> int:
    """Count MarimoExceptionRaisedError occurrences in the HTML."""
    return html_content.count("MarimoExceptionRaisedError")
