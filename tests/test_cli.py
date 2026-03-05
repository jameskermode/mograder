from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

import json

from mograder.cli import _find_source, _infer_output_dir, cli
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


# -- Smart defaults -----------------------------------------------------------


def test_infer_output_dir_source_convention(tmp_path):
    source_dir = tmp_path / "source" / "hw1"
    source_dir.mkdir(parents=True)
    nb = source_dir / "hw1.py"
    nb.touch()
    result = _infer_output_dir(nb, "source", "release", "release")
    assert result == tmp_path / "release" / "hw1"


def test_infer_output_dir_fallback(tmp_path):
    nb = tmp_path / "notebook.py"
    nb.touch()
    result = _infer_output_dir(nb, "source", "release", "release")
    assert result == Path("release")


def test_find_source_convention(tmp_path):
    # Set up: submitted/hw1/student.py  + source/hw1/student.py
    (tmp_path / "submitted" / "hw1").mkdir(parents=True)
    (tmp_path / "source" / "hw1").mkdir(parents=True)
    sub = tmp_path / "submitted" / "hw1" / "nb.py"
    src = tmp_path / "source" / "hw1" / "nb.py"
    sub.touch()
    src.write_text("# source")
    found = _find_source(sub)
    assert found == src


def test_find_source_not_found(tmp_path):
    nb = tmp_path / "random" / "nb.py"
    nb.parent.mkdir(parents=True)
    nb.touch()
    assert _find_source(nb) is None


@patch("subprocess.run")
def test_formgrader_launches_marimo(mock_run, tmp_path):
    """formgrader sets env var and launches marimo run."""
    mock_run.return_value = MagicMock(returncode=0)
    CliRunner().invoke(cli, ["formgrader", str(tmp_path)])
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "marimo" in " ".join(cmd)
    assert "run" in cmd
    assert "formgrader_app.py" in cmd[-1]


@patch("subprocess.run")
def test_formgrader_does_not_sandbox(mock_run, tmp_path):
    """formgrader must not pass --sandbox; mograder would not be importable."""
    mock_run.return_value = MagicMock(returncode=0)
    CliRunner().invoke(cli, ["formgrader", str(tmp_path)])
    cmd = mock_run.call_args[0][0]
    assert "--sandbox" not in cmd


def test_formgrader_app_has_no_script_header():
    """The app file must not have a PEP 723 script header (/// script).

    If present, marimo prompts for sandbox install which blocks the app
    since mograder is a local package.
    """
    app_path = Path(__file__).parent.parent / "src" / "mograder" / "formgrader_app.py"
    header = app_path.read_text(encoding="utf-8")[:200]
    assert "/// script" not in header


@patch("mograder.runner.create_shared_sandbox", return_value=None)
@patch("mograder.runner.run_notebook")
@patch("mograder.cells.inject_grading_cells")
@patch("mograder.runner.run_batch")
def test_autograde_with_source(
    mock_batch, mock_inject, mock_run_nb, mock_sandbox, tmp_path
):
    """autograde --source runs the source notebook and uses integrity check."""
    nb = tmp_path / "student.py"
    nb.write_text(
        "import marimo\napp = marimo.App()\n\nif __name__ == '__main__':\n    app.run()\n"
    )
    source = tmp_path / "source.py"
    source.write_text(
        "import marimo\napp = marimo.App()\n\nif __name__ == '__main__':\n    app.run()\n"
    )

    mock_run_nb.return_value = NotebookResult(
        path=source,
        checks=[CheckResult("Q1: Foo", "success")],
        cell_errors=0,
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
    result = runner.invoke(
        cli, ["autograde", str(nb), "--source", str(source), "-o", str(out_dir)]
    )
    assert result.exit_code == 0
    mock_run_nb.assert_called_once()
    assert "Running source notebook" in result.output


@patch("mograder.cells.inject_grading_cells")
@patch("mograder.runner.run_batch")
def test_autograde_progress_flag(mock_batch, mock_inject, tmp_path):
    """--progress emits JSON start + progress events to stderr."""
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
    result = runner.invoke(
        cli, ["autograde", str(nb), "-o", str(out_dir), "--progress"]
    )
    assert result.exit_code == 0

    # Parse JSON lines from combined output (CliRunner merges stdout/stderr)
    json_msgs = []
    for line in result.output.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                json_msgs.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    # Should have a start event
    start_msgs = [m for m in json_msgs if m.get("event") == "start"]
    assert len(start_msgs) == 1
    assert start_msgs[0]["total"] == 1

    # run_batch should have been called with on_progress callback
    call_kwargs = mock_batch.call_args[1]
    assert call_kwargs.get("on_progress") is not None


@patch("mograder.runner.create_shared_sandbox")
@patch("mograder.runner.run_notebook")
@patch("mograder.cells.inject_grading_cells")
@patch("mograder.runner.run_batch")
def test_autograde_creates_shared_sandbox(
    mock_batch, mock_inject, mock_run_nb, mock_sandbox, tmp_path
):
    """autograde creates a shared sandbox from source and cleans it up."""
    nb = tmp_path / "student.py"
    nb.write_text(
        "import marimo\napp = marimo.App()\n\nif __name__ == '__main__':\n    app.run()\n"
    )
    source = tmp_path / "source.py"
    source.write_text(
        "import marimo\napp = marimo.App()\n\nif __name__ == '__main__':\n    app.run()\n"
    )

    # Simulate create_shared_sandbox returning a persistent .venv dir
    sandbox_dir = tmp_path / ".venv"
    sandbox_dir.mkdir()
    mock_sandbox.return_value = sandbox_dir

    mock_run_nb.return_value = NotebookResult(
        path=source,
        checks=[CheckResult("Q1: Foo", "success")],
        cell_errors=0,
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
    cli_runner = CliRunner()
    result = cli_runner.invoke(
        cli, ["autograde", str(nb), "--source", str(source), "-o", str(out_dir)]
    )
    assert result.exit_code == 0

    # Sandbox was created from source notebook
    mock_sandbox.assert_called_once_with(source)

    # Sandbox was passed to run_notebook (source) and run_batch
    assert mock_run_nb.call_args[1].get("sandbox_dir") == sandbox_dir
    assert mock_batch.call_args[1].get("sandbox_dir") == sandbox_dir

    # Sandbox dir is persistent — not cleaned up
    assert sandbox_dir.exists()


@patch("mograder.runner.create_shared_sandbox")
@patch("mograder.runner.run_notebook")
@patch("mograder.cells.inject_grading_cells")
@patch("mograder.runner.run_batch")
def test_autograde_progress_sandbox_events(
    mock_batch, mock_inject, mock_run_nb, mock_sandbox, tmp_path
):
    """--progress emits sandbox_start and sandbox_done events when source has deps."""
    nb = tmp_path / "student.py"
    nb.write_text(
        "import marimo\napp = marimo.App()\n\nif __name__ == '__main__':\n    app.run()\n"
    )
    source = tmp_path / "source.py"
    source.write_text(
        "import marimo\napp = marimo.App()\n\nif __name__ == '__main__':\n    app.run()\n"
    )

    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir()
    mock_sandbox.return_value = sandbox_dir

    mock_run_nb.return_value = NotebookResult(
        path=source,
        checks=[CheckResult("Q1: Foo", "success")],
        cell_errors=0,
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
    cli_runner = CliRunner()
    result = cli_runner.invoke(
        cli,
        [
            "autograde",
            str(nb),
            "--source",
            str(source),
            "-o",
            str(out_dir),
            "--progress",
        ],
    )
    assert result.exit_code == 0

    # Parse JSON lines from output
    json_msgs = []
    for line in result.output.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                json_msgs.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    events = [m["event"] for m in json_msgs]
    assert "sandbox_start" in events
    assert "sandbox_done" in events

    # sandbox_start comes before sandbox_done
    assert events.index("sandbox_start") < events.index("sandbox_done")

    # sandbox_done should indicate created=True
    done_msg = next(m for m in json_msgs if m["event"] == "sandbox_done")
    assert done_msg["created"] is True
