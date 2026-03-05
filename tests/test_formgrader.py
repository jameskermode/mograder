"""Tests for formgrader directory scanning and UI helpers."""

from mograder.cells import inject_grading_cells
from mograder.formgrader import (
    collect_student_marks,
    get_max_marks,
    scan_course,
    scan_submissions,
)
from mograder.models import CheckResult


def _minimal_notebook() -> str:
    return (
        "import marimo\n"
        "app = marimo.App()\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    app.run()\n"
    )


def _make_autograded(graded: bool = False, mark: int = 65) -> str:
    """Build a notebook with injected grading cells, optionally graded."""
    lines = _minimal_notebook().splitlines(keepends=True)
    checks = [CheckResult("Q1: Foo", "success")]
    injected = inject_grading_cells(lines, checks)
    text = "".join(injected)
    if graded:
        text = text.replace("_mark = None", f"_mark = {mark}")
        text = text.replace('_feedback = ""', '_feedback = "Good work"')
    return text


def _make_autograded_with_marks(graded: bool = False, manual_mark: int = 70) -> str:
    """Build a notebook with per-question marks, optionally graded."""
    lines = _minimal_notebook().splitlines(keepends=True)
    checks = [CheckResult("Q1: Computation", "success")]
    marks = {"Q1": 10, "Analysis": 90}
    injected = inject_grading_cells(lines, checks, marks=marks)
    text = "".join(injected)
    if graded:
        text = text.replace("_mark = None", f"_mark = {manual_mark}")
        text = text.replace('_feedback = ""', '_feedback = "Solid analysis"')
    return text


# --- scan_course ---


def test_scan_course_empty(tmp_path):
    result = scan_course(tmp_path)
    assert result == []


def test_scan_course_source_only(tmp_path):
    src = tmp_path / "source" / "hw1"
    src.mkdir(parents=True)
    (src / "hw1.py").write_text(_minimal_notebook())

    result = scan_course(tmp_path)
    assert len(result) == 1
    assert result[0].name == "hw1"
    assert result[0].has_source is True
    assert result[0].has_release is False
    assert result[0].num_submitted == 0


def test_scan_course_source_and_release(tmp_path):
    (tmp_path / "source" / "hw1").mkdir(parents=True)
    (tmp_path / "source" / "hw1" / "hw1.py").write_text(_minimal_notebook())
    (tmp_path / "release" / "hw1").mkdir(parents=True)
    (tmp_path / "release" / "hw1" / "hw1.py").write_text(_minimal_notebook())

    result = scan_course(tmp_path)
    assert len(result) == 1
    assert result[0].has_source is True
    assert result[0].has_release is True


def test_scan_course_full_pipeline(tmp_path):
    name = "hw1"
    # Source + release
    (tmp_path / "source" / name).mkdir(parents=True)
    (tmp_path / "source" / name / f"{name}.py").write_text(_minimal_notebook())
    (tmp_path / "release" / name).mkdir(parents=True)
    (tmp_path / "release" / name / f"{name}.py").write_text(_minimal_notebook())

    # 3 submitted
    sub_dir = tmp_path / "submitted" / name
    sub_dir.mkdir(parents=True)
    for s in ["alice", "bob", "carol"]:
        (sub_dir / f"{s}.py").write_text(_minimal_notebook())

    # 2 autograded (1 graded, 1 not)
    auto_dir = tmp_path / "autograded" / name
    auto_dir.mkdir(parents=True)
    (auto_dir / "alice.py").write_text(_make_autograded(graded=True))
    (auto_dir / "bob.py").write_text(_make_autograded(graded=False))

    # 1 feedback
    fb_dir = tmp_path / "feedback" / name
    fb_dir.mkdir(parents=True)
    (fb_dir / "alice.html").write_text("<html></html>")

    result = scan_course(tmp_path)
    assert len(result) == 1
    info = result[0]
    assert info.has_source is True
    assert info.has_release is True
    assert info.num_submitted == 3
    assert info.num_autograded == 2
    assert info.num_graded == 1
    assert info.num_feedback == 1


def test_scan_course_multiple_assignments(tmp_path):
    for name in ["hw2", "hw1", "hw3"]:
        (tmp_path / "source" / name).mkdir(parents=True)
        (tmp_path / "source" / name / f"{name}.py").write_text(_minimal_notebook())

    result = scan_course(tmp_path)
    assert len(result) == 3
    assert [a.name for a in result] == ["hw1", "hw2", "hw3"]


# --- scan_submissions ---


def test_scan_submissions_ungraded(tmp_path):
    name = "hw1"
    sub_dir = tmp_path / "submitted" / name
    sub_dir.mkdir(parents=True)
    (sub_dir / "alice.py").write_text(_minimal_notebook())

    auto_dir = tmp_path / "autograded" / name
    auto_dir.mkdir(parents=True)
    (auto_dir / "alice.py").write_text(_make_autograded(graded=False))

    result = scan_submissions(tmp_path, name)
    assert len(result) == 1
    assert result[0].student == "alice"
    assert result[0].graded is False
    assert result[0].mark is None
    assert result[0].has_grading_cells is True


def test_scan_submissions_graded(tmp_path):
    name = "hw1"
    sub_dir = tmp_path / "submitted" / name
    sub_dir.mkdir(parents=True)
    (sub_dir / "alice.py").write_text(_minimal_notebook())

    auto_dir = tmp_path / "autograded" / name
    auto_dir.mkdir(parents=True)
    (auto_dir / "alice.py").write_text(_make_autograded(graded=True, mark=72))

    result = scan_submissions(tmp_path, name)
    assert len(result) == 1
    assert result[0].graded is True
    assert result[0].mark == 72


def test_scan_submissions_graded_with_marks(tmp_path):
    """With per-question marks, total = auto + manual."""
    name = "hw1"
    auto_dir = tmp_path / "autograded" / name
    auto_dir.mkdir(parents=True)
    (auto_dir / "alice.py").write_text(
        _make_autograded_with_marks(graded=True, manual_mark=70)
    )

    result = scan_submissions(tmp_path, name)
    assert len(result) == 1
    assert result[0].graded is True
    # auto_mark = 10 (Q1 passed), manual = 70, total = 80
    assert result[0].auto_mark == 10
    assert result[0].mark == 80


def test_scan_submissions_with_feedback(tmp_path):
    name = "hw1"
    auto_dir = tmp_path / "autograded" / name
    auto_dir.mkdir(parents=True)
    (auto_dir / "alice.py").write_text(_make_autograded(graded=True))

    fb_dir = tmp_path / "feedback" / name
    fb_dir.mkdir(parents=True)
    (fb_dir / "alice.html").write_text("<html></html>")

    result = scan_submissions(tmp_path, name)
    assert len(result) == 1
    assert result[0].feedback_exported is True


def test_scan_submissions_empty(tmp_path):
    result = scan_submissions(tmp_path, "nonexistent")
    assert result == []


def test_scan_submissions_multiple_students(tmp_path):
    name = "hw1"
    auto_dir = tmp_path / "autograded" / name
    auto_dir.mkdir(parents=True)
    for s in ["carol", "alice", "bob"]:
        (auto_dir / f"{s}.py").write_text(_make_autograded(graded=False))

    result = scan_submissions(tmp_path, name)
    assert len(result) == 3
    assert [s.student for s in result] == ["alice", "bob", "carol"]


# --- formgrader app source code assertions ---


def test_app_assignments_table_has_std_column():
    """Assignments table should have Std column instead of Min/Max."""
    from pathlib import Path

    app_path = Path(__file__).parent.parent / "src" / "mograder" / "formgrader_app.py"
    source = app_path.read_text()
    assert '"Std"' in source
    assert '"Min"' not in source
    assert '"Max"' not in source


def test_app_assignments_table_has_actions_column():
    """Assignments table should combine action buttons into a single Actions column."""
    from pathlib import Path

    app_path = Path(__file__).parent.parent / "src" / "mograder" / "formgrader_app.py"
    source = app_path.read_text()
    assert '"Actions"' in source
    # Old separate columns should be gone
    assert '"Export FB"' not in source


def test_app_no_svg_histogram():
    """App should not reference svg_histogram anymore."""
    from pathlib import Path

    app_path = Path(__file__).parent.parent / "src" / "mograder" / "formgrader_app.py"
    source = app_path.read_text()
    assert "svg_histogram" not in source


# --- formgrader app action commands ---


def test_app_run_cli_captures_output():
    """_run_cli uses subprocess.run to capture output, not Popen."""
    from pathlib import Path

    app_path = Path(__file__).parent.parent / "src" / "mograder" / "formgrader_app.py"
    source = app_path.read_text()
    # _run_cli should use sp.run (blocking with capture), not sp.Popen
    assert "sp.run(" in source
    assert "capture_output=True" in source


def test_app_run_cli_does_not_use_python_m_mograder():
    """_run_cli must not use 'python -m mograder' — there is no __main__.py."""
    from pathlib import Path

    app_path = Path(__file__).parent.parent / "src" / "mograder" / "formgrader_app.py"
    source = app_path.read_text()
    assert '"-m", "mograder"' not in source


def test_app_run_cli_invokes_entry_point():
    """_run_cli should invoke the mograder CLI via its entry-point script."""
    import shutil

    # The mograder entry point must be on PATH (installed in dev mode)
    assert shutil.which("mograder") is not None


# --- collect_student_marks ---


def test_collect_student_marks_empty(tmp_path):
    """No autograded dir → empty dict."""
    from mograder.formgrader import AssignmentInfo

    assignments = [AssignmentInfo(name="hw1")]
    result = collect_student_marks(tmp_path, assignments)
    assert result == {}


def test_collect_student_marks_basic(tmp_path):
    """Two students, one graded, one not → correct marks."""
    from mograder.formgrader import AssignmentInfo

    name = "hw1"
    auto_dir = tmp_path / "autograded" / name
    auto_dir.mkdir(parents=True)
    (auto_dir / "alice.py").write_text(_make_autograded(graded=True, mark=72))
    (auto_dir / "bob.py").write_text(_make_autograded(graded=False))

    assignments = [AssignmentInfo(name=name)]
    result = collect_student_marks(tmp_path, assignments)
    assert "alice" in result
    assert result["alice"][name] == 72
    assert "bob" in result
    assert result["bob"][name] is None


def test_collect_student_marks_multiple_assignments(tmp_path):
    """Students across two assignments → correct matrix."""
    from mograder.formgrader import AssignmentInfo

    for aname in ["hw1", "hw2"]:
        auto_dir = tmp_path / "autograded" / aname
        auto_dir.mkdir(parents=True)
        (auto_dir / "alice.py").write_text(_make_autograded(graded=True, mark=80))

    # bob only in hw1
    (tmp_path / "autograded" / "hw1" / "bob.py").write_text(
        _make_autograded(graded=True, mark=60)
    )

    assignments = [AssignmentInfo(name="hw1"), AssignmentInfo(name="hw2")]
    result = collect_student_marks(tmp_path, assignments)
    assert result["alice"]["hw1"] == 80
    assert result["alice"]["hw2"] == 80
    assert result["bob"]["hw1"] == 60
    assert "hw2" not in result["bob"]


def test_collect_student_marks_with_per_question_marks(tmp_path):
    """Per-question marks: total = auto + manual."""
    from mograder.formgrader import AssignmentInfo

    name = "hw1"
    auto_dir = tmp_path / "autograded" / name
    auto_dir.mkdir(parents=True)
    (auto_dir / "alice.py").write_text(
        _make_autograded_with_marks(graded=True, manual_mark=70)
    )

    assignments = [AssignmentInfo(name=name)]
    result = collect_student_marks(tmp_path, assignments)
    # auto_mark = 10 (Q1 passed), manual = 70, total = 80
    assert result["alice"][name] == 80


# --- get_max_marks ---


def test_get_max_marks_defaults_to_100(tmp_path):
    """Assignments without source default to 100."""
    from mograder.formgrader import AssignmentInfo

    assignments = [AssignmentInfo(name="hw1")]
    result = get_max_marks(tmp_path, assignments)
    assert result == {"hw1": 100}


def test_get_max_marks_from_source(tmp_path):
    """Source with marks cell → sum of marks values."""
    from mograder.formgrader import AssignmentInfo

    src_dir = tmp_path / "source" / "hw1"
    src_dir.mkdir(parents=True)
    src_path = src_dir / "hw1.py"
    # Build a source notebook with a marks cell
    lines = _minimal_notebook().splitlines(keepends=True)
    checks = [CheckResult("Q1: Foo", "success")]
    marks = {"Q1": 10, "Analysis": 90}
    injected = inject_grading_cells(lines, checks, marks=marks)
    src_path.write_text("".join(injected))

    assignments = [AssignmentInfo(name="hw1", source_path=src_path, has_source=True)]
    result = get_max_marks(tmp_path, assignments)
    assert result == {"hw1": 100}


def test_get_max_marks_no_marks_cell(tmp_path):
    """Source without marks cell → 100."""
    from mograder.formgrader import AssignmentInfo

    src_dir = tmp_path / "source" / "hw1"
    src_dir.mkdir(parents=True)
    src_path = src_dir / "hw1.py"
    src_path.write_text(_minimal_notebook())

    assignments = [AssignmentInfo(name="hw1", source_path=src_path, has_source=True)]
    result = get_max_marks(tmp_path, assignments)
    assert result == {"hw1": 100}


def test_app_no_value_access_in_creator_cell():
    """UI elements must not have .value accessed in the cell that creates them."""
    from pathlib import Path

    app_path = Path(__file__).parent.parent / "src" / "mograder" / "formgrader_app.py"
    source = app_path.read_text()

    # Split into cells by @app.cell boundaries
    import re

    cells = re.split(r"@app\.cell", source)
    for cell in cells:
        # Find UI element creation patterns
        created = re.findall(
            r"(\w+)\s*=\s*mo\.ui\.(?:switch|file|button)\(", cell
        )
        for name in created:
            # The same cell must not access <name>.value
            assert f"{name}.value" not in cell, (
                f"Cell accesses {name}.value in the same cell that creates it"
            )


def test_app_open_marimo_passes_sandbox():
    """Source/release/edit buttons should pass --sandbox to marimo."""
    from pathlib import Path

    app_path = Path(__file__).parent.parent / "src" / "mograder" / "formgrader_app.py"
    source = app_path.read_text()
    # _open_marimo and _open_editor should use --sandbox
    assert source.count('"--sandbox"') >= 2
