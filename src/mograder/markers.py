"""Marker validation and solution stripping for marimo notebooks."""

import re
import sys
from pathlib import Path

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
    student_lines = convert_markdown_cells(student_lines)

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
