"""Marker validation and solution stripping for marimo notebooks."""

import re
import sys
from pathlib import Path

from mograder.cells import MARKS_MARKER

SOLUTION_BEGIN = "### BEGIN SOLUTION"
SOLUTION_END = "### END SOLUTION"


def validate_markers(lines: list[str], filepath: str) -> list[str]:
    """Check that all solution markers are properly paired.

    Returns a list of error messages (empty if valid).
    """
    errors = []
    in_solution = False
    sol_start_line = 0

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        if stripped == SOLUTION_BEGIN:
            if in_solution:
                errors.append(
                    f"{filepath}:{i}: nested {SOLUTION_BEGIN} "
                    f"(previous opened at line {sol_start_line})"
                )
            in_solution = True
            sol_start_line = i

        elif stripped == SOLUTION_END:
            if not in_solution:
                errors.append(
                    f"{filepath}:{i}: {SOLUTION_END} without matching {SOLUTION_BEGIN}"
                )
            in_solution = False

    if in_solution:
        errors.append(f"{filepath}:{sol_start_line}: unclosed {SOLUTION_BEGIN}")

    return errors


def strip_solutions(lines: list[str]) -> list[str]:
    """Remove solution blocks from source lines.

    Lines between BEGIN SOLUTION / END SOLUTION are replaced with
    ``# YOUR CODE HERE`` and ``pass`` at the correct indentation.
    The ``pass`` ensures empty function bodies remain syntactically valid.
    """
    output = []
    in_solution = False
    solution_indent = ""

    for line in lines:
        stripped = line.strip()

        if stripped == SOLUTION_BEGIN:
            in_solution = True
            solution_indent = line[: len(line) - len(line.lstrip())]
            continue

        if stripped == SOLUTION_END:
            in_solution = False
            output.append(f"{solution_indent}# YOUR CODE HERE\n")
            output.append(f"{solution_indent}pass\n")
            continue

        if not in_solution:
            output.append(line)

    return output


def count_markers(lines: list[str]) -> int:
    """Count solution blocks."""
    return sum(1 for line in lines if line.strip() == SOLUTION_BEGIN)


def has_marks_cell(lines: list[str]) -> bool:
    """Check if the source contains a marks cell."""
    return any(MARKS_MARKER in line for line in lines)


def inject_state_cell(lines: list[str]) -> list[str]:
    """Insert a ``mo.state({})`` cell before the check function cell.

    Finds the cell containing ``def check(label`` and inserts a new cell
    that creates ``_check_state, _set_check = mo.state({})``.

    Returns lines unchanged if no check function cell found.
    """
    # Find the @app.cell decorator for the check function cell
    check_cell_idx = None
    for i, line in enumerate(lines):
        if re.search(r"def check\(label", line):
            # Walk back to find the @app.cell decorator
            for j in range(i - 1, -1, -1):
                if lines[j].strip().startswith("@app.cell"):
                    check_cell_idx = j
                    break
            break

    if check_cell_idx is None:
        return lines

    state_cell = [
        "\n",
        "@app.cell(hide_code=True)\n",
        "def _(mo):\n",
        "    _check_state, _set_check = mo.state({})\n",
        "    return _check_state, _set_check\n",
        "\n",
        "\n",
    ]
    return lines[:check_cell_idx] + state_cell + lines[check_cell_idx:]


def augment_check_function(lines: list[str]) -> list[str]:
    """Add result tracking to the ``check()`` function.

    Finds the cell containing ``def check(label`` and:
    1. Adds ``_set_check`` to the cell's ``def _(...)`` parameter list
    2. Inserts tracking lines at the start of the function body

    Returns lines unchanged if no check function cell found.
    """
    # Find the def check(label line
    check_def_idx = None
    for i, line in enumerate(lines):
        if re.search(r"def check\(label", line):
            check_def_idx = i
            break

    if check_def_idx is None:
        return lines

    output = list(lines)

    # Find the cell's def _(…) line above check_def_idx
    for j in range(check_def_idx - 1, -1, -1):
        if re.match(r"^def _\(", output[j]):
            # Add _set_check to parameters
            output[j] = output[j].replace("):", ", _set_check):")
            break

    # Find the function body start (line after def check(...):)
    # We need to find the end of the def check signature
    body_idx = check_def_idx + 1
    # Skip any continuation lines of the def signature
    while (
        body_idx < len(output)
        and not output[body_idx].startswith("    ")
        and not output[body_idx].strip()
    ):
        body_idx += 1

    # Find the first line of the function body (indented deeper than def check)
    # The def check is at 4 spaces indent, body is at 8 spaces
    for k in range(check_def_idx + 1, len(output)):
        stripped = output[k].strip()
        if (
            stripped
            and not stripped.startswith('"""')
            and not stripped.startswith("'''")
        ):
            # This might be the docstring start, skip it
            if stripped.startswith('"""') or stripped.startswith("'''"):
                # Find end of docstring
                continue
            body_idx = k
            break

    # Actually, let's find the first real statement in the function body
    # Skip the def line, then skip docstring if present
    k = check_def_idx + 1
    in_docstring = False
    while k < len(output):
        stripped = output[k].strip()
        if not in_docstring and (
            stripped.startswith('"""') or stripped.startswith("'''")
        ):
            quote = stripped[:3]
            if stripped.count(quote) >= 2:
                # Single-line docstring
                k += 1
                continue
            in_docstring = True
            k += 1
            continue
        if in_docstring:
            if '"""' in stripped or "'''" in stripped:
                in_docstring = False
            k += 1
            continue
        if stripped:
            body_idx = k
            break
        k += 1

    # Get the indentation of the body
    indent = output[body_idx][: len(output[body_idx]) - len(output[body_idx].lstrip())]

    tracking_lines = [
        f'{indent}_key = label.split(":")[0].strip()\n',
        f"{indent}_passed = bool(checks) and all(ok for ok, _ in checks)\n",
        f"{indent}_set_check(lambda prev: {{**prev, _key: _passed}})\n",
    ]

    output = output[:body_idx] + tracking_lines + output[body_idx:]

    # Update the return statement to include _set_check isn't needed since
    # _set_check is a parameter, not a local. But we need to ensure
    # the return includes check. Check current return.
    return output


def transform_marks_cell(lines: list[str]) -> list[str]:
    """Transform the marks cell for student view with reactive score display.

    Detects the marks cell by MARKS_MARKER, adds ``_check_state`` to the
    cell's parameter list, and replaces the display section with a reactive
    score table.

    Returns lines unchanged if no marks cell found.
    """
    # Find the MARKS_MARKER line
    marker_idx = None
    for i, line in enumerate(lines):
        if MARKS_MARKER in line:
            marker_idx = i
            break

    if marker_idx is None:
        return lines

    output = list(lines)

    # Find the cell's def _(…) line above marker_idx
    cell_def_idx = None
    for j in range(marker_idx - 1, -1, -1):
        if re.match(r"^def _\(", output[j]):
            cell_def_idx = j
            break

    if cell_def_idx is None:
        return lines

    # Add _check_state to parameters
    output[cell_def_idx] = output[cell_def_idx].replace("):", ", _check_state):")

    # Find the "# --- display" line
    display_idx = None
    for i in range(marker_idx, len(output)):
        if "# --- display" in output[i]:
            display_idx = i
            break

    if display_idx is None:
        return output

    # Find the end of this cell (next @app.cell or if __name__ or end of file)
    # Also look for the return statement
    cell_end_idx = len(output)
    for i in range(display_idx + 1, len(output)):
        stripped = output[i].strip()
        if stripped.startswith("@app.cell") or stripped.startswith("if __name__"):
            cell_end_idx = i
            break
        # Check for blank line followed by non-indented content (cell boundary)
        if stripped == "" and i + 1 < len(output):
            next_stripped = output[i + 1].strip()
            if next_stripped.startswith("@app.cell") or next_stripped.startswith(
                "if __name__"
            ):
                cell_end_idx = i
                break

    # Find the return line within the cell
    return_idx = cell_end_idx
    for i in range(display_idx + 1, cell_end_idx):
        if output[i].strip().startswith("return"):
            return_idx = i
            break

    # Replace from display line to return line (inclusive) with reactive display
    reactive_display = [
        "    # --- display (do not edit below) ---\n",
        "    _results = _check_state()\n",
        "    _auto = sum(v for k, v in _marks.items() if _results.get(k))\n",
        "    _total = sum(_marks.values())\n",
        '    _rows = ""\n',
        "    for _q, _pts in _marks.items():\n",
        "        _got = _pts if _results.get(_q) else 0\n",
        '        _icon = "PASS" if _results.get(_q) else ("FAIL" if _q in _results else "\u2014")\n',
        '        _rows += f"| {_q} | {_icon} | {_got}/{_pts} |\\n"\n',
        '    _rows += f"| **Total** | | **{_auto}/{_total}** |\\n"\n',
        "    mo.callout(mo.md(\n",
        '        f"## Your Score\\n\\n"\n',
        '        f"| Question | Status | Marks |\\n|----------|--------|-------|\\n{_rows}"),\n',
        '        kind="success" if _auto == _total else "neutral")\n',
        "    return (_marks,)\n",
    ]

    output = output[:display_idx] + reactive_display + output[return_idx + 1 :]
    return output


def process_file(
    source: Path,
    output_dir: Path | None,
    dry_run: bool = False,
    validate_only: bool = False,
) -> bool:
    """Process a single notebook file. Returns True on success."""
    lines = source.read_text().splitlines(keepends=True)

    errors = validate_markers(lines, str(source))
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return False

    n_solutions = count_markers(lines)
    if n_solutions == 0:
        print(f"SKIP: {source} (no solution markers found)")
        return True

    if validate_only:
        print(f"VALID: {source} ({n_solutions} solution blocks)")
        return True

    student_lines = strip_solutions(lines)

    if has_marks_cell(student_lines):
        student_lines = inject_state_cell(student_lines)
        student_lines = augment_check_function(student_lines)
        student_lines = transform_marks_cell(student_lines)

    if dry_run:
        n_removed = len(lines) - len(student_lines)
        print(
            f"DRY-RUN: {source} → "
            f"{n_solutions} solution blocks stripped, "
            f"{n_removed} lines removed"
        )
        return True

    if output_dir is None:
        output_dir = Path("release")
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / source.name
    dest.write_text("".join(student_lines))
    print(f"OK: {source} → {dest} ({n_solutions} solution blocks stripped)")
    return True
