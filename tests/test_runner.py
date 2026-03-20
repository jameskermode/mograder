import csv
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mograder.models import CheckResult, NotebookResult
from mograder.runner import (
    _venv_python,
    build_zip,
    create_shared_sandbox,
    discover_labels,
    run_batch,
    run_notebook,
    serialize_results,
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
    assert len(result.checks) == 4
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

    # Create a fake sandbox dir structure (cross-platform venv layout)
    sandbox_dir = tmp_path / ".venv"
    fake_python = _venv_python(sandbox_dir)
    fake_python.parent.mkdir(parents=True)
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
    fake_python = _venv_python(sandbox_dir)
    fake_python.parent.mkdir(parents=True)

    with patch(
        "mograder.runner.subprocess.run", side_effect=_mock_subprocess_success(tmp_path)
    ) as mock_run:
        results = run_batch(nbs, jobs=2, timeout=60, sandbox_dir=sandbox_dir)

    assert len(results) == 2
    # Every subprocess call should use the sandbox python
    for call in mock_run.call_args_list:
        cmd = call[0][0]
        assert cmd[0] == str(fake_python)
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
    """create_shared_sandbox skips venv creation if venv python already exists."""
    nb = tmp_path / "notebook.py"
    nb.write_text("# has deps")

    # Pre-create the venv structure (cross-platform)
    venv_dir = tmp_path / ".venv"
    venv_py = _venv_python(venv_dir)
    venv_py.parent.mkdir(parents=True)
    venv_py.touch()

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


def test_serialize_results():
    results = [
        NotebookResult(
            path=Path("alice.py"),
            checks=[
                CheckResult("Q1: Foo", "success"),
                CheckResult("Q2: Bar", "danger"),
            ],
            cell_errors=1,
        ),
        NotebookResult(
            path=Path("bob.py"),
            export_ok=False,
            export_error="timeout",
        ),
        NotebookResult(
            path=Path("carol.py"),
            checks=[CheckResult("Q1: Foo", "success")],
            cell_errors=0,
            tampered=["check(Q1)"],
        ),
    ]
    labels = ["Q1: Foo", "Q2: Bar"]
    marks = {"Q1": 10, "Q2": 20}

    rows = serialize_results(results, labels, marks)

    assert len(rows) == 3

    # alice: Q1 pass, Q2 fail
    assert rows[0]["notebook"] == "alice"
    assert rows[0]["checks"] == {"Q1": "PASS", "Q2": "FAIL"}
    assert rows[0]["auto_mark"] == 10
    assert rows[0]["total_mark"] == 30
    assert rows[0]["cell_errors"] == 1
    assert rows[0]["tampered"] == []

    # bob: export failure
    assert rows[1]["notebook"] == "bob"
    assert rows[1]["checks"] == {"Q1": "EXPORT_FAILED", "Q2": "EXPORT_FAILED"}
    assert rows[1]["auto_mark"] is None
    assert rows[1]["export_error"] == "timeout"

    # carol: tampered
    assert rows[2]["notebook"] == "carol"
    assert rows[2]["tampered"] == ["check(Q1)"]


def test_read_sidecar_with_weights(tmp_path):
    """JSONL with weights → CheckResult with weights."""
    import json

    sidecar = tmp_path / "sidecar.jsonl"
    record = {
        "label": "Q1: Foo",
        "status": "warn",
        "details": ["x failed"],
        "earned_weight": 3.0,
        "total_weight": 5.0,
    }
    sidecar.write_text(json.dumps(record) + "\n")

    from mograder.runner import _read_sidecar

    results = _read_sidecar(sidecar)
    assert len(results) == 1
    assert results[0].earned_weight == 3.0
    assert results[0].total_weight == 5.0


def test_read_sidecar_backward_compat(tmp_path):
    """Old JSONL without weights → defaults to 0."""
    import json

    sidecar = tmp_path / "sidecar.jsonl"
    record = {"label": "Q1: Foo", "status": "success", "details": []}
    sidecar.write_text(json.dumps(record) + "\n")

    from mograder.runner import _read_sidecar

    results = _read_sidecar(sidecar)
    assert len(results) == 1
    assert results[0].earned_weight == 0
    assert results[0].total_weight == 0


def test_compute_auto_mark_fractional():
    """Fractional auto_mark from weighted checks."""
    from mograder.runner import _compute_auto_mark

    checks = [
        CheckResult("Q1: Foo", "partial", earned_weight=3.0, total_weight=5.0),
        CheckResult("Q2: Bar", "success", earned_weight=2.0, total_weight=2.0),
    ]
    marks = {"Q1": 10, "Q2": 20}
    result = _compute_auto_mark(checks, marks)
    # Q1: round(10*3/5, 1)=6.0, Q2: round(20*2/2, 1)=20.0
    assert result == 26.0


def test_compute_auto_mark_binary_fallback():
    """When total_weight=0, falls back to binary."""
    from mograder.runner import _compute_auto_mark

    checks = [
        CheckResult("Q1: Foo", "success"),  # tw=0 → binary
        CheckResult("Q2: Bar", "danger"),  # tw=0 → binary
    ]
    marks = {"Q1": 10, "Q2": 20}
    result = _compute_auto_mark(checks, marks)
    assert result == 10.0  # Only Q1 passed


def test_serialize_results_without_marks():
    results = [
        NotebookResult(
            path=Path("alice.py"),
            checks=[CheckResult("Q1: Foo", "success")],
            cell_errors=0,
        ),
    ]
    labels = ["Q1: Foo"]
    rows = serialize_results(results, labels)

    assert len(rows) == 1
    assert "auto_mark" not in rows[0]
    assert "total_mark" not in rows[0]
    assert rows[0]["checks"] == {"Q1": "PASS"}


def test_run_notebook_isolate_cwd(tmp_path):
    """When isolate_cwd=True, the subprocess runs in a temp dir, not the notebook's parent."""
    nb = tmp_path / "student.py"
    nb.write_text("# notebook")

    captured_cwd = []

    def mock_run(cmd, **kwargs):
        captured_cwd.append(kwargs.get("cwd"))
        out_path = Path(cmd[cmd.index("-o") + 1])
        out_path.write_text(SAMPLE_HTML)
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        return result

    with patch("mograder.runner.subprocess.run", side_effect=mock_run):
        result = run_notebook(nb, timeout=60, isolate_cwd=True)

    assert result.export_ok is True
    assert len(captured_cwd) == 1
    # The cwd should NOT be the original notebook's parent
    assert captured_cwd[0] != tmp_path
    # The temp dir should have been cleaned up
    assert not captured_cwd[0].exists()


def test_run_notebook_isolate_cwd_cleanup_on_failure(tmp_path):
    """Temp dir is cleaned up even when the subprocess fails."""
    nb = tmp_path / "student.py"
    nb.write_text("# notebook")

    captured_cwd = []

    def mock_run(cmd, **kwargs):
        captured_cwd.append(kwargs.get("cwd"))
        result = MagicMock()
        result.returncode = 1
        result.stderr = "error"
        Path(cmd[cmd.index("-o") + 1]).unlink(missing_ok=True)
        return result

    with patch("mograder.runner.subprocess.run", side_effect=mock_run):
        result = run_notebook(nb, timeout=60, isolate_cwd=True)

    assert result.export_ok is False
    assert len(captured_cwd) == 1
    assert not captured_cwd[0].exists()


def test_maybe_bwrap_cmd_disabled():
    """With use_bwrap=False, command is returned unchanged."""
    from mograder.runner import _maybe_bwrap_cmd

    cmd = ["python", "-m", "marimo", "export", "html", "nb.py"]
    assert _maybe_bwrap_cmd(cmd, Path("/tmp"), False) is cmd


@pytest.mark.skipif(os.name == "nt", reason="bwrap is Unix-only")
def test_maybe_bwrap_cmd_prepended():
    """With use_bwrap=True and bwrap available, command is wrapped."""
    from mograder.runner import _maybe_bwrap_cmd

    cmd = ["python", "-m", "marimo", "export", "html", "nb.py"]
    with patch("mograder.runner.shutil.which", return_value="/usr/bin/bwrap"):
        wrapped = _maybe_bwrap_cmd(cmd, Path("/work"), True)

    assert wrapped[0] == "bwrap"
    assert "--ro-bind" in wrapped
    assert "--dev" in wrapped
    assert "--unshare-net" in wrapped
    assert "--bind" in wrapped
    idx = wrapped.index("--bind")
    assert wrapped[idx + 1] == "/work"
    assert wrapped[-len(cmd) :] == cmd


@pytest.mark.skipif(os.name == "nt", reason="bwrap is Unix-only")
def test_maybe_bwrap_cmd_ro_bind_extra():
    """Extra paths are added as --ro-bind pairs."""
    from mograder.runner import _maybe_bwrap_cmd

    cmd = ["python", "nb.py"]
    extras = [Path("/opt/venv"), Path("/home/user/.local/bin")]
    with patch("mograder.runner.shutil.which", return_value="/usr/bin/bwrap"):
        wrapped = _maybe_bwrap_cmd(cmd, Path("/work"), True, ro_bind_extra=extras)

    # Count --ro-bind occurrences: 1 for /, plus 2 extras = 3
    ro_binds = [i for i, x in enumerate(wrapped) if x == "--ro-bind"]
    assert len(ro_binds) == 3
    # The extra paths should appear (resolved — on macOS /home → /System/Volumes/Data/home)
    assert str(Path("/opt/venv").resolve()) in wrapped
    assert str(Path("/home/user/.local/bin").resolve()) in wrapped


def test_maybe_bwrap_cmd_fallback_when_missing():
    """With use_bwrap=True but bwrap not found, returns original command."""
    from mograder.runner import _maybe_bwrap_cmd

    cmd = ["python", "-m", "marimo"]
    with patch("mograder.runner.shutil.which", return_value=None):
        result = _maybe_bwrap_cmd(cmd, Path("/tmp"), True)

    assert result == cmd
