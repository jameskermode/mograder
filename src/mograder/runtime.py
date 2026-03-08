"""Runtime helpers for mograder notebooks.

Notebooks import either ``check`` (holistic grading) or ``Grader``
(per-question marks with reactive tracking) from this module.

Holistic usage::

    from mograder.runtime import check

Per-question marks usage::

    from mograder.runtime import Grader
    grader = Grader(mo, {"Q1": 10, "Q2": 15, "Analysis": 60})
    check = grader.check
"""

import json
import os

import marimo as mo


def _write_sidecar(label: str, check_status: str, details: list[str]) -> None:
    """Append a check result to the sidecar JSONL file (if configured).

    The runner sets ``MOGRADER_SIDECAR_PATH`` before executing the notebook.
    """
    path = os.environ.get("MOGRADER_SIDECAR_PATH")
    if not path:
        return
    record = {"label": label, "status": check_status, "details": details}
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def check(label, checks):
    """Run a list of (condition, message) checks and display coloured feedback.

    Args:
        label: Name of the test (e.g. "Q2: Model evaluation")
        checks: List of (bool_expr, fail_message) tuples

    Returns a coloured callout: green (PASS), red (FAIL), or amber (WAIT).
    """
    failures = [msg for ok, msg in checks if not ok]
    if not checks:
        _write_sidecar(label, "warn", [])
        return mo.callout(mo.md(f"**{label}** — waiting for your code"), kind="warn")
    if failures:
        _write_sidecar(label, "danger", failures)
        items = "\n".join(f"- {f}" for f in failures)
        return mo.callout(
            mo.md(f"**{label}** — some checks failed:\n\n{items}"),
            kind="danger",
        )
    _write_sidecar(label, "success", [])
    return mo.callout(mo.md(f"**{label}** — all checks passed"), kind="success")


class Grader:
    """Per-question marks with reactive score tracking.

    Usage in a marimo notebook::

        grader = Grader(mo, {"Q1": 10, "Q2": 15, "Analysis": 60})
        check = grader.check

    Then use ``check(label, checks)`` exactly like the standalone version.
    Call ``grader.scores()`` to display a reactive score table.
    """

    def __init__(self, mo, marks):
        self.mo = mo
        self.marks = marks
        self._state, self._set = mo.state({})

    def check(self, label, checks):
        """Check with auto marks badge and state tracking.

        Looks up marks from ``self.marks`` using the question key
        (text before the first colon in label).
        """
        _mo = self.mo
        key = label.split(":")[0].strip()
        avail = self.marks.get(key)

        failures = [msg for ok, msg in checks if not ok]
        passed = bool(checks) and not failures

        # Update reactive state
        self._set(lambda prev, k=key, p=passed: {**prev, k: p})

        # Build marks badge
        if avail is not None:
            earned = avail if passed else 0
            badge = f'<span style="float:right"><code>[{earned}/{avail} marks]</code></span>'
        else:
            badge = ""

        if not checks:
            _write_sidecar(label, "warn", [])
            return _mo.callout(
                _mo.md(f"{badge}**{label}** — waiting for your code"), kind="warn"
            )
        if failures:
            _write_sidecar(label, "danger", failures)
            items = "\n".join(f"- {f}" for f in failures)
            return _mo.callout(
                _mo.md(f"{badge}**{label}** — some checks failed:\n\n{items}"),
                kind="danger",
            )
        _write_sidecar(label, "success", [])
        return _mo.callout(
            _mo.md(f"{badge}**{label}** — all checks passed"), kind="success"
        )

    def scores(self):
        # MOGRADER_SCORES_CELL — removed during feedback export
        """Display a reactive score table callout."""
        _mo = self.mo
        results = self._state()
        auto = sum(v for k, v in self.marks.items() if results.get(k))
        total = sum(self.marks.values())
        rows = ""
        for q, pts in self.marks.items():
            got = pts if results.get(q) else 0
            icon = "PASS" if results.get(q) else ("FAIL" if q in results else "\u2014")
            rows += f"| {q} | {icon} | {got}/{pts} |\n"
        rows += f"| **Total** | | **{auto}/{total}** |\n"
        return _mo.callout(
            _mo.md(
                f"## Your Score\n\n"
                f"| Question | Status | Marks |\n|----------|--------|-------|\n{rows}"
            ),
            kind="success" if auto == total else "neutral",
        )


# Re-export remote helpers for use in notebooks
from mograder.remote import fetch, status, submit  # noqa: F401, E402
