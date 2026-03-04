"""Inject and parse grading cells in marimo notebooks."""

import re

from mograder.models import CheckResult

VERIFICATION_MARKER = "# === MOGRADER: VERIFICATION SUMMARY ==="
FEEDBACK_MARKER = "# === MOGRADER: GTA FEEDBACK ==="


def _build_verification_cell(checks: list[CheckResult], cell_errors: int) -> str:
    """Build the verification summary cell source."""
    checks_list = ",\n        ".join(
        f'("{c.label}", "{c.status.upper()}")'
        if c.status in ("success", "danger")
        else f'("{c.label}", "WAIT")'
        for c in checks
    )
    # Map statuses: success -> PASS, danger -> FAIL, anything else -> WAIT
    status_map = []
    for c in checks:
        if c.status == "success":
            status_map.append(f'("{c.label}", "PASS")')
        elif c.status == "danger":
            status_map.append(f'("{c.label}", "FAIL")')
        else:
            status_map.append(f'("{c.label}", "WAIT")')
    checks_list = ",\n        ".join(status_map)

    return f'''\

@app.cell(hide_code=True)
def _(mo):
    {VERIFICATION_MARKER}
    _mograder_checks = [
        {checks_list},
    ]
    _cell_errors = {cell_errors}
    _table = "\\n".join(
        f"| {{label}} | {{'PASS' if s == 'PASS' else 'FAIL' if s == 'FAIL' else 'WAIT'}} |"
        for label, s in _mograder_checks
    )
    mo.callout(mo.md(f"## Verification Summary\\n\\n"
        f"| Check | Result |\\n|-------|--------|\\n{{_table}}\\n\\n"
        f"Cell errors: {{_cell_errors}}"),
        kind="success" if all(s == "PASS" for _, s in _mograder_checks) else "danger")
    return

'''


def _build_feedback_cell() -> str:
    """Build the GTA feedback cell source."""
    return f'''\
@app.cell
def _(mo):
    {FEEDBACK_MARKER}
    # Set the mark (0-100) and write 2-3 sentences of feedback, then save.
    _mark = None       # e.g. _mark = 65
    _feedback = ""     # e.g. _feedback = "Good analysis of the DP approach..."

    # --- display (do not edit below) ---
    if _mark is not None:
        mo.callout(mo.md(f"**Mark: {{_mark}}/100**\\n\\n{{_feedback}}"), kind="success")
    else:
        mo.callout(mo.md("**Awaiting GTA feedback** — edit `_mark` and `_feedback` above"), kind="warn")
    return

'''


def has_grading_cells(source_lines: list[str]) -> bool:
    """Detect if grading cells are already injected."""
    text = "".join(source_lines)
    return VERIFICATION_MARKER in text or FEEDBACK_MARKER in text


def inject_grading_cells(
    source_lines: list[str],
    checks: list[CheckResult],
    cell_errors: int = 0,
) -> list[str]:
    """Insert verification summary + GTA feedback cells before ``if __name__``.

    Returns modified source lines. Idempotent: if grading cells already exist,
    returns the input unchanged.
    """
    if has_grading_cells(source_lines):
        return source_lines

    verification = _build_verification_cell(checks, cell_errors)
    feedback = _build_feedback_cell()

    # Find the `if __name__` line
    insert_idx = None
    for i, line in enumerate(source_lines):
        if line.strip().startswith("if __name__"):
            insert_idx = i
            break

    if insert_idx is None:
        # Append at end
        insert_idx = len(source_lines)

    new_lines = (
        source_lines[:insert_idx]
        + (verification + feedback).splitlines(keepends=True)
        + source_lines[insert_idx:]
    )
    return new_lines


def parse_gta_feedback(source_lines: list[str]) -> tuple[int | None, str]:
    """Extract ``_mark`` and ``_feedback`` from a graded notebook.

    Looks for the MOGRADER: GTA FEEDBACK marker and parses the variable
    assignments that follow it.

    Returns (mark, feedback) where mark is None if not yet graded.
    """
    text = "".join(source_lines)
    if FEEDBACK_MARKER not in text:
        return (None, "")

    # Find the feedback section
    marker_idx = text.index(FEEDBACK_MARKER)
    section = text[marker_idx:]

    # Parse _mark
    mark_match = re.search(r"_mark\s*=\s*(\d+|None)", section)
    mark = None
    if mark_match and mark_match.group(1) != "None":
        mark = int(mark_match.group(1))

    # Parse _feedback - handle both single and double quoted strings
    feedback = ""
    fb_match = re.search(r'_feedback\s*=\s*"((?:[^"\\]|\\.)*)"', section)
    if not fb_match:
        fb_match = re.search(r"_feedback\s*=\s*'((?:[^'\\]|\\.)*)'", section)
    if fb_match:
        feedback = fb_match.group(1)

    return (mark, feedback)
