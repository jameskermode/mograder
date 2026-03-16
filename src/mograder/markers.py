"""Marker validation and solution stripping for marimo notebooks."""

import os
import re
import sys
from pathlib import Path


def _rel(p: Path) -> str:
    """Return a short relative path string for display."""
    try:
        return os.path.relpath(p)
    except ValueError:
        return str(p)


SOLUTION_BEGIN = "### BEGIN SOLUTION"
SOLUTION_END = "### END SOLUTION"
SUBMIT_MARKER = "# === MOGRADER: SUBMIT ==="

_SIMPLE_NAME_RE = re.compile(r"^[a-zA-Z_]\w*$")
_ASSIGN_RE = re.compile(r"^\s*([a-zA-Z_]\w*)\s*=")


def _extract_return_names(line: str) -> list[str]:
    """Extract simple variable names from a return statement.

    Returns names only when every component of the return expression is a
    bare identifier (e.g. ``return x`` or ``return x, y``).  Complex
    expressions like ``return x.value + 1`` yield an empty list.
    """
    m = re.match(r"^\s*return\s+(.+)$", line)
    if not m:
        return []
    expr = m.group(1).strip()
    # Single name: return result
    if _SIMPLE_NAME_RE.match(expr):
        return [expr]
    # Tuple with optional parens: return (x, y) or return x, y
    if expr.startswith("(") and expr.endswith(")"):
        expr = expr[1:-1].strip()
    if expr.endswith(","):
        expr = expr[:-1].strip()
    parts = [p.strip() for p in expr.split(",")]
    if all(_SIMPLE_NAME_RE.match(p) for p in parts):
        return parts
    return []


def _find_sentinel_vars(lines: list[str]) -> dict[int, list[str]]:
    """Identify variables needing sentinels for each solution block.

    Returns a mapping from solution-block index (0-based count of BEGIN
    SOLUTION markers) to the list of variable names that should be
    initialised as ``name = ...`` before the ``# YOUR CODE HERE``
    placeholder.

    A variable needs a sentinel when it appears in a ``return`` statement
    after the corresponding END SOLUTION but is **not** already assigned
    between the beginning of the enclosing scope and the BEGIN SOLUTION
    marker.
    """
    # First pass: locate all solution blocks
    blocks: list[tuple[int, int, str]] = []  # (begin_idx, end_idx, indent)
    stack_begin: int | None = None
    stack_indent = ""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == SOLUTION_BEGIN:
            stack_begin = i
            stack_indent = line[: len(line) - len(line.lstrip())]
        elif stripped == SOLUTION_END and stack_begin is not None:
            blocks.append((stack_begin, i, stack_indent))
            stack_begin = None

    result: dict[int, list[str]] = {}
    for block_idx, (begin, end, indent) in enumerate(blocks):
        # Scan forward from END SOLUTION to find return statements
        # Stop at next BEGIN SOLUTION, end of file, or a line at lower
        # indentation (different scope).
        return_names: list[str] = []
        for j in range(end + 1, len(lines)):
            fwd = lines[j]
            fwd_stripped = fwd.strip()
            if not fwd_stripped:
                continue
            if fwd_stripped == SOLUTION_BEGIN:
                break
            # Stop when we leave the scope (lower indentation)
            fwd_indent = fwd[: len(fwd) - len(fwd.lstrip())]
            if len(fwd_indent) < len(indent):
                break
            names = _extract_return_names(fwd)
            return_names.extend(names)
            if names or fwd_stripped.startswith("return"):
                break  # found the return, stop scanning

        if not return_names:
            continue

        # Collect names already assigned before BEGIN SOLUTION in this scope
        pre_assigned: set[str] = set()
        for j in range(begin - 1, -1, -1):
            prev = lines[j]
            prev_stripped = prev.strip()
            if not prev_stripped:
                continue
            # Stop scanning when we leave the enclosing scope
            prev_indent = prev[: len(prev) - len(prev.lstrip())]
            if prev_stripped and len(prev_indent) < len(indent):
                break
            m = _ASSIGN_RE.match(prev)
            if m:
                pre_assigned.add(m.group(1))

        orphaned = [n for n in return_names if n not in pre_assigned]
        if orphaned:
            result[block_idx] = orphaned

    return result


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

    When a ``return`` statement after END SOLUTION references simple
    variable names that are only defined inside the removed solution block,
    sentinel assignments (``name = ...``) are inserted before the
    placeholder so the return does not raise :class:`NameError`.
    """
    sentinels = _find_sentinel_vars(lines)

    output = []
    in_solution = False
    solution_indent = ""
    block_idx = -1

    for line in lines:
        stripped = line.strip()

        if stripped == SOLUTION_BEGIN:
            in_solution = True
            block_idx += 1
            solution_indent = line[: len(line) - len(line.lstrip())]
            continue

        if stripped == SOLUTION_END:
            in_solution = False
            # Insert sentinels for orphaned return variables
            for name in sentinels.get(block_idx, []):
                output.append(f"{solution_indent}{name} = ...\n")
            output.append(f"{solution_indent}# YOUR CODE HERE\n")
            output.append(f"{solution_indent}pass\n")
            continue

        if not in_solution:
            output.append(line)

    return output


def count_markers(lines: list[str]) -> int:
    """Count solution blocks."""
    return sum(1 for line in lines if line.strip() == SOLUTION_BEGIN)


def convert_markdown_cells(lines: list[str]) -> list[str]:
    """Convert stripped markdown answer cells to editable mo.md() blocks.

    After ``strip_solutions()``, markdown answer cells look like::

        _response = "placeholder text"
        # YOUR CODE HERE
        pass
        mo.md(_response)

    This function converts them to::

        mo.md(r\"\"\"
        placeholder text
        \"\"\")

    so that students see a clean editable markdown cell instead of ugly
    placeholder code.
    """
    output = []
    i = 0
    while i < len(lines):
        # Try to match the 4-line pattern
        if i + 3 < len(lines):
            line0 = lines[i]
            line1 = lines[i + 1]
            line2 = lines[i + 2]
            line3 = lines[i + 3]
            m = re.match(r'^(\s*)_response\s*=\s*["\'](.+?)["\']\s*$', line0)
            if (
                m
                and line1.strip() == "# YOUR CODE HERE"
                and line2.strip() == "pass"
                and line3.strip() == "mo.md(_response)"
            ):
                indent = m.group(1)
                placeholder = m.group(2)
                output.append(f'{indent}mo.md(r"""\n')
                output.append(f"{indent}{placeholder}\n")
                output.append(f'{indent}""")\n')
                i += 4
                continue
        output.append(lines[i])
        i += 1
    return output


def build_submit_cell(server_url: str, assignment_name: str) -> str:
    """Build a submit cell that uses ``mograder.remote.submit()``.

    Returns source text for two marimo cells (username input + submit action).
    """
    return f'''\

@app.cell(hide_code=True)
def _(mo):
    {SUBMIT_MARKER}
    submit_username = mo.ui.text(label="Username", placeholder="Enter your username")
    submit_btn = mo.ui.run_button(label="Submit")
    mo.hstack([submit_username, submit_btn])
    return (submit_btn, submit_username)


@app.cell(hide_code=True)
def _(submit_btn, submit_username, mo):
    mo.stop(not submit_btn.value or not submit_username.value)
    from mograder.remote import submit as submit_fn
    submit_result = submit_fn("{server_url}", "{assignment_name}", __file__, submit_username.value)
    mo.callout(mo.md(f"**Submitted!** Status: {{submit_result}}"), kind="success")
    return


'''


def _inject_before_main(lines: list[str], cell_text: str) -> list[str]:
    """Insert *cell_text* before the ``if __name__`` guard."""
    insert_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("if __name__"):
            insert_idx = i
            break
    if insert_idx is None:
        insert_idx = len(lines)
    return lines[:insert_idx] + cell_text.splitlines(keepends=True) + lines[insert_idx:]


def process_file(
    source: Path,
    output_dir: Path | None,
    dry_run: bool = False,
    validate_only: bool = False,
    submit_url: str | None = None,
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
    student_lines = convert_markdown_cells(student_lines)

    if submit_url:
        assignment_name = source.parent.name
        submit_cell = build_submit_cell(submit_url, assignment_name)
        student_lines = _inject_before_main(student_lines, submit_cell)

    if dry_run:
        n_removed = len(lines) - len(student_lines)
        print(
            f"DRY-RUN: {_rel(source)} → "
            f"{n_solutions} solution blocks stripped, "
            f"{n_removed} lines removed"
        )
        return True

    if output_dir is None:
        output_dir = Path("release")
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / source.name
    dest.write_text("".join(student_lines))
    print(f"OK: {_rel(source)} → {_rel(dest)} ({n_solutions} solution blocks stripped)")
    return True
