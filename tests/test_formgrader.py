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


def test_app_assignments_table_no_stats_columns():
    """Assignments table should not have Mean/Std columns; uses dropdown for selection."""
    from pathlib import Path

    app_path = Path(__file__).parent.parent / "src" / "mograder" / "formgrader_app.py"
    source = app_path.read_text()
    assert '"Mean"' not in source
    assert '"Std"' not in source
    assert "dropdown" in source


def test_app_no_svg_histogram():
    """App should not reference svg_histogram anymore."""
    from pathlib import Path

    app_path = Path(__file__).parent.parent / "src" / "mograder" / "formgrader_app.py"
    source = app_path.read_text()
    assert "svg_histogram" not in source


# --- formgrader app action commands ---


def test_app_cli_executor_captures_output():
    """The CLI executor cell uses sp.run for non-autograde and sp.Popen for autograde."""
    from pathlib import Path

    app_path = Path(__file__).parent.parent / "src" / "mograder" / "formgrader_app.py"
    source = app_path.read_text()
    assert "sp.run(" in source
    assert "capture_output=True" in source
    assert "sp.Popen(" in source


def test_app_cli_executor_does_not_use_python_m_mograder():
    """The CLI executor must not use 'python -m mograder' — there is no __main__.py."""
    from pathlib import Path

    app_path = Path(__file__).parent.parent / "src" / "mograder" / "formgrader_app.py"
    source = app_path.read_text()
    assert '"-m", "mograder"' not in source


def test_app_cli_executor_invokes_entry_point():
    """The mograder entry-point script must be installed."""
    import shutil

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
        created = re.findall(r"(\w+)\s*=\s*mo\.ui\.(?:switch|file|button)\(", cell)
        for name in created:
            # The same cell must not access <name>.value
            assert f"{name}.value" not in cell, (
                f"Cell accesses {name}.value in the same cell that creates it"
            )


def test_app_students_cell_does_not_depend_on_ui_elements():
    """Students content cell must not take show_names/moodle_file as parameters.

    If the cell both displays and depends on a UI element, interacting with
    that element re-runs the cell which re-renders it, causing marimo to
    drop the cell output.  The cell should depend only on derived data
    (name_lookup, students_controls) — not the raw UI elements.
    """
    import re
    from pathlib import Path

    app_path = Path(__file__).parent.parent / "src" / "mograder" / "formgrader_app.py"
    source = app_path.read_text()

    # Find the cell that builds students_content
    cells = re.split(r"@app\.cell", source)
    students_cell = [
        c for c in cells if "students_content" in c and "collect_student_marks" in c
    ]
    assert len(students_cell) == 1, "Expected exactly one students content cell"

    # Extract the function signature (parameter list)
    sig_match = re.search(r"def _\((.*?)\):", students_cell[0], re.DOTALL)
    assert sig_match, "Could not find cell function signature"
    params = sig_match.group(1)

    assert "show_names" not in params, (
        "students content cell should not depend on show_names directly"
    )
    assert "moodle_file" not in params, (
        "students content cell should not depend on moodle_file directly"
    )


def test_app_on_change_callbacks_do_not_block():
    """on_change callbacks must not call sp.run or _run_cli — use state to trigger a reactive cell."""
    from pathlib import Path

    app_path = Path(__file__).parent.parent / "src" / "mograder" / "formgrader_app.py"
    source = app_path.read_text()
    # on_change lambdas should set state, not call _run_cli
    assert "on_change=lambda" in source  # buttons still exist
    assert "_run_cli" not in source  # no blocking helper in callbacks
    # subprocess runs in a reactive cell triggered by pending_action state
    assert "set_pending_action" in source
    assert "get_pending_action" in source


def test_app_open_marimo_passes_sandbox():
    """Source/release/edit buttons should pass --sandbox to marimo."""
    from pathlib import Path

    app_path = Path(__file__).parent.parent / "src" / "mograder" / "formgrader_app.py"
    source = app_path.read_text()
    # _open_marimo and _open_editor should use --sandbox
    assert source.count('"--sandbox"') >= 2


def test_app_executor_uses_popen_for_autograde():
    """The executor cell uses sp.Popen + --progress for autograde commands."""
    from pathlib import Path

    app_path = Path(__file__).parent.parent / "src" / "mograder" / "formgrader_app.py"
    source = app_path.read_text()
    assert "sp.Popen(" in source
    assert '"--progress"' in source
    assert "progress_bar" in source


def test_app_executor_cell_after_layout():
    """Executor cell must come after layout cell so progress bar renders below the table."""
    from pathlib import Path

    app_path = Path(__file__).parent.parent / "src" / "mograder" / "formgrader_app.py"
    source = app_path.read_text()
    # Layout cell contains the tabs vstack; executor cell contains get_pending_action
    layout_pos = source.index("mo.ui.tabs(")
    executor_pos = source.index("get_pending_action()")
    assert layout_pos < executor_pos, (
        "executor cell must be defined after layout cell in the file"
    )


def test_app_uses_single_progress_bar():
    """Autograde uses progress_bar; other commands use spinner."""
    import re
    from pathlib import Path

    app_path = Path(__file__).parent.parent / "src" / "mograder" / "formgrader_app.py"
    source = app_path.read_text()

    # spinner is used for non-autograde commands
    assert "mo.status.spinner(" in source

    # progress_bar calls should always have a total= argument
    for m in re.finditer(r"mo\.status\.progress_bar\(([^)]*)\)", source, re.DOTALL):
        args = m.group(1)
        assert "total=" in args, (
            f"progress_bar without total= will raise ValueError: {m.group(0)}"
        )

    # sandbox_start should update with increment=0 (no visual jump)
    assert "increment=0" in source


def test_app_executor_handles_results_event():
    """The executor cell handles the 'results' event and renders a markdown table."""
    from pathlib import Path

    app_path = Path(__file__).parent.parent / "src" / "mograder" / "formgrader_app.py"
    source = app_path.read_text()
    assert '"results"' in source
    assert "_results_data" in source
    assert "_STATUS" in source
    # Should build a markdown table from results
    assert "_table_md" in source


def test_app_has_grading_tab():
    """The formgrader app should have a Grading tab."""
    from pathlib import Path

    app_path = Path(__file__).parent.parent / "src" / "mograder" / "formgrader_app.py"
    source = app_path.read_text()
    assert '"Grading"' in source
    assert "grading_content" in source


def test_scan_course_custom_dirs(tmp_path):
    """DirNames overrides hardcoded directory names."""
    from mograder.formgrader import DirNames

    # Use custom dir names
    dn = DirNames(source="src", release="rel", submitted="sub", autograded="graded")
    (tmp_path / "src" / "hw1").mkdir(parents=True)
    (tmp_path / "src" / "hw1" / "hw1.py").write_text(_minimal_notebook())
    (tmp_path / "sub" / "hw1").mkdir(parents=True)
    (tmp_path / "sub" / "hw1" / "alice.py").write_text(_minimal_notebook())

    result = scan_course(tmp_path, dir_names=dn)
    assert len(result) == 1
    assert result[0].has_source is True
    assert result[0].num_submitted == 1

    # Default dir names should find nothing
    result_default = scan_course(tmp_path)
    assert result_default == []


def test_scan_submissions_custom_dirs(tmp_path):
    """DirNames overrides hardcoded directory names in scan_submissions."""
    from mograder.formgrader import DirNames

    dn = DirNames(submitted="sub", autograded="graded", feedback="fb")
    (tmp_path / "sub" / "hw1").mkdir(parents=True)
    (tmp_path / "sub" / "hw1" / "alice.py").write_text(_minimal_notebook())
    (tmp_path / "graded" / "hw1").mkdir(parents=True)
    (tmp_path / "graded" / "hw1" / "alice.py").write_text(
        _make_autograded(graded=True, mark=80)
    )

    result = scan_submissions(tmp_path, "hw1", dir_names=dn)
    assert len(result) == 1
    assert result[0].student == "alice"
    assert result[0].mark == 80

    # Default dir names should find nothing
    result_default = scan_submissions(tmp_path, "hw1")
    assert result_default == []


def test_collect_student_marks_custom_dirs(tmp_path):
    """DirNames overrides in collect_student_marks."""
    from mograder.formgrader import AssignmentInfo, DirNames

    dn = DirNames(autograded="graded")
    name = "hw1"
    (tmp_path / "graded" / name).mkdir(parents=True)
    (tmp_path / "graded" / name / "alice.py").write_text(
        _make_autograded(graded=True, mark=72)
    )

    assignments = [AssignmentInfo(name=name)]
    result = collect_student_marks(tmp_path, assignments, dir_names=dn)
    assert result["alice"][name] == 72

    # Default dir names should find nothing
    result_default = collect_student_marks(tmp_path, assignments)
    assert result_default == {}


def test_app_progress_bar_uses_context_manager_return():
    """progress_bar.__enter__() returns a ProgressBar; update() must be called on that, not the wrapper."""
    import re
    from pathlib import Path

    app_path = Path(__file__).parent.parent / "src" / "mograder" / "formgrader_app.py"
    source = app_path.read_text()

    # Find all progress_bar context manager usages:
    # The pattern _var = mo.status.progress_bar(...) followed by _var.__enter__()
    # should capture the __enter__ return value and call .update() on it.
    # Bad:  _bar = mo.status.progress_bar(...); _bar.__enter__(); _bar.update()
    # Good: _bar = mo.status.progress_bar(...); _inner = _bar.__enter__(); _inner.update()
    #   or: with mo.status.progress_bar(...) as _bar: _bar.update()

    # Find variables assigned from progress_bar() that later call .__enter__()
    bar_vars = re.findall(r"(\w+)\s*=\s*mo\.status\.progress_bar\(", source)
    for var in bar_vars:
        # If this var calls __enter__(), the return value must be captured
        enter_pattern = rf"{re.escape(var)}\.__enter__\(\)"
        for enter_match in re.finditer(enter_pattern, source):
            # Get the line containing this __enter__ call
            line_start = source.rfind("\n", 0, enter_match.start()) + 1
            line_end = source.find("\n", enter_match.end())
            line = source[line_start:line_end].strip()
            # The __enter__ return must be assigned to a variable
            assert re.match(r"\w+\s*=\s*" + re.escape(var), line), (
                f"progress_bar.__enter__() return value not captured — "
                f".update() will fail: {line}"
            )
