"""HTML feedback export and grade aggregation."""

import csv
import subprocess
import sys
from pathlib import Path

from mograder.cells import parse_gta_feedback


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

    Returns a list of dicts with keys: student, mark, feedback.
    """
    grades = []
    for nb in graded_notebooks:
        lines = nb.read_text().splitlines(keepends=True)
        mark, feedback = parse_gta_feedback(lines)
        grades.append(
            {
                "student": nb.stem,
                "mark": mark,
                "feedback": feedback,
            }
        )
    return grades


def write_grades_csv(grades: list[dict], path: Path):
    """Write aggregated grades to CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["student", "mark", "feedback"])
        writer.writeheader()
        writer.writerows(grades)
    print(f"Grades written to {path}")
