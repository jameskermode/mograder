import csv
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from mograder.models import CheckResult, NotebookResult
from mograder.runner import (
    build_zip,
    create_shared_sandbox,
    discover_labels,
    run_batch,
    run_notebook,
    write_csv,
)


SAMPLE_HTML_PATH = Path(__file__).parent / "fixtures" / "sample_export.html"
SAMPLE_HTML = SAMPLE_HTML_PATH.read_text()


def _mock_subprocess_success(tmp_path):
    """Create a mock subprocess.run that writes sample HTML."""

    def mock_run(cmd, **kwargs):
        # Write HTML to the -o path
        out_path = Path(cmd[cmd.index("-o") + 1])
        out_path.write_text(SAMPLE_HTML)
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        return result

    return mock_run


def test_run_notebook_success(tmp_path):
    nb = tmp_path / "student.py"
    nb.write_text("# notebook")

    with patch(
        "mograder.runner.subprocess.run", side_effect=_mock_subprocess_success(tmp_path)
    ):
        result = run_notebook(nb, timeout=60)

    assert result.export_ok is True
    assert len(result.checks) == 3
    assert result.cell_errors == 2


def test_run_notebook_export_failure(tmp_path):
    nb = tmp_path / "bad.py"
    nb.write_text("# bad")

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 1
        result.stderr = "some error"
        # Don't create the output file
        out_path = Path(cmd[cmd.index("-o") + 1])
        out_path.unlink(missing_ok=True)
        return result

    with patch("mograder.runner.subprocess.run", side_effect=mock_run):
        result = run_notebook(nb, timeout=60)

    assert result.export_ok is False
    assert "some error" in result.export_error


def test_run_notebook_timeout(tmp_path):
    nb = tmp_path / "slow.py"
    nb.write_text("# slow")

    with patch(
        "mograder.runner.subprocess.run",
        side_effect=subprocess.TimeoutExpired("cmd", 5),
    ):
        result = run_notebook(nb, timeout=5)

    assert result.export_ok is False
    assert "timeout" in result.export_error


def test_run_notebook_saves_html(tmp_path):
    nb = tmp_path / "student.py"
    nb.write_text("# notebook")
    html_dir = tmp_path / "html"
    html_dir.mkdir()

    with patch(
        "mograder.runner.subprocess.run", side_effect=_mock_subprocess_success(tmp_path)
    ):
        result = run_notebook(nb, timeout=60, html_dir=html_dir)

    assert result.html_path is not None
    assert result.html_path.exists()


def test_run_batch(tmp_path):
    nbs = []
    for name in ["alice.py", "bob.py"]:
        nb = tmp_path / name
        nb.write_text("# notebook")
        nbs.append(nb)

    with patch(
        "mograder.runner.subprocess.run", side_effect=_mock_subprocess_success(tmp_path)
    ):
        results = run_batch(nbs, jobs=2, timeout=60)

    assert len(results) == 2
    # Sorted by stem
    assert results[0].path.stem == "alice"
    assert results[1].path.stem == "bob"


def test_discover_labels():
    results = [
        NotebookResult(
            path=Path("a.py"),
            checks=[
                CheckResult("Q1: Foo", "success"),
                CheckResult("Q2: Bar", "danger"),
            ],
        ),
        NotebookResult(
            path=Path("b.py"),
            checks=[CheckResult("Q1: Foo", "warn")],
        ),
    ]
    labels = discover_labels(results)
    assert labels == ["Q1: Foo", "Q2: Bar"]


def test_write_csv(tmp_path):
    results = [
        NotebookResult(
            path=Path("alice.py"),
            checks=[CheckResult("Q1: Foo", "success")],
            cell_errors=0,
        ),
        NotebookResult(
            path=Path("bob.py"),
            export_ok=False,
            export_error="timeout",
        ),
    ]
    labels = ["Q1: Foo"]
    csv_path = tmp_path / "results.csv"
    write_csv(results, labels, csv_path)

    with open(csv_path) as f:
        reader = csv.reader(f)
        rows = list(reader)

    assert rows[0] == ["notebook", "Q1", "cell_errors", "export_error"]
    assert rows[1][0] == "alice"
    assert rows[1][1] == "PASS"
    assert rows[2][0] == "bob"
    assert rows[2][1] == "EXPORT_FAILED"


def test_write_csv_with_marks(tmp_path):
    results = [
        NotebookResult(
            path=Path("alice.py"),
            checks=[
                CheckResult("Q1: Foo", "success"),
                CheckResult("Q2: Bar", "danger"),
            ],
            cell_errors=0,
        ),
    ]
    labels = ["Q1: Foo", "Q2: Bar"]
    marks = {"Q1": 10, "Q2": 20, "Analysis": 70}
    csv_path = tmp_path / "results.csv"
    write_csv(results, labels, csv_path, marks=marks)

    with open(csv_path) as f:
        reader = csv.reader(f)
        rows = list(reader)

    assert "auto_mark" in rows[0]
    assert rows[1][-1] == "10"  # Only Q1 passed


def test_write_csv_without_marks_unchanged(tmp_path):
    results = [
        NotebookResult(
            path=Path("alice.py"),
            checks=[CheckResult("Q1: Foo", "success")],
            cell_errors=0,
        ),
    ]
    labels = ["Q1: Foo"]
    csv_path = tmp_path / "results.csv"
    write_csv(results, labels, csv_path)

    with open(csv_path) as f:
        reader = csv.reader(f)
        rows = list(reader)

    assert "auto_mark" not in rows[0]


def test_print_summary_with_marks(capsys):
    results = [
        NotebookResult(
            path=Path("alice.py"),
            checks=[
                CheckResult("Q1: Foo", "success"),
                CheckResult("Q2: Bar", "danger"),
            ],
        ),
    ]
    labels = ["Q1: Foo", "Q2: Bar"]
    marks = {"Q1": 10, "Q2": 20}
    from mograder.runner import print_summary

    print_summary(results, labels, marks=marks)
    captured = capsys.readouterr()
    assert "Marks" in captured.out
    assert "10/30" in captured.out


def test_run_batch_on_progress_called(tmp_path):
    nbs = []
    for name in ["alice.py", "bob.py", "carol.py"]:
        nb = tmp_path / name
        nb.write_text("# notebook")
        nbs.append(nb)

    progress_calls = []

    def on_progress(completed, total, path):
        progress_calls.append((completed, total, path))

    with patch(
        "mograder.runner.subprocess.run", side_effect=_mock_subprocess_success(tmp_path)
    ):
        results = run_batch(nbs, jobs=2, timeout=60, on_progress=on_progress)

    assert len(results) == 3
    assert len(progress_calls) == 3
    # All calls should have total=3
    assert all(t == 3 for _, t, _ in progress_calls)
    # Completed counts should be 1, 2, 3 (in some order due to parallel execution)
    assert sorted(c for c, _, _ in progress_calls) == [1, 2, 3]


def test_build_zip(tmp_path):
    nb = tmp_path / "alice.py"
    nb.write_text("# notebook")
    results = [
        NotebookResult(
            path=nb,
            checks=[CheckResult("Q1: Foo", "success")],
        ),
    ]
    labels = ["Q1: Foo"]
    zip_path = tmp_path / "bundle.zip"
    build_zip(results, labels, zip_path)

    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert "results.csv" in names
        assert "sources/alice.py" in names


def test_run_notebook_with_sandbox_dir(tmp_path):
    """When sandbox_dir is provided, run_notebook uses its python and --no-sandbox."""
    nb = tmp_path / "student.py"
    nb.write_text("# notebook")

    # Create a fake sandbox dir structure (.venv with bin/python)
    sandbox_dir = tmp_path / ".venv"
    (sandbox_dir / "bin").mkdir(parents=True)
    fake_python = sandbox_dir / "bin" / "python"
    fake_python.touch()

    with patch(
        "mograder.runner.subprocess.run", side_effect=_mock_subprocess_success(tmp_path)
    ) as mock_run:
        result = run_notebook(nb, timeout=60, sandbox_dir=sandbox_dir)

    assert result.export_ok is True
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == str(fake_python)
    assert "--no-sandbox" in cmd


def test_run_notebook_without_sandbox_uses_sys_executable(tmp_path):
    """Without sandbox_dir, run_notebook uses sys.executable and no --no-sandbox."""
    nb = tmp_path / "student.py"
    nb.write_text("# notebook")

    with patch(
        "mograder.runner.subprocess.run", side_effect=_mock_subprocess_success(tmp_path)
    ) as mock_run:
        run_notebook(nb, timeout=60)

    cmd = mock_run.call_args[0][0]
    assert cmd[0] == sys.executable
    assert "--no-sandbox" not in cmd


def test_run_batch_passes_sandbox_dir(tmp_path):
    """run_batch passes sandbox_dir through to run_notebook."""
    nbs = []
    for name in ["alice.py", "bob.py"]:
        nb = tmp_path / name
        nb.write_text("# notebook")
        nbs.append(nb)

    sandbox_dir = tmp_path / ".venv"
    (sandbox_dir / "bin").mkdir(parents=True)

    with patch(
        "mograder.runner.subprocess.run", side_effect=_mock_subprocess_success(tmp_path)
    ) as mock_run:
        results = run_batch(nbs, jobs=2, timeout=60, sandbox_dir=sandbox_dir)

    assert len(results) == 2
    # Every subprocess call should use the sandbox python
    for call in mock_run.call_args_list:
        cmd = call[0][0]
        assert cmd[0] == str(sandbox_dir / "bin" / "python")
        assert "--no-sandbox" in cmd


def test_create_shared_sandbox_returns_none_without_deps(tmp_path):
    """create_shared_sandbox returns None when uv export fails or returns empty."""
    nb = tmp_path / "simple.py"
    nb.write_text("# no deps")

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 1
        result.stdout = ""
        result.stderr = "no script metadata"
        return result

    with patch("mograder.runner.subprocess.run", side_effect=mock_run):
        result = create_shared_sandbox(nb)

    assert result is None


def test_create_shared_sandbox_reuses_existing_venv(tmp_path):
    """create_shared_sandbox skips venv creation if .venv/bin/python already exists."""
    nb = tmp_path / "notebook.py"
    nb.write_text("# has deps")

    # Pre-create the venv structure
    venv_dir = tmp_path / ".venv"
    (venv_dir / "bin").mkdir(parents=True)
    (venv_dir / "bin" / "python").touch()

    calls = []

    def mock_run(cmd, **kwargs):
        calls.append(cmd)
        result = MagicMock()
        result.returncode = 0
        result.stdout = "numpy>=1.0\n"
        result.stderr = ""
        return result

    with patch("mograder.runner.subprocess.run", side_effect=mock_run):
        result = create_shared_sandbox(nb)

    assert result == venv_dir
    # Should have called uv export + uv pip install, but NOT uv venv
    cmd_strs = [" ".join(str(c) for c in cmd) for cmd in calls]
    assert any("uv export" in c for c in cmd_strs)
    assert any("uv pip install" in c for c in cmd_strs)
    assert not any("uv venv" in c for c in cmd_strs)
