import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

import json

from mograder.cli import (
    _find_source,
    _find_source_for_assignment,
    _infer_output_dir,
    _resolve_assignments,
    cli,
)
from mograder.grading.cells import _inject_cell_hashes
from mograder.core.models import CheckResult, NotebookResult


@patch("mograder.grading.cells.process_file")
def test_generate_calls_process_file(mock_pf, tmp_path):
    nb = tmp_path / "staff.py"
    nb.write_text("# notebook")
    mock_pf.return_value = True

    runner = CliRunner()
    result = runner.invoke(cli, ["generate", str(nb), "-o", str(tmp_path / "out")])
    assert result.exit_code == 0
    mock_pf.assert_called_once()


@patch("mograder.grading.cells.process_file")
def test_generate_dry_run(mock_pf, tmp_path):
    nb = tmp_path / "staff.py"
    nb.write_text("# notebook")
    mock_pf.return_value = True

    runner = CliRunner()
    result = runner.invoke(cli, ["generate", str(nb), "--dry-run"])
    assert result.exit_code == 0
    args, kwargs = mock_pf.call_args
    assert kwargs.get("dry_run") or args[2] is True


@patch("mograder.grading.cells.process_file")
def test_generate_validate(mock_pf, tmp_path):
    nb = tmp_path / "staff.py"
    nb.write_text("# notebook")
    mock_pf.return_value = True

    runner = CliRunner()
    result = runner.invoke(cli, ["generate", str(nb), "--validate"])
    assert result.exit_code == 0
    args, kwargs = mock_pf.call_args
    assert kwargs.get("validate_only") or args[3] is True


@patch("mograder.grading.cells.process_file")
def test_generate_failure_exits_nonzero(mock_pf, tmp_path):
    nb = tmp_path / "bad.py"
    nb.write_text("# bad")
    mock_pf.return_value = False

    runner = CliRunner()
    result = runner.invoke(cli, ["generate", str(nb)])
    assert result.exit_code != 0


@patch("mograder.grading.cells.build_release_zip")
@patch("mograder.grading.cells.process_file")
def test_generate_creates_zip(mock_pf, mock_zip, tmp_path):
    """generate calls build_release_zip for each processed directory."""
    src_dir = tmp_path / "source" / "hw1"
    src_dir.mkdir(parents=True)
    nb = src_dir / "hw1.py"
    nb.write_text("# notebook")

    out = tmp_path / "release"
    rel_dir = out / "hw1"
    rel_dir.mkdir(parents=True)

    mock_pf.return_value = True
    mock_zip.return_value = rel_dir / "hw1.zip"

    runner = CliRunner()
    result = runner.invoke(cli, ["generate", str(nb), "-o", str(out), "--no-validate"])
    assert result.exit_code == 0
    mock_zip.assert_called_once()


@patch("mograder.grading.cells.build_release_zip")
@patch("mograder.grading.cells.process_file")
def test_generate_dry_run_no_zip(mock_pf, mock_zip, tmp_path):
    """--dry-run should NOT call build_release_zip."""
    nb = tmp_path / "staff.py"
    nb.write_text("# notebook")
    mock_pf.return_value = True

    runner = CliRunner()
    result = runner.invoke(cli, ["generate", str(nb), "--dry-run"])
    assert result.exit_code == 0
    mock_zip.assert_not_called()


@patch("mograder.grading.cells.build_release_zip")
@patch("mograder.grading.cells.process_file")
def test_generate_validate_no_zip(mock_pf, mock_zip, tmp_path):
    """--validate should NOT call build_release_zip."""
    nb = tmp_path / "staff.py"
    nb.write_text("# notebook")
    mock_pf.return_value = True

    runner = CliRunner()
    result = runner.invoke(cli, ["generate", str(nb), "--validate"])
    assert result.exit_code == 0
    mock_zip.assert_not_called()


@patch("mograder.grading.cells.inject_grading_cells")
@patch("mograder.grading.runner.run_batch")
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


@patch("mograder.grading.cells.inject_grading_cells")
@patch("mograder.grading.runner.run_batch")
def test_autograde_jobs_default_from_config(
    mock_batch, mock_inject, tmp_path, monkeypatch
):
    """Without ``-j``, autograde uses ``[defaults] jobs`` from mograder.toml."""
    nb = tmp_path / "student.py"
    nb.write_text(
        "import marimo\napp = marimo.App()\n\nif __name__ == '__main__':\n    app.run()\n"
    )
    (tmp_path / "mograder.toml").write_text("[defaults]\njobs = 1\n")
    mock_batch.return_value = [
        NotebookResult(
            path=nb,
            checks=[CheckResult("Q1: Foo", "success")],
            cell_errors=0,
        )
    ]
    mock_inject.return_value = nb.read_text().splitlines(keepends=True)
    monkeypatch.chdir(tmp_path)

    out_dir = tmp_path / "grading"
    runner = CliRunner()
    result = runner.invoke(cli, ["autograde", str(nb), "-o", str(out_dir)])
    assert result.exit_code == 0, result.output
    _, kwargs = mock_batch.call_args
    assert kwargs["jobs"] == 1


@patch("mograder.grading.cells.inject_grading_cells")
@patch("mograder.grading.runner.run_batch")
def test_autograde_jobs_flag_overrides_config(
    mock_batch, mock_inject, tmp_path, monkeypatch
):
    """``-j`` on the command line wins over ``[defaults] jobs`` in config."""
    nb = tmp_path / "student.py"
    nb.write_text(
        "import marimo\napp = marimo.App()\n\nif __name__ == '__main__':\n    app.run()\n"
    )
    (tmp_path / "mograder.toml").write_text("[defaults]\njobs = 1\n")
    mock_batch.return_value = [
        NotebookResult(
            path=nb,
            checks=[CheckResult("Q1: Foo", "success")],
            cell_errors=0,
        )
    ]
    mock_inject.return_value = nb.read_text().splitlines(keepends=True)
    monkeypatch.chdir(tmp_path)

    out_dir = tmp_path / "grading"
    runner = CliRunner()
    result = runner.invoke(cli, ["autograde", str(nb), "-o", str(out_dir), "-j", "3"])
    assert result.exit_code == 0, result.output
    _, kwargs = mock_batch.call_args
    assert kwargs["jobs"] == 3


@patch("mograder.grading.cells.inject_grading_cells")
@patch("mograder.grading.runner.run_batch")
def test_autograde_max_memory_flag(mock_batch, mock_inject, tmp_path):
    """--max-memory converts MB to bytes and passes to run_batch as rlimit_as."""
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
        cli, ["autograde", str(nb), "-o", str(out_dir), "--max-memory", "2048"]
    )
    assert result.exit_code == 0
    _, kwargs = mock_batch.call_args
    assert kwargs["rlimit_as"] == 2048 * 1024 * 1024
    assert kwargs["isolate_cwd"] is True


@patch("mograder.grading.feedback.export_feedback_html")
@patch("mograder.grading.feedback.collect_grades")
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


@patch("mograder.grading.feedback.write_grades_csv")
@patch("mograder.grading.feedback.export_feedback_html")
@patch("mograder.grading.feedback.collect_grades")
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
def test_grader_launches_marimo(mock_run, tmp_path):
    """grader sets env var and launches marimo run."""
    mock_run.return_value = MagicMock(returncode=0)
    CliRunner().invoke(cli, ["grader", str(tmp_path)])
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "marimo" in " ".join(cmd)
    assert "run" in cmd
    assert cmd[-1].endswith(os.path.join("grader", "app.py"))


@patch("subprocess.run")
def test_grader_does_not_sandbox(mock_run, tmp_path):
    """grader must not pass --sandbox; mograder would not be importable."""
    mock_run.return_value = MagicMock(returncode=0)
    CliRunner().invoke(cli, ["grader", str(tmp_path)])
    cmd = mock_run.call_args[0][0]
    assert "--sandbox" not in cmd


def test_grader_app_has_no_script_header():
    """The app file must not have a PEP 723 script header (/// script).

    If present, marimo prompts for sandbox install which blocks the app
    since mograder is a local package.
    """
    app_path = Path(__file__).parent.parent / "src" / "mograder" / "grader" / "app.py"
    header = app_path.read_text(encoding="utf-8")[:200]
    assert "/// script" not in header


@patch("mograder.grading.runner.create_shared_sandbox", return_value=None)
@patch("mograder.grading.runner.run_notebook")
@patch("mograder.grading.cells.inject_grading_cells")
@patch("mograder.grading.runner.run_batch")
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


@patch("mograder.grading.cells.inject_grading_cells")
@patch("mograder.grading.runner.run_batch")
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


@patch("mograder.grading.runner.create_shared_sandbox")
@patch("mograder.grading.runner.run_notebook")
@patch("mograder.grading.cells.inject_grading_cells")
@patch("mograder.grading.runner.run_batch")
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


@patch("mograder.grading.runner.create_shared_sandbox")
@patch("mograder.grading.runner.run_notebook")
@patch("mograder.grading.cells.inject_grading_cells")
@patch("mograder.grading.runner.run_batch")
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
    assert "start" in events
    assert "sandbox_start" in events
    assert "sandbox_done" in events

    # start comes first, then sandbox_start, then sandbox_done
    assert events.index("start") < events.index("sandbox_start")
    assert events.index("sandbox_start") < events.index("sandbox_done")

    # sandbox_done should indicate created=True
    done_msg = next(m for m in json_msgs if m["event"] == "sandbox_done")
    assert done_msg["created"] is True


@patch("mograder.grading.cells.inject_grading_cells")
@patch("mograder.grading.runner.run_batch")
def test_autograde_progress_emits_results(mock_batch, mock_inject, tmp_path):
    """--progress emits a results event with labels and rows."""
    nb = tmp_path / "student.py"
    nb.write_text(
        "import marimo\napp = marimo.App()\n\nif __name__ == '__main__':\n    app.run()\n"
    )

    mock_batch.return_value = [
        NotebookResult(
            path=nb,
            checks=[
                CheckResult("Q1: Foo", "success"),
                CheckResult("Q2: Bar", "danger"),
            ],
            cell_errors=1,
        )
    ]
    mock_inject.return_value = nb.read_text().splitlines(keepends=True)

    out_dir = tmp_path / "grading"
    runner = CliRunner()
    result = runner.invoke(
        cli, ["autograde", str(nb), "-o", str(out_dir), "--progress"]
    )
    assert result.exit_code == 0

    # Parse JSON lines from combined output
    json_msgs = []
    for line in result.output.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                json_msgs.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    results_msgs = [m for m in json_msgs if m.get("event") == "results"]
    assert len(results_msgs) == 1

    results_data = results_msgs[0]
    assert results_data["labels"] == ["Q1", "Q2"]
    assert len(results_data["rows"]) == 1
    assert results_data["rows"][0]["notebook"] == "student"
    assert results_data["rows"][0]["checks"]["Q1"] == "PASS"
    assert results_data["rows"][0]["checks"]["Q2"] == "FAIL"


def test_import_students_removed():
    """import-students command has been removed in favour of moodle sync-users."""
    runner = CliRunner()
    result = runner.invoke(cli, ["import-students", "dummy.csv"])
    assert result.exit_code != 0


# -- _resolve_assignments helper ----------------------------------------------


def test_resolve_assignments_name(tmp_path):
    """Assignment name resolves to .py files in the directory."""
    d = tmp_path / "source" / "hw1"
    d.mkdir(parents=True)
    (d / "hw1.py").write_text("# nb")
    result = _resolve_assignments(("hw1",), str(tmp_path / "source"))
    assert result == (d / "hw1.py",)


def test_resolve_assignments_path(tmp_path):
    """File paths pass through unchanged."""
    nb = tmp_path / "staff.py"
    nb.write_text("# nb")
    result = _resolve_assignments((str(nb),), "source")
    assert result == (nb,)


def test_resolve_assignments_nonexistent_dir(tmp_path):
    """Non-existent assignment directory raises UsageError."""
    import click

    try:
        _resolve_assignments(("nosuch",), str(tmp_path / "source"))
        assert False, "should have raised"
    except click.UsageError as e:
        assert "not found" in str(e)


def test_resolve_assignments_empty_dir(tmp_path):
    """Empty assignment directory raises UsageError."""
    import click

    d = tmp_path / "source" / "empty"
    d.mkdir(parents=True)
    try:
        _resolve_assignments(("empty",), str(tmp_path / "source"))
        assert False, "should have raised"
    except click.UsageError as e:
        assert "No .py files" in str(e)


def test_find_source_for_assignment(tmp_path):
    """_find_source_for_assignment finds .py in source/<name>/."""
    d = tmp_path / "source" / "hw1"
    d.mkdir(parents=True)
    src = d / "hw1.py"
    src.write_text("# source")
    assert _find_source_for_assignment("hw1", str(tmp_path / "source")) == src


def test_find_source_for_assignment_not_found(tmp_path):
    assert _find_source_for_assignment("nope", str(tmp_path / "source")) is None


# -- Name-based CLI invocation ------------------------------------------------


@patch("mograder.grading.cells.process_file")
def test_generate_assignment_name(mock_pf, tmp_path, monkeypatch):
    """generate accepts an assignment name instead of a file path."""
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "source" / "hw1"
    d.mkdir(parents=True)
    (d / "hw1.py").write_text("# nb")
    mock_pf.return_value = True

    runner = CliRunner()
    result = runner.invoke(cli, ["generate", "hw1", "--no-validate"])
    assert result.exit_code == 0, result.output
    mock_pf.assert_called_once()


@patch("mograder.grading.cells.process_file")
def test_generate_backward_compat(mock_pf, tmp_path):
    """generate still works with explicit file paths."""
    nb = tmp_path / "staff.py"
    nb.write_text("# notebook")
    mock_pf.return_value = True

    runner = CliRunner()
    result = runner.invoke(
        cli, ["generate", str(nb), "-o", str(tmp_path / "out"), "--no-validate"]
    )
    assert result.exit_code == 0
    mock_pf.assert_called_once()


@patch("mograder.grading.cells.process_file")
def test_generate_multiple_assignments(mock_pf, tmp_path, monkeypatch):
    """generate accepts multiple assignment names."""
    monkeypatch.chdir(tmp_path)
    for name in ("hw1", "hw2"):
        d = tmp_path / "source" / name
        d.mkdir(parents=True)
        (d / f"{name}.py").write_text("# nb")
    mock_pf.return_value = True

    runner = CliRunner()
    result = runner.invoke(cli, ["generate", "hw1", "hw2", "--no-validate"])
    assert result.exit_code == 0, result.output
    assert mock_pf.call_count == 2


def test_generate_nonexistent_assignment_error(tmp_path, monkeypatch):
    """generate gives a clear error for non-existent assignment name."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "source").mkdir()

    runner = CliRunner()
    result = runner.invoke(cli, ["generate", "nosuch"])
    assert result.exit_code != 0
    assert "not found" in result.output


def test_generate_lecture(tmp_path):
    """generate --lecture strips layout metadata and injects mograder-type."""
    nb = tmp_path / "L01-Intro.py"
    nb.write_text(
        "import marimo\n"
        "\n"
        '__generated_with = "0.19.2"\n'
        "app = marimo.App(\n"
        '    layout_file="layouts/L01-Intro.slides.json",\n'
        '    html_head_file="fragment-slides.html"\n'
        ")\n"
        "\n"
        "@app.cell\n"
        "def _():\n"
        "    import marimo as mo\n"
        "    return (mo,)\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    app.run()\n"
    )

    out = tmp_path / "release"
    runner = CliRunner()
    result = runner.invoke(cli, ["generate", "--lecture", str(nb), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert "lecture" in result.output

    dest = out / "L01-Intro" / "L01-Intro.py"
    assert dest.is_file()

    text = dest.read_text()
    assert "layout_file" not in text
    assert "html_head_file" not in text
    assert "marimo.App()" in text
    assert '# mograder-type = "lecture"' in text


def test_generate_lecture_dry_run(tmp_path):
    """generate --lecture --dry-run does not write files."""
    nb = tmp_path / "L01.py"
    nb.write_text("import marimo\napp = marimo.App()\n")

    out = tmp_path / "release"
    runner = CliRunner()
    result = runner.invoke(
        cli, ["generate", "--lecture", "--dry-run", str(nb), "-o", str(out)]
    )
    assert result.exit_code == 0
    assert "DRY-RUN" in result.output
    assert not (out / "L01" / "L01.py").exists()


def test_generate_lecture_nonexistent_file(tmp_path):
    """generate --lecture errors on missing file."""
    runner = CliRunner()
    result = runner.invoke(cli, ["generate", "--lecture", str(tmp_path / "nope.py")])
    assert result.exit_code != 0
    assert "not found" in result.output


@patch("mograder.grading.cells.inject_grading_cells")
@patch("mograder.grading.runner.run_batch")
def test_autograde_assignment_name(mock_batch, mock_inject, tmp_path, monkeypatch):
    """autograde accepts an assignment name and auto-discovers source."""
    monkeypatch.chdir(tmp_path)
    # Create submitted/hw1/alice.py
    sub_dir = tmp_path / "submitted" / "hw1"
    sub_dir.mkdir(parents=True)
    nb = sub_dir / "alice.py"
    nb.write_text(
        "import marimo\napp = marimo.App()\n\nif __name__ == '__main__':\n    app.run()\n"
    )
    # Create source/hw1/hw1.py (different filename than submission)
    src_dir = tmp_path / "source" / "hw1"
    src_dir.mkdir(parents=True)
    (src_dir / "hw1.py").write_text(
        "import marimo\napp = marimo.App()\n\nif __name__ == '__main__':\n    app.run()\n"
    )

    mock_batch.return_value = [
        NotebookResult(
            path=nb,
            checks=[CheckResult("Q1", "success")],
            cell_errors=0,
        )
    ]
    mock_inject.return_value = nb.read_text().splitlines(keepends=True)

    runner = CliRunner()
    result = runner.invoke(cli, ["autograde", "hw1"])
    assert result.exit_code == 0, result.output
    assert "Auto-discovered source" in result.output


@patch("mograder.grading.feedback.export_feedback_html")
@patch("mograder.grading.feedback.collect_grades")
def test_feedback_assignment_name(mock_grades, mock_export, tmp_path, monkeypatch):
    """feedback accepts an assignment name."""
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "autograded" / "hw1"
    d.mkdir(parents=True)
    nb = d / "alice.py"
    nb.write_text("# graded")

    mock_grades.return_value = [{"student": "alice", "mark": 72, "feedback": "Good"}]
    mock_export.return_value = tmp_path / "feedback" / "hw1" / "alice.html"

    runner = CliRunner()
    result = runner.invoke(cli, ["feedback", "hw1"])
    assert result.exit_code == 0, result.output
    assert "1/1 notebooks have been graded" in result.output


# -- Validate hash warnings ---------------------------------------------------

_VALIDATE_NB = """\
# /// script
# requires-python = ">=3.11"
# ///

import marimo

__generated_with = "0.20.0"
app = marimo.App()


@app.cell
def _():
    x = 1
    return (x,)


@app.cell
def _():
    # YOUR CODE HERE
    pass
    return


@app.cell
def _(x):
    y = x + 1
    return (y,)


if __name__ == "__main__":
    app.run()
"""


@patch("mograder.grading.runner.create_shared_sandbox", return_value=None)
@patch("mograder.grading.runner.run_notebook")
def test_validate_warns_on_modified_cells(mock_run_nb, mock_sandbox, tmp_path):
    """validate prints warnings when non-solution cells are modified."""
    nb_text = _inject_cell_hashes(_VALIDATE_NB)
    # Modify a non-solution cell
    nb_text = nb_text.replace("x = 1", "x = 999")
    nb = tmp_path / "student.py"
    nb.write_text(nb_text)

    mock_run_nb.return_value = NotebookResult(
        path=nb, checks=[CheckResult("Q1", "success")], cell_errors=0
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["validate", str(nb)])
    assert "WARNING" in result.output
    assert "non-solution cell" in result.output.lower()


@patch("mograder.grading.runner.create_shared_sandbox", return_value=None)
@patch("mograder.grading.runner.run_notebook")
def test_validate_no_warning_on_clean_notebook(mock_run_nb, mock_sandbox, tmp_path):
    """validate shows no warnings when cells are unmodified."""
    nb_text = _inject_cell_hashes(_VALIDATE_NB)
    nb = tmp_path / "student.py"
    nb.write_text(nb_text)

    mock_run_nb.return_value = NotebookResult(
        path=nb, checks=[CheckResult("Q1", "success")], cell_errors=0
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["validate", str(nb)])
    assert "WARNING" not in result.output


@patch("mograder.grading.runner.create_shared_sandbox", return_value=None)
@patch("mograder.grading.runner.run_notebook")
def test_validate_fix_restores_cells(mock_run_nb, mock_sandbox, tmp_path):
    """validate --fix with --release restores modified cells."""
    nb_text = _inject_cell_hashes(_VALIDATE_NB)
    release = tmp_path / "release.py"
    release.write_text(nb_text)

    # Modify a non-solution cell
    modified = nb_text.replace("x = 1", "x = 999")
    nb = tmp_path / "student.py"
    nb.write_text(modified)

    mock_run_nb.return_value = NotebookResult(
        path=nb, checks=[CheckResult("Q1", "success")], cell_errors=0
    )

    runner = CliRunner()
    result = runner.invoke(
        cli, ["validate", "--fix", "--release", str(release), str(nb)]
    )
    assert "Fixed" in result.output
    # The file should be restored
    restored = nb.read_text()
    assert "x = 1" in restored
    assert "x = 999" not in restored


@patch("mograder.grading.runner.create_shared_sandbox", return_value=None)
@patch("mograder.grading.runner.run_notebook")
def test_validate_fix_no_release_shows_instructions(
    mock_run_nb, mock_sandbox, tmp_path
):
    """validate --fix without available release prints help message."""
    nb_text = _inject_cell_hashes(_VALIDATE_NB)
    modified = nb_text.replace("x = 1", "x = 999")
    nb = tmp_path / "student.py"
    nb.write_text(modified)

    mock_run_nb.return_value = NotebookResult(
        path=nb, checks=[CheckResult("Q1", "success")], cell_errors=0
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "--fix", str(nb)])
    assert "Cannot fix" in result.output
