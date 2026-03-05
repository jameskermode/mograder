import csv
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from mograder.cells import inject_grading_cells
from mograder.feedback import (
    collect_grades,
    export_feedback_html,
    inject_feedback_html,
    write_grades_csv,
)
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


# --- per-question marks ---


def _make_graded_notebook_with_marks(manual_mark, feedback_text):
    """Create graded notebook with per-question marks."""
    marks = {"Q1": 10, "Analysis": 90}
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
    injected = inject_grading_cells(lines, checks, marks=marks)
    text = "".join(injected)
    if manual_mark is not None:
        text = text.replace("_mark = None", f"_mark = {manual_mark}")
    if feedback_text:
        text = text.replace('_feedback = ""', f'_feedback = "{feedback_text}"')
    return text


def test_collect_grades_with_auto_marks(tmp_path):
    nb = tmp_path / "alice.py"
    nb.write_text(_make_graded_notebook_with_marks(70, "Good analysis"))
    grades = collect_grades([nb])
    assert len(grades) == 1
    assert grades[0]["auto_mark"] == 10  # Q1 passed
    assert grades[0]["mark"] == 80  # 10 auto + 70 manual


def test_collect_grades_auto_marks_none_without_marks(tmp_path):
    nb = tmp_path / "alice.py"
    nb.write_text(_make_graded_notebook(72, "Good"))
    grades = collect_grades([nb])
    assert grades[0]["auto_mark"] is None
    assert grades[0]["mark"] == 72


def test_write_grades_csv_with_auto_mark(tmp_path):
    grades = [
        {"student": "alice", "mark": 80, "auto_mark": 10, "feedback": "Good"},
        {"student": "bob", "mark": 75, "auto_mark": 10, "feedback": "OK"},
    ]
    csv_path = tmp_path / "grades.csv"
    write_grades_csv(grades, csv_path)

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert "auto_mark" in rows[0]
    assert rows[0]["auto_mark"] == "10"


def test_write_grades_csv_omits_auto_mark_when_none(tmp_path):
    grades = [
        {"student": "alice", "mark": 72, "auto_mark": None, "feedback": "Good"},
    ]
    csv_path = tmp_path / "grades.csv"
    write_grades_csv(grades, csv_path)

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert "auto_mark" not in rows[0]


# --- HTML injection ---


def _make_marimo_html(cells=None):
    """Build a minimal marimo static HTML page with __MARIMO_MOUNT_CONFIG__."""
    if cells is None:
        cells = [
            {
                "code": "x = 1",
                "code_hash": "abc",
                "config": {"column": None, "disabled": False, "hide_code": False},
                "id": "AAAA",
                "name": "_",
            }
        ]
    session_cells = [
        {
            "code_hash": c["code_hash"],
            "console": [],
            "id": c["id"],
            "outputs": [{"data": {"text/plain": ""}, "type": "data"}],
        }
        for c in cells
    ]
    config = {
        "filename": "test.py",
        "mode": "read",
        "notebook": {"cells": cells, "metadata": {}, "version": "1"},
        "session": {
            "cells": session_cells,
            "metadata": {},
            "version": "1",
        },
        "runtimeConfig": None,
    }
    config_json = json.dumps(config)
    # Mimic marimo's JS-style trailing comma
    config_json = config_json[:-1] + ",}"
    return (
        "<html><body>\n"
        '    <script data-marimo="true">\n'
        f"      window.__MARIMO_MOUNT_CONFIG__ = {config_json};\n"
        "    </script>\n"
        "</body></html>\n"
    )


def test_inject_feedback_html_holistic(tmp_path):
    html_src = _make_marimo_html()
    dest = tmp_path / "out.html"

    inject_feedback_html(html_src, dest, mark=72, feedback_text="Good work")

    result = dest.read_text()
    assert "marimo-callout-output" in result
    assert "72/100" in result
    assert "Good work" in result

    # Verify the JSON is parseable (extract and check)
    prefix = "window.__MARIMO_MOUNT_CONFIG__ = "
    start = result.index(prefix) + len(prefix)
    config, _ = json.JSONDecoder().raw_decode(result, start)
    assert len(config["notebook"]["cells"]) == 2
    assert len(config["session"]["cells"]) == 2
    assert config["notebook"]["cells"][-1]["id"] == "mgFB"
    assert config["session"]["cells"][-1]["id"] == "mgFB"


def test_inject_feedback_html_with_marks(tmp_path):
    html_src = _make_marimo_html()
    dest = tmp_path / "out.html"

    inject_feedback_html(
        html_src,
        dest,
        mark=90,
        feedback_text="Excellent analysis",
        auto_mark=40,
        total_available=100,
    )

    result = dest.read_text()
    assert "90/100" in result
    assert "auto: 40" in result
    assert "manual: 50" in result
    assert "Excellent analysis" in result


def test_export_uses_injection_when_html_exists(tmp_path):
    """When autograde HTML exists, export uses injection (no subprocess)."""
    # Create graded .py notebook
    nb = tmp_path / "student.py"
    nb.write_text(_make_graded_notebook(72, "Good work"))

    # Create matching autograde .html
    html_file = tmp_path / "student.html"
    html_file.write_text(_make_marimo_html())

    out_dir = tmp_path / "feedback"

    with patch("mograder.feedback.subprocess.run") as mock_run:
        html_path = export_feedback_html(nb, out_dir)
        mock_run.assert_not_called()

    assert html_path.exists()
    assert html_path.name == "student.html"
    content = html_path.read_text()
    assert "72/100" in content
    assert "Good work" in content


def test_export_falls_back_when_no_html(tmp_path):
    """When no autograde HTML exists, falls back to marimo export."""
    nb = tmp_path / "student.py"
    nb.write_text("# notebook")
    out_dir = tmp_path / "feedback"

    def mock_run(cmd, **kwargs):
        dest = Path(cmd[cmd.index("-o") + 1])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("<html>exported</html>")
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        return result

    with patch("mograder.feedback.subprocess.run", side_effect=mock_run) as mock:
        html_path = export_feedback_html(nb, out_dir)
        mock.assert_called_once()

    assert html_path.exists()


def test_export_copies_html_when_ungraded(tmp_path):
    """When mark is None (ungraded), HTML is copied without injection."""
    nb = tmp_path / "student.py"
    nb.write_text(_make_graded_notebook(None, ""))

    original_html = _make_marimo_html()
    html_file = tmp_path / "student.html"
    html_file.write_text(original_html)

    out_dir = tmp_path / "feedback"
    html_path = export_feedback_html(nb, out_dir)

    assert html_path.exists()
    # Should be a copy — no injection, so no "mgFB" cell
    content = html_path.read_text()
    assert "mgFB" not in content
