from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from mograder.cli import cli
from mograder.models import CheckResult, NotebookResult


@patch("mograder.markers.process_file")
def test_generate_calls_process_file(mock_pf, tmp_path):
    nb = tmp_path / "staff.py"
    nb.write_text("# notebook")
    mock_pf.return_value = True

    runner = CliRunner()
    result = runner.invoke(cli, ["generate", str(nb), "-o", str(tmp_path / "out")])
    assert result.exit_code == 0
    mock_pf.assert_called_once()


@patch("mograder.markers.process_file")
def test_generate_dry_run(mock_pf, tmp_path):
    nb = tmp_path / "staff.py"
    nb.write_text("# notebook")
    mock_pf.return_value = True

    runner = CliRunner()
    result = runner.invoke(cli, ["generate", str(nb), "--dry-run"])
    assert result.exit_code == 0
    args, kwargs = mock_pf.call_args
    assert kwargs.get("dry_run") or args[2] is True


@patch("mograder.markers.process_file")
def test_generate_validate(mock_pf, tmp_path):
    nb = tmp_path / "staff.py"
    nb.write_text("# notebook")
    mock_pf.return_value = True

    runner = CliRunner()
    result = runner.invoke(cli, ["generate", str(nb), "--validate"])
    assert result.exit_code == 0
    args, kwargs = mock_pf.call_args
    assert kwargs.get("validate_only") or args[3] is True


@patch("mograder.markers.process_file")
def test_generate_failure_exits_nonzero(mock_pf, tmp_path):
    nb = tmp_path / "bad.py"
    nb.write_text("# bad")
    mock_pf.return_value = False

    runner = CliRunner()
    result = runner.invoke(cli, ["generate", str(nb)])
    assert result.exit_code != 0


@patch("mograder.cells.inject_grading_cells")
@patch("mograder.runner.run_batch")
def test_autograde_runs_and_injects(mock_batch, mock_inject, tmp_path):
    nb = tmp_path / "student.py"
    nb.write_text(
        "import marimo\napp = marimo.App()\n\nif __name__ == '__main__':\n    app.run()\n"
    )

    mock_batch.return_value = [
        NotebookResult(
            path=nb,
            checks=[CheckResult("Q1: Foo", "success")],
            cell_errors=0,
        )
    ]
    mock_inject.return_value = nb.read_text().splitlines(keepends=True)

    out_dir = tmp_path / "grading"
    runner = CliRunner()
    result = runner.invoke(cli, ["autograde", str(nb), "-o", str(out_dir)])
    assert result.exit_code == 0
    mock_batch.assert_called_once()
    mock_inject.assert_called_once()


@patch("mograder.feedback.export_feedback_html")
@patch("mograder.feedback.collect_grades")
def test_feedback_collects_and_exports(mock_grades, mock_export, tmp_path):
    nb = tmp_path / "graded.py"
    nb.write_text("# graded notebook")

    mock_grades.return_value = [{"student": "graded", "mark": 72, "feedback": "Good"}]
    mock_export.return_value = tmp_path / "feedback" / "graded.html"

    runner = CliRunner()
    result = runner.invoke(cli, ["feedback", str(nb), "-o", str(tmp_path / "feedback")])
    assert result.exit_code == 0
    assert "1/1 notebooks have been graded" in result.output
    mock_export.assert_called_once()


@patch("mograder.feedback.write_grades_csv")
@patch("mograder.feedback.export_feedback_html")
@patch("mograder.feedback.collect_grades")
def test_feedback_writes_grades_csv(mock_grades, mock_export, mock_csv, tmp_path):
    nb = tmp_path / "graded.py"
    nb.write_text("# graded")

    mock_grades.return_value = [{"student": "graded", "mark": 72, "feedback": "Good"}]
    mock_export.return_value = tmp_path / "graded.html"

    runner = CliRunner()
    csv_path = tmp_path / "grades.csv"
    result = runner.invoke(
        cli,
        [
            "feedback",
            str(nb),
            "-o",
            str(tmp_path / "fb"),
            "--grades-csv",
            str(csv_path),
        ],
    )
    assert result.exit_code == 0
    mock_csv.assert_called_once()
