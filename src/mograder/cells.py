"""Inject and parse grading cells in marimo notebooks."""

import ast
import re
from pathlib import Path

from mograder.models import CheckResult

VERIFICATION_MARKER = "# === MOGRADER: VERIFICATION SUMMARY ==="
FEEDBACK_MARKER = "# === MOGRADER: GTA FEEDBACK ==="
MARKS_MARKER = "# === MOGRADER: MARKS ==="
SCORES_MARKER = "# MOGRADER_SCORES_CELL"


def extract_marking_scale(source_lines: list[str]) -> str | None:
    """Extract the Marking Scale admonition from a source notebook.

    Looks for ``/// details | Marking Scale`` ... ``///`` block in markdown cells.
    Returns the markdown content (without the admonition wrapper), or None.
    """
    import textwrap

    text = "".join(source_lines)
    match = re.search(
        r"///\s*details\s*\|\s*Marking Scale\s*\n(.*?)\n\s*///",
        text,
        re.DOTALL,
    )
    if not match:
        return None
    content = match.group(1)
    lines = content.splitlines()
    # Skip directive lines (e.g. "    type: info") and blank lines at start
    start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("type:") or not stripped:
            start = i + 1
        else:
            break
    body = "\n".join(lines[start:])
    return textwrap.dedent(body).strip() or None


def parse_marks_metadata(source_lines: list[str]) -> dict[str, int | float] | None:
    """Extract marks metadata from a notebook.

    Reads ``_marks = {...}`` from the MARKS_MARKER cell. All question marks
    (both auto-checked and manual) must be listed in this single dict.

    Returns None if no MARKS_MARKER cell found.
    """
    text = "".join(source_lines)
    if MARKS_MARKER not in text:
        return None

    marker_idx = text.index(MARKS_MARKER)
    section = text[marker_idx:]

    dict_match = re.search(r"_marks\s*=\s*(\{[^}]+\})", section)
    if not dict_match:
        return None
    try:
        marks = ast.literal_eval(dict_match.group(1))
    except (ValueError, SyntaxError):
        return None

    return marks if marks else None


def parse_auto_marks(source_lines: list[str]) -> int | None:
    """Extract auto-scored marks from a verification cell with marks data.

    Looks for ``_mograder_marks`` and ``_mograder_checks`` in the verification
    cell and computes sum of marks for PASS checks.

    Returns None if no marks data found in the verification cell.
    """
    text = "".join(source_lines)
    if VERIFICATION_MARKER not in text or "_mograder_marks" not in text:
        return None

    marker_idx = text.index(VERIFICATION_MARKER)
    section = text[marker_idx:]

    # Extract _mograder_marks dict
    marks_match = re.search(r"_mograder_marks\s*=\s*(\{[^}]+\})", section)
    if not marks_match:
        return None
    try:
        marks_dict = ast.literal_eval(marks_match.group(1))
    except (ValueError, SyntaxError):
        return None

    # Extract _mograder_checks list
    checks_match = re.search(r"_mograder_checks\s*=\s*\[(.*?)\]", section, re.DOTALL)
    if not checks_match:
        return None

    # Parse check tuples to find PASS results
    auto_mark = 0
    for m in re.finditer(r'\("([^"]+)",\s*"([^"]+)"\)', checks_match.group(1)):
        label, status = m.group(1), m.group(2)
        key = label.split(":")[0].strip()
        if status == "PASS" and key in marks_dict:
            auto_mark += marks_dict[key]

    return auto_mark


def _build_verification_cell(
    checks: list[CheckResult],
    cell_errors: int,
    marks: dict[str, int | float] | None = None,
) -> str:
    """Build the verification summary cell source."""
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
    checks_block = f"\n        {checks_list},\n    " if checks_list else ""

    if marks is None:
        return f"""\

@app.cell(hide_code=True)
def _(mo):
    {VERIFICATION_MARKER}
    _mograder_checks = [{checks_block}]
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

"""

    # Build marks-aware version
    marks_repr = repr(marks)

    # Compute check keys for matching
    check_keys = {c.label.split(":")[0].strip() for c in checks}
    # Manual questions are those in marks but not in checks
    manual_keys = [k for k in marks if k not in check_keys]

    # Build manual rows string
    manual_rows = ""
    for k in manual_keys:
        manual_rows += f'    _table += "| {k} | — | ?/{marks[k]} |\\n"\n'

    return f"""\

@app.cell(hide_code=True)
def _(mo):
    {VERIFICATION_MARKER}
    _mograder_checks = [{checks_block}]
    _mograder_marks = {marks_repr}
    _cell_errors = {cell_errors}
    _auto_earned = 0
    _table = ""
    for _label, _s in _mograder_checks:
        _key = _label.split(":")[0].strip()
        _avail = _mograder_marks.get(_key, "")
        _earned = _avail if _s == "PASS" else 0
        if _s == "PASS" and isinstance(_avail, (int, float)):
            _auto_earned += _avail
        _marks_col = f"{{_earned}}/{{_avail}}" if _avail != "" else ""
        _table += f"| {{_label}} | {{_s}} | {{_marks_col}} |\\n"
{manual_rows}\
    _total_avail = sum(_mograder_marks.values())
    _table += f"| **Total** | | **{{_auto_earned}}/{{_total_avail}}** |\\n"
    mo.callout(mo.md(f"## Verification Summary\\n\\n"
        f"| Check | Result | Marks |\\n|-------|--------|-------|\\n{{_table}}\\n"
        f"Cell errors: {{_cell_errors}}"),
        kind="success" if all(s == "PASS" for _, s in _mograder_checks) else "danger")
    return

"""


def _build_feedback_cell(
    auto_mark: int | float | None = None,
    manual_available: int | float | None = None,
    total_available: int | float | None = None,
) -> str:
    """Build the GTA feedback cell source."""
    if auto_mark is None:
        return f"""\
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

"""

    return f"""\
@app.cell
def _(mo):
    {FEEDBACK_MARKER}
    # Auto marks: {auto_mark}/{total_available - manual_available}
    # Set _mark for manual questions (out of {manual_available}), then save.
    _mark = None       # e.g. _mark = {manual_available}
    _feedback = ""     # e.g. _feedback = "Good analysis of the DP approach..."

    # --- display (do not edit below) ---
    if _mark is not None:
        _total = {auto_mark} + _mark
        mo.callout(mo.md(f"**Mark: {{_total}}/{total_available}** (auto: {auto_mark}, manual: {{_mark}})\\n\\n{{_feedback}}"), kind="success")
    else:
        mo.callout(mo.md("**Awaiting GTA feedback** — edit `_mark` (out of {manual_available}) and `_feedback` above\\n\\n"
            f"Auto marks so far: {auto_mark}/{total_available - manual_available}"), kind="warn")
    return

"""


def has_grading_cells(source_lines: list[str]) -> bool:
    """Detect if grading cells are already injected."""
    text = "".join(source_lines)
    return VERIFICATION_MARKER in text or FEEDBACK_MARKER in text


def inject_grading_cells(
    source_lines: list[str],
    checks: list[CheckResult],
    cell_errors: int = 0,
    marks: dict[str, int | float] | None = None,
) -> list[str]:
    """Insert verification summary + GTA feedback cells before ``if __name__``.

    Returns modified source lines. Idempotent: if grading cells already exist,
    returns the input unchanged.

    When ``marks`` is provided, the verification cell includes a marks column
    and the feedback cell is pre-configured for manual-only grading.
    """
    if has_grading_cells(source_lines):
        return source_lines

    if marks is not None:
        # Compute auto marks and manual available
        check_keys = {c.label.split(":")[0].strip() for c in checks}
        auto_mark = sum(
            marks[k]
            for k in check_keys
            if k in marks
            and any(
                c.status == "success"
                for c in checks
                if c.label.split(":")[0].strip() == k
            )
        )
        manual_available = sum(v for k, v in marks.items() if k not in check_keys)
        total_available = sum(marks.values())
        verification = _build_verification_cell(checks, cell_errors, marks)
        feedback = _build_feedback_cell(auto_mark, manual_available, total_available)
    else:
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

    # Parse _feedback - try triple-quoted first, then single-line
    feedback = ""
    fb_match = re.search(r'_feedback\s*=\s*"""(.*?)"""', section, re.DOTALL)
    if not fb_match:
        fb_match = re.search(r"_feedback\s*=\s*'''(.*?)'''", section, re.DOTALL)
    if not fb_match:
        fb_match = re.search(r'_feedback\s*=\s*"((?:[^"\\]|\\.)*)"', section)
    if not fb_match:
        fb_match = re.search(r"_feedback\s*=\s*'((?:[^'\\]|\\.)*)'", section)
    if fb_match:
        feedback = fb_match.group(1)

    return (mark, feedback)


def write_gta_feedback(file_path: Path, mark: int | None, feedback: str) -> None:
    """Write ``_mark`` and ``_feedback`` values into a graded notebook.

    The file must contain a MOGRADER: GTA FEEDBACK marker cell.
    Always writes ``_feedback`` as a triple-quoted string.

    Raises ValueError if the feedback marker is not found.
    """
    text = file_path.read_text()
    if FEEDBACK_MARKER not in text:
        raise ValueError(f"No {FEEDBACK_MARKER} found in {file_path}")

    # Replace _mark value
    mark_str = str(mark) if mark is not None else "None"
    text = re.sub(r"_mark\s*=\s*(\d+|None)", f"_mark = {mark_str}", text)

    # Escape triple quotes in feedback
    safe_feedback = feedback.replace('"""', r"\"\"\"")

    # Replace _feedback value — try triple-quoted patterns first, then single-line
    replacement = f'_feedback = """{safe_feedback}"""'

    # Try triple-double-quoted
    new_text, count = re.subn(
        r'_feedback\s*=\s*""".*?"""', replacement, text, count=1, flags=re.DOTALL
    )
    if count == 0:
        # Try triple-single-quoted
        new_text, count = re.subn(
            r"_feedback\s*=\s*'''.*?'''", replacement, text, count=1, flags=re.DOTALL
        )
    if count == 0:
        # Try double-quoted single-line
        new_text, count = re.subn(
            r'_feedback\s*=\s*"(?:[^"\\]|\\.)*"', replacement, text, count=1
        )
    if count == 0:
        # Try single-quoted single-line
        new_text, count = re.subn(
            r"_feedback\s*=\s*'(?:[^'\\]|\\.)*'", replacement, text, count=1
        )

    file_path.write_text(new_text)
