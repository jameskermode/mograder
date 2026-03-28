"""Moodle CSV merging and feedback ZIP bundling."""

import csv
import math
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


def markdown_to_plaintext(text: str) -> str:
    """Strip markdown formatting from text, producing clean plain text."""
    if not text:
        return text
    from markdown_it import MarkdownIt

    md = MarkdownIt()
    tokens = md.parse(text)
    parts: list[str] = []
    in_list = 0
    for token in tokens:
        if token.children:
            for child in token.children:
                if child.type in ("text", "code_inline"):
                    parts.append(child.content)
                elif child.type == "softbreak":
                    parts.append("\n")
        elif token.type in ("text", "code_block", "fence"):
            parts.append(token.content)
        # Track list nesting to avoid double newlines
        if token.tag in ("ul", "ol"):
            in_list += token.nesting  # +1 open, -1 close
        # Add newline after block-level closing tags (skip <p> inside lists)
        if token.nesting == -1:
            if token.tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                parts.append("\n")
            elif token.tag == "li":
                parts.append("\n")
            elif token.tag == "p" and not in_list:
                parts.append("\n")
    return "".join(parts).strip()


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
            # Prefer penalised_mark if available
            mark = grades[key].get("penalised_mark") or grades[key]["mark"]
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


@dataclass
class ExtractResult:
    """Tracks submission extraction outcomes."""

    extracted: int = 0
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)


def extract_submissions(
    zip_path: Path,
    csv_path: Path,
    output_dir: Path,
    match_column: str = "Username",
) -> ExtractResult:
    """Extract Moodle submission ZIP into output_dir/<username>.py.

    Moodle ZIP entries have paths like:
        Full Name_participantid_assignsubmission_file_/original.py

    Uses the CSV to map participant_id → username (match_column value).
    """
    _, rows = read_moodle_worksheet(csv_path)

    # Build {participant_id: username} from Identifier column + match_column
    pid_to_username: dict[str, str] = {}
    for row in rows:
        identifier = row.get("Identifier", "")
        # "Participant 4454589" → "4454589"
        parts = identifier.split()
        if len(parts) >= 2:
            pid_to_username[parts[-1]] = row[match_column]

    result = ExtractResult()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Group .py entries by participant_id
    pid_pattern = re.compile(r"_(\d+)_assignsubmission_file_/")
    py_entries: dict[str, list[str]] = {}  # pid → [entry names]

    with zipfile.ZipFile(zip_path) as zf:
        for entry in zf.namelist():
            if not entry.endswith(".py"):
                continue
            m = pid_pattern.search(entry)
            if not m:
                continue
            pid = m.group(1)
            py_entries.setdefault(pid, []).append(entry)

        for pid, entries in py_entries.items():
            if pid not in pid_to_username:
                result.warnings.append(
                    f"⚠️ participant {pid} not found in CSV — skipped"
                )
                result.skipped += 1
                continue
            username = pid_to_username[pid]
            if len(entries) > 1:
                result.warnings.append(
                    f"⚠️ {username} has {len(entries)} .py files — skipped"
                )
                result.skipped += 1
                continue
            data = zf.read(entries[0])
            (output_dir / f"{username}.py").write_bytes(data)
            result.extracted += 1

    return result


def build_feedback_zip(
    moodle_rows: list[dict],
    feedback_dir: Path,
    zip_path: Path,
    match_column: str = "Username",
    name_column: str = "Full name",
) -> int:
    """Create ZIP with Moodle feedback path convention.

    Returns count of files added.
    """
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    # Build lookup: match_key → (full_name, participant_id)
    lookup = {}
    for row in moodle_rows:
        key = row[match_column]
        full_name = row[name_column]
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


def grades_from_gradebook(db_path: "Path") -> dict[str, dict]:
    """Read grades from a gradebook DB, merging all assignments.

    Returns same format as ``read_grades_csv()``: ``{student: {mark, feedback, ...}}``.
    """
    from mograder.grading.gradebook import Gradebook

    grades: dict[str, dict] = {}
    with Gradebook(db_path) as gb:
        # Get all assignments
        rows = gb._conn.execute("SELECT name FROM assignments").fetchall()
        for row in rows:
            for g in gb.collect_grades(row["name"]):
                student = g["student"]
                if student not in grades:
                    grades[student] = {"student": student, "mark": None, "feedback": ""}
                # Sum marks across assignments
                if g["mark"] is not None:
                    if grades[student]["mark"] is None:
                        grades[student]["mark"] = g["mark"]
                    else:
                        grades[student]["mark"] += g["mark"]
                # Carry through penalised_mark if present
                if g.get("penalised_mark") is not None:
                    if grades[student].get("penalised_mark") is None:
                        grades[student]["penalised_mark"] = g["penalised_mark"]
                    else:
                        grades[student]["penalised_mark"] += g["penalised_mark"]
                if g["feedback"]:
                    if grades[student]["feedback"]:
                        grades[student]["feedback"] += "\n" + g["feedback"]
                    else:
                        grades[student]["feedback"] = g["feedback"]
    return grades


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
