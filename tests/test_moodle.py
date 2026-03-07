"""Tests for mograder.moodle — Moodle CSV merging and feedback ZIP."""

import csv
import zipfile
from pathlib import Path

from click.testing import CliRunner

from mograder.cli import cli
from mograder.moodle import (
    build_feedback_zip,
    compute_statistics,
    extract_submissions,
    merge_grades,
    read_grades_csv,
    read_moodle_worksheet,
    write_moodle_csv,
)

MOODLE_FIELDS = [
    "Identifier",
    "Full name",
    "Email address",
    "Status",
    "Grade",
    "Maximum grade",
    "Grade can be changed",
    "Last modified (submission)",
    "Last modified (grade)",
    "Feedback comments",
    "Username",
    "ID number",
]


def _make_moodle_csv(path: Path, rows: list[dict]) -> Path:
    """Write a Moodle-style CSV with BOM."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MOODLE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _make_grades_csv(path: Path, rows: list[dict]) -> Path:
    """Write a mograder grades CSV."""
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["student", "mark", "feedback"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def _moodle_row(
    username="u1234567",
    full_name="Alice Example",
    identifier="Participant 9900001",
    status="Submitted",
    grade="",
    id_number="1234567",
):
    return {
        "Identifier": identifier,
        "Full name": full_name,
        "Email address": f"{username}@university.ac.uk",
        "Status": status,
        "Grade": grade,
        "Maximum grade": "100",
        "Grade can be changed": "Yes",
        "Last modified (submission)": "Monday, 01 January 2024, 12:00 PM",
        "Last modified (grade)": "",
        "Feedback comments": "",
        "Username": username,
        "ID number": id_number,
    }


# --- read_moodle_worksheet ---


def test_read_moodle_worksheet(tmp_path):
    csv_path = _make_moodle_csv(
        tmp_path / "worksheet.csv",
        [_moodle_row()],
    )
    fieldnames, rows = read_moodle_worksheet(csv_path)
    assert fieldnames == MOODLE_FIELDS
    assert len(rows) == 1
    assert rows[0]["Username"] == "u1234567"


def test_read_moodle_worksheet_bom_stripped(tmp_path):
    """BOM should not appear in fieldnames."""
    csv_path = _make_moodle_csv(tmp_path / "bom.csv", [_moodle_row()])
    fieldnames, _ = read_moodle_worksheet(csv_path)
    assert not fieldnames[0].startswith("\ufeff")
    assert fieldnames[0] == "Identifier"


# --- read_grades_csv ---


def test_read_grades_csv(tmp_path):
    csv_path = _make_grades_csv(
        tmp_path / "grades.csv",
        [
            {"student": "u1234567", "mark": "85", "feedback": "Good work"},
            {"student": "u7654321", "mark": "", "feedback": ""},
        ],
    )
    grades = read_grades_csv(csv_path)
    assert grades["u1234567"]["mark"] == 85
    assert grades["u7654321"]["mark"] is None


# --- merge_grades ---


def test_merge_grades_basic(tmp_path):
    moodle_rows = [
        _moodle_row(username="u1234567", full_name="Alice Example"),
        _moodle_row(
            username="u7654321",
            full_name="Bob Sample",
            identifier="Participant 9900002",
            id_number="7654321",
        ),
    ]
    grades = {
        "u1234567": {"student": "u1234567", "mark": 85, "feedback": "Good"},
        "u7654321": {"student": "u7654321", "mark": 42, "feedback": "Needs work"},
    }
    updated, result = merge_grades(moodle_rows, grades)
    assert result.matched == 2
    assert updated[0]["Grade"] == "85"
    assert updated[1]["Grade"] == "42"
    assert updated[0]["Maximum grade"] == "100"
    # Timestamp should be set
    assert updated[0]["Last modified (grade)"] != ""


def test_merge_grades_warns_submitted_no_grade():
    moodle_rows = [_moodle_row(username="u1234567", status="Submitted")]
    grades = {}  # No grade for this student
    _, result = merge_grades(moodle_rows, grades)
    assert result.skipped == 1
    assert any("u1234567" in w for w in result.warnings)


def test_merge_grades_warns_unmatched_grade():
    moodle_rows = [_moodle_row(username="u1234567")]
    grades = {
        "u1234567": {"student": "u1234567", "mark": 85, "feedback": ""},
        "u9999999": {"student": "u9999999", "mark": 50, "feedback": ""},
    }
    _, result = merge_grades(moodle_rows, grades)
    assert "u9999999" in result.unmatched_grades


def test_merge_grades_custom_match_column():
    moodle_rows = [_moodle_row(username="u1234567", id_number="1234567")]
    grades = {"1234567": {"student": "1234567", "mark": 70, "feedback": ""}}
    updated, result = merge_grades(moodle_rows, grades, match_column="ID number")
    assert result.matched == 1
    assert updated[0]["Grade"] == "70"


def test_merge_grades_skips_none_marks():
    moodle_rows = [_moodle_row(username="u1234567")]
    grades = {"u1234567": {"student": "u1234567", "mark": None, "feedback": ""}}
    updated, result = merge_grades(moodle_rows, grades)
    assert result.matched == 0
    assert result.skipped == 1
    # Grade should remain unchanged
    assert updated[0]["Grade"] == ""


# --- write_moodle_csv ---


def test_write_moodle_csv_preserves_columns(tmp_path):
    rows = [_moodle_row()]
    out = tmp_path / "out.csv"
    write_moodle_csv(rows, MOODLE_FIELDS, out)

    with open(out, newline="") as f:
        reader = csv.DictReader(f)
        assert list(reader.fieldnames) == MOODLE_FIELDS
        result_rows = list(reader)
    assert len(result_rows) == 1
    assert result_rows[0]["Username"] == "u1234567"


# --- build_feedback_zip ---


def test_build_feedback_zip(tmp_path):
    feedback_dir = tmp_path / "feedback"
    feedback_dir.mkdir()
    (feedback_dir / "u1234567.html").write_text("<html>feedback</html>")

    moodle_rows = [
        _moodle_row(
            username="u1234567",
            full_name="Alice Example",
            identifier="Participant 9900001",
        )
    ]
    zip_path = tmp_path / "feedback.zip"
    count = build_feedback_zip(moodle_rows, feedback_dir, zip_path)
    assert count == 1

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert len(names) == 1
        assert names[0] == "Alice Example_9900001_assignsubmission_file_/u1234567.html"


def test_build_feedback_zip_skips_unmatched(tmp_path):
    feedback_dir = tmp_path / "feedback"
    feedback_dir.mkdir()
    (feedback_dir / "u9999999.html").write_text("<html>orphan</html>")

    moodle_rows = [_moodle_row(username="u1234567")]
    zip_path = tmp_path / "feedback.zip"
    count = build_feedback_zip(moodle_rows, feedback_dir, zip_path)
    assert count == 0

    with zipfile.ZipFile(zip_path) as zf:
        assert len(zf.namelist()) == 0


def test_build_feedback_zip_custom_match_column(tmp_path):
    feedback_dir = tmp_path / "feedback"
    feedback_dir.mkdir()
    (feedback_dir / "1234567.html").write_text("<html>feedback</html>")

    moodle_rows = [
        _moodle_row(
            username="u1234567",
            full_name="Alice Example",
            identifier="Participant 9900001",
            id_number="1234567",
        )
    ]
    zip_path = tmp_path / "feedback.zip"
    count = build_feedback_zip(
        moodle_rows, feedback_dir, zip_path, match_column="ID number"
    )
    assert count == 1

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert names[0] == "Alice Example_9900001_assignsubmission_file_/1234567.html"


def test_build_feedback_zip_custom_name_column(tmp_path):
    """name_column overrides which column is used for the folder name."""
    feedback_dir = tmp_path / "feedback"
    feedback_dir.mkdir()
    (feedback_dir / "u1234567.html").write_text("<html>feedback</html>")

    moodle_rows = [
        {
            **_moodle_row(
                username="u1234567",
                full_name="Alice Example",
                identifier="Participant 9900001",
            ),
            "Display name": "Alice E.",
        }
    ]
    zip_path = tmp_path / "feedback.zip"
    count = build_feedback_zip(
        moodle_rows, feedback_dir, zip_path, name_column="Display name"
    )
    assert count == 1

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert "Alice E._9900001_assignsubmission_file_/u1234567.html" in names


# --- compute_statistics ---


def test_compute_statistics():
    marks = [30, 45, 55, 65, 75, 90]
    stats = compute_statistics(marks)
    assert "Min:" in stats
    assert "Max:" in stats
    assert "Average:" in stats
    assert "<40" in stats
    assert "85+" in stats


def test_compute_statistics_empty():
    stats = compute_statistics([])
    assert "No grades" in stats


# --- CLI integration ---


def test_moodle_cli_full_roundtrip(tmp_path):
    worksheet = _make_moodle_csv(
        tmp_path / "worksheet.csv",
        [
            _moodle_row(username="u1234567", full_name="Alice Example"),
            _moodle_row(
                username="u7654321",
                full_name="Bob Sample",
                identifier="Participant 9900002",
                id_number="7654321",
            ),
        ],
    )
    grades = _make_grades_csv(
        tmp_path / "grades.csv",
        [
            {"student": "u1234567", "mark": "85", "feedback": "Good"},
            {"student": "u7654321", "mark": "42", "feedback": "Needs work"},
        ],
    )
    feedback_dir = tmp_path / "feedback"
    feedback_dir.mkdir()
    (feedback_dir / "u1234567.html").write_text("<html>alice</html>")
    (feedback_dir / "u7654321.html").write_text("<html>bob</html>")

    out_dir = tmp_path / "export"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "moodle",
            "export",
            str(worksheet),
            "--grades-csv",
            str(grades),
            "--feedback-dir",
            str(feedback_dir),
            "-o",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Matched: 2" in result.output
    assert (out_dir / "worksheet.csv").exists()

    # Check ZIP was created
    zip_files = list(out_dir.glob("feedback_*.zip"))
    assert len(zip_files) == 1


def test_moodle_cli_no_feedback(tmp_path):
    worksheet = _make_moodle_csv(
        tmp_path / "worksheet.csv",
        [_moodle_row(username="u1234567")],
    )
    grades = _make_grades_csv(
        tmp_path / "grades.csv",
        [{"student": "u1234567", "mark": "85", "feedback": "Good"}],
    )
    out_dir = tmp_path / "export"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "moodle",
            "export",
            str(worksheet),
            "--grades-csv",
            str(grades),
            "-o",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (out_dir / "worksheet.csv").exists()
    # No ZIP should be created
    assert not list(out_dir.glob("*.zip"))


def _make_submission_zip(path: Path, entries: dict[str, str]) -> Path:
    """Create a ZIP with given {arc_path: content} entries."""
    with zipfile.ZipFile(path, "w") as zf:
        for arc, content in entries.items():
            zf.writestr(arc, content)
    return path


# --- extract_submissions ---


def test_extract_submissions_basic(tmp_path):
    """One .py per student extracts correctly."""
    csv_path = _make_moodle_csv(
        tmp_path / "worksheet.csv",
        [
            _moodle_row(
                username="u1234567",
                full_name="Alice Example",
                identifier="Participant 9900001",
            ),
            _moodle_row(
                username="u7654321",
                full_name="Bob Sample",
                identifier="Participant 9900002",
                id_number="7654321",
            ),
        ],
    )
    zip_path = _make_submission_zip(
        tmp_path / "submissions.zip",
        {
            "Alice Example_9900001_assignsubmission_file_/hw1.py": "print('alice')",
            "Bob Sample_9900002_assignsubmission_file_/hw1.py": "print('bob')",
        },
    )
    out = tmp_path / "submitted"
    result = extract_submissions(zip_path, csv_path, out)
    assert result.extracted == 2
    assert result.skipped == 0
    assert not result.warnings
    assert (out / "u1234567.py").read_text() == "print('alice')"
    assert (out / "u7654321.py").read_text() == "print('bob')"


def test_extract_submissions_multiple_py_skipped(tmp_path):
    """Multiple .py files for one student → warning, skipped."""
    csv_path = _make_moodle_csv(
        tmp_path / "worksheet.csv",
        [_moodle_row(username="u1234567", identifier="Participant 9900001")],
    )
    zip_path = _make_submission_zip(
        tmp_path / "submissions.zip",
        {
            "Alice_9900001_assignsubmission_file_/hw1.py": "a",
            "Alice_9900001_assignsubmission_file_/hw2.py": "b",
        },
    )
    out = tmp_path / "submitted"
    result = extract_submissions(zip_path, csv_path, out)
    assert result.extracted == 0
    assert result.skipped == 1
    assert any("2 .py files" in w for w in result.warnings)


def test_extract_submissions_missing_pid_in_csv(tmp_path):
    """Participant ID in ZIP but not in CSV → warning, skipped."""
    csv_path = _make_moodle_csv(
        tmp_path / "worksheet.csv",
        [_moodle_row(username="u1234567", identifier="Participant 9900001")],
    )
    zip_path = _make_submission_zip(
        tmp_path / "submissions.zip",
        {"Unknown_9999999_assignsubmission_file_/hw1.py": "x"},
    )
    out = tmp_path / "submitted"
    result = extract_submissions(zip_path, csv_path, out)
    assert result.extracted == 0
    assert result.skipped == 1
    assert any("9999999" in w for w in result.warnings)


def test_extract_submissions_ignores_non_py(tmp_path):
    """Non-.py files in ZIP are ignored."""
    csv_path = _make_moodle_csv(
        tmp_path / "worksheet.csv",
        [_moodle_row(username="u1234567", identifier="Participant 9900001")],
    )
    zip_path = _make_submission_zip(
        tmp_path / "submissions.zip",
        {
            "Alice_9900001_assignsubmission_file_/notes.txt": "text",
            "Alice_9900001_assignsubmission_file_/hw1.py": "code",
        },
    )
    out = tmp_path / "submitted"
    result = extract_submissions(zip_path, csv_path, out)
    assert result.extracted == 1
    assert (out / "u1234567.py").read_text() == "code"


def test_moodle_cli_bad_match_column(tmp_path):
    worksheet = _make_moodle_csv(
        tmp_path / "worksheet.csv",
        [_moodle_row()],
    )
    grades = _make_grades_csv(
        tmp_path / "grades.csv",
        [{"student": "u1234567", "mark": "85", "feedback": ""}],
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "moodle",
            "export",
            str(worksheet),
            "--grades-csv",
            str(grades),
            "--match-column",
            "Nonexistent Column",
        ],
    )
    assert result.exit_code != 0
    assert (
        "not found" in result.output.lower()
        or "not found" in (result.output + str(result.exception)).lower()
    )
