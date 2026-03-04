"""HTML feedback export and grade aggregation."""

import csv
import subprocess
import sys
from pathlib import Path

from mograder.cells import parse_auto_marks, parse_gta_feedback


def export_feedback_html(
    notebook_path: Path,
    output_dir: Path,
    timeout: int = 300,
) -> Path:
    """Export a graded notebook to standalone HTML via ``marimo export html``.

    Returns the path to the exported HTML file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / f"{notebook_path.stem}.html"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "marimo",
            "export",
            "html",
            str(notebook_path),
            "-o",
            str(dest),
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if proc.returncode != 0 and not dest.exists():
        raise RuntimeError(f"Failed to export {notebook_path}: {proc.stderr[:500]}")

    return dest


def collect_grades(graded_notebooks: list[Path]) -> list[dict]:
    """Parse marks and feedback from graded notebooks.

    Returns a list of dicts with keys: student, mark, feedback, auto_mark.

    When per-question marks are present (``_mograder_marks`` in verification cell),
    ``auto_mark`` contains the auto-scored portion and ``mark`` is the total
    (auto + manual). When no marks metadata exists, ``auto_mark`` is None and
    ``mark`` is the raw ``_mark`` value (backward compatible).
    """
    grades = []
    for nb in graded_notebooks:
        lines = nb.read_text().splitlines(keepends=True)
        manual_mark, feedback = parse_gta_feedback(lines)
        auto_mark = parse_auto_marks(lines)

        if auto_mark is not None and manual_mark is not None:
            total_mark = auto_mark + manual_mark
        elif auto_mark is not None:
            # Auto marks present but GTA hasn't graded yet
            total_mark = None
        else:
            # No per-question marks — backward compatible
            total_mark = manual_mark

        grades.append(
            {
                "student": nb.stem,
                "mark": total_mark,
                "auto_mark": auto_mark,
                "feedback": feedback,
            }
        )
    return grades


def write_grades_csv(grades: list[dict], path: Path):
    """Write aggregated grades to CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    has_auto = any(g.get("auto_mark") is not None for g in grades)
    fieldnames = ["student", "mark", "feedback"]
    if has_auto:
        fieldnames = ["student", "mark", "auto_mark", "feedback"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(grades)
    print(f"Grades written to {path}")
