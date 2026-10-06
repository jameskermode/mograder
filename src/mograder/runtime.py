"""Runtime helpers for mograder notebooks.

Notebooks import either ``check`` (holistic grading) or ``Grader``
(per-question marks with reactive tracking) from this module.

Holistic usage::

    from mograder.runtime import check

Per-question marks usage::

    from mograder.runtime import Grader
    grader = Grader({"Q1": 10, "Q2": 15, "Analysis": 60})
    check = grader.check
"""

import json
import os
import re

import marimo as mo

_HIDDEN_TESTS_RE = re.compile(r"#\s*mograder-hidden-tests\s*=\s*true")

__all__ = ["check", "Grader", "hint", "fetch", "submit", "status"]


def _parse_checks(
    checks: list[tuple[bool, str] | tuple[bool, str, int | float]],
) -> list[tuple[bool, str, float]]:
    """Normalize check tuples to ``(ok, msg, weight)`` with default weight=1."""
    parsed = []
    for item in checks:
        if len(item) == 3:
            ok, msg, weight = item
            parsed.append((ok, msg, float(weight)))
        else:
            ok, msg = item
            parsed.append((ok, msg, 1.0))
    return parsed


def _write_sidecar(
    label: str,
    check_status: str,
    details: list[str],
    earned_weight: float = 0,
    total_weight: float = 0,
) -> None:
    """Append a check result to the sidecar JSONL file (if configured).

    The runner sets ``MOGRADER_SIDECAR_PATH`` before executing the notebook.
    """
    path = os.environ.get("MOGRADER_SIDECAR_PATH")
    if not path:
        return
    record = {
        "label": label,
        "status": check_status,
        "details": details,
        "earned_weight": earned_weight,
        "total_weight": total_weight,
    }
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def hint(*hints: str) -> mo.Html:
    """Display progressive hints in a collapsed accordion."""
    if len(hints) == 1:
        items = {"Hint": mo.md(hints[0])}
    else:
        items = {f"Hint {i}": mo.md(h) for i, h in enumerate(hints, 1)}
    return mo.accordion(items)


def check(
    label: str, checks: list[tuple[bool, str] | tuple[bool, str, int | float]]
) -> mo.Html:
    """Run a list of checks and display coloured feedback.

    Args:
        label: Name of the test (e.g. "Q2: Model evaluation")
        checks: List of ``(bool_expr, fail_message)`` or
                ``(bool_expr, fail_message, weight)`` tuples.

    Returns a coloured callout: green (PASS), red (FAIL), or amber (WAIT).
    """
    if not checks:
        _write_sidecar(label, "warn", [])
        return mo.callout(mo.md(f"**{label}** — waiting for your code"), kind="warn")
    parsed = _parse_checks(checks)
    failures = [msg for ok, msg, _w in parsed if not ok]
    earned_w = sum(w for ok, _, w in parsed if ok)
    total_w = sum(w for _, _, w in parsed)
    if failures:
        if earned_w > 0:
            sidecar_status = "partial"
        else:
            sidecar_status = "danger"
        _write_sidecar(label, sidecar_status, failures, earned_w, total_w)
        items = "\n".join(f"- {f}" for f in failures)
        return mo.callout(
            mo.md(f"**{label}** — some checks failed:\n\n{items}"),
            kind="danger",
        )
    _write_sidecar(label, "success", [], earned_w, total_w)
    return mo.callout(mo.md(f"**{label}** — all checks passed"), kind="success")


class Grader:
    """Per-question marks with reactive score tracking.

    Usage in a marimo notebook::

        grader = Grader({"Q1": 10, "Q2": 15, "Analysis": 60})
        check = grader.check

    Then use ``check(label, checks)`` exactly like the standalone version.
    Call ``grader.scores()`` to display a reactive score table.
    """

    def __init__(self, marks: dict[str, int | float]):
        self.marks = marks
        self._state, self._set = mo.state({})
        # Detect hidden tests flag from PEP 723 metadata in __file__
        self._has_hidden = False
        try:
            import __main__

            if hasattr(__main__, "__file__") and __main__.__file__:
                with open(__main__.__file__) as f:
                    head = f.read(4096)
                self._has_hidden = bool(_HIDDEN_TESTS_RE.search(head))
        except Exception:
            pass

    def check(
        self,
        label: str,
        checks: list[tuple[bool, str] | tuple[bool, str, int | float]],
    ) -> mo.Html:
        """Check with auto marks badge and state tracking.

        Looks up marks from ``self.marks`` using the question key
        (text before the first colon in label).  Each check can
        optionally carry a weight as a third element; the default
        weight is 1.  Earned marks are proportional to the weight of
        passing checks.
        """
        key = label.split(":")[0].strip()
        avail = self.marks.get(key)

        if not checks:
            _write_sidecar(label, "warn", [])
            if avail is not None and not self._has_hidden:
                badge = (
                    f'<span style="float:right"><code>[0/{avail} marks]</code></span>'
                )
            else:
                badge = ""
            return mo.callout(
                mo.md(f"{badge}**{label}** — waiting for your code"), kind="warn"
            )

        parsed = _parse_checks(checks)
        failures = [msg for ok, msg, _w in parsed if not ok]
        earned_w = sum(w for ok, _, w in parsed if ok)
        total_w = sum(w for _, _, w in parsed)

        # Update reactive state with (earned_weight, total_weight) tuple
        self._set(lambda prev, k=key, ew=earned_w, tw=total_w: {**prev, k: (ew, tw)})

        # Build marks badge (suppressed when hidden tests exist)
        if avail is not None and not self._has_hidden:
            earned = round(avail * earned_w / total_w, 1) if total_w > 0 else 0
            # Display as int if whole number
            earned_str = str(int(earned)) if earned == int(earned) else str(earned)
            badge = f'<span style="float:right"><code>[{earned_str}/{avail} marks]</code></span>'
        else:
            badge = ""

        if failures:
            if earned_w > 0:
                kind = "info"  # blue — partial credit
                sidecar_status = "partial"
            else:
                kind = "danger"
                sidecar_status = "danger"
            _write_sidecar(label, sidecar_status, failures, earned_w, total_w)
            items = "\n".join(f"- {f}" for f in failures)
            return mo.callout(
                mo.md(f"{badge}**{label}** — some checks failed:\n\n{items}"),
                kind=kind,
            )
        _write_sidecar(label, "success", [], earned_w, total_w)
        return mo.callout(
            mo.md(f"{badge}**{label}** — all checks passed"), kind="success"
        )

    def scores(self):
        # MOGRADER_SCORES_CELL — removed during feedback export
        """Display a reactive score table callout."""
        if self._has_hidden:
            return mo.callout(
                mo.md("Scores will be available in your feedback after grading."),
                kind="neutral",
            )
        results = self._state()
        total = sum(self.marks.values())
        auto = 0.0
        rows = ""
        for q, pts in self.marks.items():
            val = results.get(q)
            if isinstance(val, tuple):
                # (earned_weight, total_weight) from partial credit
                ew, tw = val
                got = round(pts * ew / tw, 1) if tw > 0 else 0
                if ew == tw:
                    icon = "PASS"
                elif ew == 0:
                    icon = "FAIL"
                else:
                    icon = "PARTIAL"
            elif isinstance(val, bool):
                # Backward compat: old bool state
                got = pts if val else 0
                icon = "PASS" if val else "FAIL"
            elif val is None or q not in results:
                got = 0
                icon = "\u2014"
            else:
                got = 0
                icon = "\u2014"
            auto += got
            got_str = str(int(got)) if got == int(got) else str(got)
            rows += f"| {q} | {icon} | {got_str}/{pts} |\n"
        auto_str = str(int(auto)) if auto == int(auto) else str(auto)
        rows += f"| **Total** | | **{auto_str}/{total}** |\n"
        return mo.callout(
            mo.md(
                f"## Your Score\n\n"
                f"| Question | Status | Marks |\n|----------|--------|-------|\n{rows}"
            ),
            kind="success" if auto == total else "neutral",
        )


# Re-export remote helpers for use in notebooks
def count_response_words(source: str, cell: str = "written_analysis"):
    """Count the words in the written answer held by the cell named ``cell``.

    ``source`` is the text of a marimo notebook. The answer is taken to be the
    longest string literal in that cell, which covers both the release form
    (a plain ``mo.md(r\"\"\"...\"\"\")`` cell edited by the student) and the
    source form (a ``response_text`` model answer). Inline and display maths
    count as one word each. Returns ``None`` if the cell is not found.
    """
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == cell:
            strings = [
                n.value
                for n in ast.walk(node)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
            ]
            if not strings:
                return 0
            text = max(strings, key=len)
            text = re.sub(r"\$\$.*?\$\$|\$[^$]*\$", " MATH ", text, flags=re.S)
            return len(re.findall(r"\S+", text))
    return None


def _word_count_colour(n: int, target: tuple[int, int]) -> str:
    lo, hi = target
    if lo <= n <= hi:
        return "#34A853"  # green
    if lo - 100 <= n < lo or hi < n <= hi + 100:
        return "#FF9800"  # amber
    return "#EA4335"  # red


def word_count(
    notebook_file, cell: str = "written_analysis", target=(300, 500)
) -> mo.Html:
    """Live word count for a written answer in a plain markdown cell.

    Students write their answer directly in a markdown cell named ``cell``
    (``def written_analysis(mo): mo.md(...)``), with no variable to assign.
    Pass the notebook file wrapped with ``mo.watch.file`` so the count
    refreshes whenever marimo autosaves the notebook::

        @app.cell(hide_code=True)
        def _(mo):
            notebook_file = mo.watch.file(__file__)
            return (notebook_file,)

        @app.cell(hide_code=True)
        def _(notebook_file):
            from mograder.runtime import word_count as _word_count
            _word_count(notebook_file)
            return
    """
    from pathlib import Path

    reader = (
        notebook_file if hasattr(notebook_file, "read_text") else Path(notebook_file)
    )
    n = count_response_words(reader.read_text(), cell=cell)
    if n is None:
        return mo.md(f"*Word count unavailable: no cell named `{cell}`.*")
    colour = _word_count_colour(n, target)
    lo, hi = target
    return mo.md(
        f'<span style="color:{colour}; font-weight:bold">Word count: {n}</span> '
        f"(target: {lo}–{hi}; updates when the notebook is saved)"
    )


from mograder.remote import fetch, status, submit  # noqa: F401, E402
