import csv
from pathlib import Path
from unittest.mock import MagicMock, patch

from mograder.cells import inject_grading_cells
from mograder.feedback import collect_grades, export_feedback_html, write_grades_csv
from mograder.models import CheckResult


def _make_graded_notebook(mark, feedback_text):
    """Create graded notebook source text."""
    lines = [
        "import marimo\n",
        "app = marimo.App()\n",
        "\n",
        "@app.cell\n",
        "def _():\n",
        "    x = 1\n",
        "    return\n",
        "\n",
        "\n",
        'if __name__ == "__main__":\n',
        "    app.run()\n",
    ]
    checks = [CheckResult("Q1: Foo", "success")]
    injected = inject_grading_cells(lines, checks)
    text = "".join(injected)
    if mark is not None:
        text = text.replace("_mark = None", f"_mark = {mark}")
    if feedback_text:
        text = text.replace('_feedback = ""', f'_feedback = "{feedback_text}"')
    return text


def test_export_feedback_html(tmp_path):
    nb = tmp_path / "student.py"
    nb.write_text("# notebook")
    out_dir = tmp_path / "feedback"

    def mock_run(cmd, **kwargs):
        dest = Path(cmd[cmd.index("-o") + 1])
        dest.write_text("<html>exported</html>")
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        return result

    with patch("mograder.feedback.subprocess.run", side_effect=mock_run):
        html_path = export_feedback_html(nb, out_dir)

    assert html_path.exists()
    assert html_path.name == "student.html"


def test_export_feedback_html_failure(tmp_path):
    nb = tmp_path / "bad.py"
    nb.write_text("# bad")
    out_dir = tmp_path / "feedback"

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 1
        result.stderr = "error occurred"
        return result

    import pytest
    with patch("mograder.feedback.subprocess.run", side_effect=mock_run):
        with pytest.raises(RuntimeError, match="Failed to export"):
            export_feedback_html(nb, out_dir)


def test_collect_grades(tmp_path):
    # Create two graded notebooks
    nb1 = tmp_path / "alice.py"
    nb1.write_text(_make_graded_notebook(72, "Excellent work"))
    nb2 = tmp_path / "bob.py"
    nb2.write_text(_make_graded_notebook(None, ""))

    grades = collect_grades([nb1, nb2])
    assert len(grades) == 2
    assert grades[0]["student"] == "alice"
    assert grades[0]["mark"] == 72
    assert grades[0]["feedback"] == "Excellent work"
    assert grades[1]["student"] == "bob"
    assert grades[1]["mark"] is None


def test_write_grades_csv(tmp_path):
    grades = [
        {"student": "alice", "mark": 72, "feedback": "Good"},
        {"student": "bob", "mark": 55, "feedback": "Needs work"},
    ]
    csv_path = tmp_path / "grades.csv"
    write_grades_csv(grades, csv_path)

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 2
    assert rows[0]["student"] == "alice"
    assert rows[0]["mark"] == "72"
    assert rows[1]["feedback"] == "Needs work"
