"""End-to-end integration test for the full mograder workflow.

Uses the demo-holistic example notebooks (no numpy dependency) and
the import-test Moodle CSV + ZIP fixtures.

Marked slow because autograde runs marimo export for each submission.
Run with: uv run pytest tests/test_integration.py -v
Skip in normal runs with: uv run pytest -m "not slow"
"""

import re
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from mograder.cli import cli
from mograder.moodle import extract_submissions

EXAMPLES = Path(__file__).parent.parent / "examples"
IMPORT_TEST = EXAMPLES / "import-test"
SOURCE_DIR = EXAMPLES / "source" / "demo-holistic"

# Script header pattern: strip /// script ... /// block so marimo
# does not attempt sandbox install during autograde
SCRIPT_HEADER_RE = re.compile(r"^# /// script\n(# .*\n)*# ///\n+", re.MULTILINE)


def _strip_script_header(path: Path) -> None:
    """Remove PEP 723 script header from a notebook file."""
    text = path.read_text()
    text = SCRIPT_HEADER_RE.sub("", text, count=1)
    path.write_text(text)


@pytest.fixture()
def course(tmp_path):
    """Set up a minimal course directory with source + import fixtures."""
    # Copy source notebook
    src = tmp_path / "source" / "demo-holistic"
    src.mkdir(parents=True)
    shutil.copy(SOURCE_DIR / "demo-holistic.py", src / "demo-holistic.py")
    _strip_script_header(src / "demo-holistic.py")

    # Copy import fixtures
    imp = tmp_path / "import-test"
    shutil.copytree(IMPORT_TEST, imp)

    # Relaxed rlimits for CI runners where the user may already have many
    # processes (NPROC is per-user, not per-process).
    (tmp_path / "mograder.toml").write_text(
        "[rlimits]\nnproc = 0\n"  # 0 = no limit
    )

    return tmp_path


@pytest.mark.slow
def test_full_workflow(course, monkeypatch):
    """Generate → extract → autograde → feedback → moodle, all via CLI."""
    monkeypatch.chdir(course)
    runner = CliRunner()

    csv_path = course / "import-test" / "demo-holistic.csv"
    zip_path = course / "import-test" / "demo-holistic.zip"
    source_nb = course / "source" / "demo-holistic" / "demo-holistic.py"

    # --- 1. Generate release from source ---
    result = runner.invoke(
        cli,
        [
            "generate",
            str(source_nb),
            "-o",
            str(course / "release"),
        ],
    )
    assert result.exit_code == 0, f"generate failed:\n{result.output}"
    release_nb = course / "release" / "demo-holistic" / "demo-holistic.py"
    assert release_nb.is_file()

    # --- 2. Extract submissions from Moodle ZIP ---
    sub_dir = course / "submitted" / "demo-holistic"
    sub_dir.mkdir(parents=True)
    ext_result = extract_submissions(zip_path, csv_path, sub_dir)
    assert ext_result.extracted == 6
    assert ext_result.skipped == 0
    submitted = sorted(sub_dir.glob("*.py"))
    assert len(submitted) == 6

    # Strip script headers from submitted notebooks too
    for f in submitted:
        _strip_script_header(f)

    # --- 3. Import students (directly via gradebook, replaces removed import-students CLI) ---
    from mograder import moodle
    from mograder.gradebook import Gradebook

    fieldnames, rows = moodle.read_moodle_worksheet(csv_path)
    name_mapping = {r["Username"]: r["Full name"] for r in rows if r.get("Username")}
    with Gradebook(course / "gradebook.db") as gb:
        gb.upsert_students(name_mapping)
    assert len(name_mapping) == 6

    # --- 4. Autograde ---
    sub_files = [str(f) for f in submitted]
    result = runner.invoke(
        cli,
        [
            "autograde",
            *sub_files,
            "--source",
            str(source_nb),
            "-o",
            str(course / "autograded" / "demo-holistic"),
            "--timeout",
            "120",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, f"autograde failed:\n{result.output}"

    autograded_dir = course / "autograded" / "demo-holistic"
    autograded = sorted(autograded_dir.glob("*.py"))
    assert len(autograded) == 6, (
        f"expected 6 autograded .py files, got {len(autograded)}: "
        f"{[f.name for f in autograded]}\nautograde output:\n{result.output}"
    )

    # HTML exports should also exist
    html_files = sorted(autograded_dir.glob("*.html"))
    assert len(html_files) == 6, (
        f"expected 6 HTML exports, got {len(html_files)}: "
        f"{[f.name for f in html_files]}\nautograde output:\n{result.output}"
    )

    # --- 5. Feedback ---
    ag_files = [str(f) for f in autograded]
    result = runner.invoke(
        cli,
        [
            "feedback",
            *ag_files,
            "-o",
            str(course / "feedback" / "demo-holistic"),
        ],
    )
    assert result.exit_code == 0, f"feedback failed:\n{result.output}"

    fb_dir = course / "feedback" / "demo-holistic"
    assert len(list(fb_dir.glob("*.html"))) == 6

    # --- 6. Moodle export ---
    result = runner.invoke(
        cli,
        [
            "moodle",
            "export",
            "demo-holistic",
            "--worksheet",
            str(csv_path),
            "--feedback-dir",
            str(fb_dir),
            "-o",
            str(course / "export"),
        ],
    )
    assert result.exit_code == 0, f"moodle failed:\n{result.output}"

    export_dir = course / "export"
    # Grades CSV
    assert (export_dir / "demo-holistic.csv").is_file()
    # Feedback ZIP
    feedback_zips = list(export_dir.glob("feedback_*.zip"))
    assert len(feedback_zips) == 1
