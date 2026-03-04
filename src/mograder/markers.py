"""Marker validation and solution stripping for marimo notebooks."""

import sys
from pathlib import Path

SOLUTION_BEGIN = "### BEGIN SOLUTION"
SOLUTION_END = "### END SOLUTION"
HIDDEN_BEGIN = "### BEGIN HIDDEN TESTS"
HIDDEN_END = "### END HIDDEN TESTS"


def validate_markers(lines: list[str], filepath: str) -> list[str]:
    """Check that all solution/hidden-test markers are properly paired.

    Returns a list of error messages (empty if valid).
    """
    errors = []
    in_solution = False
    in_hidden = False
    sol_start_line = 0
    hidden_start_line = 0

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

        elif stripped == HIDDEN_BEGIN:
            if in_hidden:
                errors.append(
                    f"{filepath}:{i}: nested {HIDDEN_BEGIN} "
                    f"(previous opened at line {hidden_start_line})"
                )
            in_hidden = True
            hidden_start_line = i

        elif stripped == HIDDEN_END:
            if not in_hidden:
                errors.append(
                    f"{filepath}:{i}: {HIDDEN_END} without matching {HIDDEN_BEGIN}"
                )
            in_hidden = False

    if in_solution:
        errors.append(f"{filepath}:{sol_start_line}: unclosed {SOLUTION_BEGIN}")
    if in_hidden:
        errors.append(f"{filepath}:{hidden_start_line}: unclosed {HIDDEN_BEGIN}")

    return errors


def strip_solutions(lines: list[str]) -> list[str]:
    """Remove solution blocks and hidden tests from source lines.

    - Lines between BEGIN SOLUTION / END SOLUTION are replaced with
      ``# YOUR CODE HERE`` and ``pass`` at the correct indentation.
    - Lines between BEGIN HIDDEN TESTS / END HIDDEN TESTS are removed
      entirely (including the markers).
    """
    output = []
    in_solution = False
    in_hidden = False
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

        if stripped == HIDDEN_BEGIN:
            in_hidden = True
            continue

        if stripped == HIDDEN_END:
            in_hidden = False
            continue

        if not in_solution and not in_hidden:
            output.append(line)

    return output


def count_markers(lines: list[str]) -> dict[str, int]:
    """Count solution and hidden-test blocks."""
    counts = {"solution": 0, "hidden": 0}
    for line in lines:
        stripped = line.strip()
        if stripped == SOLUTION_BEGIN:
            counts["solution"] += 1
        elif stripped == HIDDEN_BEGIN:
            counts["hidden"] += 1
    return counts


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

    counts = count_markers(lines)
    if counts["solution"] == 0 and counts["hidden"] == 0:
        print(f"SKIP: {source} (no solution or hidden-test markers found)")
        return True

    if validate_only:
        print(
            f"VALID: {source} "
            f"({counts['solution']} solution blocks, "
            f"{counts['hidden']} hidden-test blocks)"
        )
        return True

    student_lines = strip_solutions(lines)

    if dry_run:
        n_removed = len(lines) - len(student_lines)
        print(
            f"DRY-RUN: {source} → "
            f"{counts['solution']} solution blocks stripped, "
            f"{counts['hidden']} hidden-test blocks stripped, "
            f"{n_removed} lines removed"
        )
        return True

    if output_dir is None:
        output_dir = Path("release")
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / source.name
    dest.write_text("".join(student_lines))
    print(
        f"OK: {source} → {dest} "
        f"({counts['solution']} solutions, {counts['hidden']} hidden tests stripped)"
    )
    return True
