"""Moodle CSV merging and feedback ZIP bundling."""

import csv
import math
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class MergeResult:
    """Tracks merge outcomes."""

    matched: int = 0
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)
    unmatched_grades: list[str] = field(default_factory=list)
    marks: list[int] = field(default_factory=list)


def read_moodle_worksheet(path: Path) -> tuple[list[str], list[dict]]:
    """Read a Moodle offline grading worksheet CSV (UTF-8-SIG encoded)."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def read_grades_csv(path: Path) -> dict[str, dict]:
    """Read mograder grades CSV into lookup dict keyed by student."""
    grades = {}
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            mark_str = row["mark"].strip()
            row["mark"] = int(mark_str) if mark_str else None
            grades[row["student"]] = row
    return grades


def merge_grades(
    moodle_rows: list[dict],
    grades: dict[str, dict],
    match_column: str = "Username",
) -> tuple[list[dict], MergeResult]:
    """Merge mograder grades into Moodle rows."""
    result = MergeResult()
    matched_keys = set()
    now = datetime.now().strftime("%A, %d %B %Y, %I:%M %p")

    for row in moodle_rows:
        key = row[match_column]
        if key in grades:
            matched_keys.add(key)
            mark = grades[key]["mark"]
            if mark is not None:
                row["Grade"] = str(mark)
                row["Maximum grade"] = "100"
                row["Last modified (grade)"] = now
                result.matched += 1
                result.marks.append(mark)
            else:
                result.skipped += 1
        else:
            if "Submitted" in row.get("Status", ""):
                result.warnings.append(
                    f"WARNING: {key} has 'Submitted' status but no grade"
                )
            result.skipped += 1

    # Check for grades with no Moodle row
    for key in grades:
        if key not in matched_keys:
            result.unmatched_grades.append(key)
            result.warnings.append(
                f"WARNING: grade for {key} has no matching Moodle row"
            )

    return moodle_rows, result


def write_moodle_csv(rows: list[dict], fieldnames: list[str], path: Path) -> None:
    """Write updated Moodle CSV (UTF-8, no BOM)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_feedback_zip(
    moodle_rows: list[dict],
    feedback_dir: Path,
    zip_path: Path,
    match_column: str = "Username",
) -> int:
    """Create ZIP with Moodle feedback path convention.

    Returns count of files added.
    """
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    # Build lookup: match_key → (full_name, participant_id)
    lookup = {}
    for row in moodle_rows:
        key = row[match_column]
        full_name = row["Full name"]
        # "Participant 4454589" → "4454589"
        participant_id = row["Identifier"].split()[-1]
        lookup[key] = (full_name, participant_id)

    count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for html_file in sorted(feedback_dir.glob("*.html")):
            stem = html_file.stem
            if stem in lookup:
                full_name, pid = lookup[stem]
                arc_path = f"{full_name}_{pid}_assignsubmission_file_/{html_file.name}"
                zf.write(html_file, arcname=arc_path)
                count += 1
    return count


def compute_statistics(marks: list[int]) -> str:
    """Format grade statistics: min, max, mean±stddev, distribution buckets."""
    if not marks:
        return "No grades to compute statistics."

    n = len(marks)
    mn = min(marks)
    mx = max(marks)
    mean = sum(marks) / n
    # Population stddev (N, not N-1)
    variance = sum((x - mean) ** 2 for x in marks) / n
    stddev = math.sqrt(variance)

    lines = [
        f"Min:     {mn:.1f}",
        f"Max:     {mx:.1f}",
        f"Average: {mean:.1f}+/-{stddev:.1f}",
        "",
    ]

    # Distribution buckets
    buckets = [
        ("<40", lambda x: x < 40),
        ("40-49", lambda x: 40 <= x <= 49),
        ("50-59", lambda x: 50 <= x <= 59),
        ("60-69", lambda x: 60 <= x <= 69),
        ("70-84", lambda x: 70 <= x <= 84),
        ("85+", lambda x: x >= 85),
    ]
    headers = [b[0] for b in buckets]
    counts = [sum(1 for x in marks if b[1](x)) for b in buckets]
    pcts = [round(c / n * 100) for c in counts]

    lines.append("\t".join(headers))
    lines.append("\t".join(f"{p:.0f}%" for p in pcts))
    return "\n".join(lines)
