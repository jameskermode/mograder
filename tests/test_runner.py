import csv
import subprocess
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from mograder.models import CheckResult, NotebookResult
from mograder.runner import (
    build_zip,
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

    with patch("mograder.runner.subprocess.run", side_effect=_mock_subprocess_success(tmp_path)):
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

    with patch("mograder.runner.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 5)):
        result = run_notebook(nb, timeout=5)

    assert result.export_ok is False
    assert "timeout" in result.export_error


def test_run_notebook_saves_html(tmp_path):
    nb = tmp_path / "student.py"
    nb.write_text("# notebook")
    html_dir = tmp_path / "html"
    html_dir.mkdir()

    with patch("mograder.runner.subprocess.run", side_effect=_mock_subprocess_success(tmp_path)):
        result = run_notebook(nb, timeout=60, html_dir=html_dir)

    assert result.html_path is not None
    assert result.html_path.exists()


def test_run_batch(tmp_path):
    nbs = []
    for name in ["alice.py", "bob.py"]:
        nb = tmp_path / name
        nb.write_text("# notebook")
        nbs.append(nb)

    with patch("mograder.runner.subprocess.run", side_effect=_mock_subprocess_success(tmp_path)):
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
