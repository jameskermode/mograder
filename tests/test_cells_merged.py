"""Verify that all public symbols from both old markers.py and cells.py
are importable from the merged mograder.grading.cells module."""


def test_cells_has_marker_constants():
    from mograder.grading.cells import (
        SOLUTION_BEGIN,
        SOLUTION_END,
        HIDDEN_TESTS_BEGIN,
        HIDDEN_TESTS_END,
        SUBMIT_MARKER,
    )

    assert SOLUTION_BEGIN == "### BEGIN SOLUTION"
    assert SOLUTION_END == "### END SOLUTION"
    assert HIDDEN_TESTS_BEGIN == "### BEGIN HIDDEN TESTS"
    assert HIDDEN_TESTS_END == "### END HIDDEN TESTS"
    assert "SUBMIT" in SUBMIT_MARKER


def test_cells_has_grading_constants():
    from mograder.grading.cells import (
        VERIFICATION_MARKER,
        FEEDBACK_MARKER,
        MARKS_MARKER,
    )

    assert "VERIFICATION" in VERIFICATION_MARKER
    assert "FEEDBACK" in FEEDBACK_MARKER
    assert "MARKS" in MARKS_MARKER


def test_cells_has_marker_functions():
    from mograder.grading.cells import (
        validate_markers,
        strip_solutions,
        count_markers,
        count_hidden_markers,
        strip_hidden_tests,
        extract_hidden_tests,
        convert_markdown_cells,
        build_submit_cell,
        process_file,
        build_release_zip,
    )

    assert all(
        callable(f)
        for f in [
            validate_markers,
            strip_solutions,
            count_markers,
            count_hidden_markers,
            strip_hidden_tests,
            extract_hidden_tests,
            convert_markdown_cells,
            build_submit_cell,
            process_file,
            build_release_zip,
        ]
    )


def test_strip_submit_cells_removes_both_cells():
    """Strip removes the MOGRADER: SUBMIT cell and the dependent
    submit_btn-consuming cell so ``marimo export`` doesn't hang on
    ``mo.ui.run_button``."""
    from mograder.grading.cells import strip_submit_cells

    notebook = """import marimo
app = marimo.App()


@app.cell
def _():
    response = "hi"
    return (response,)


@app.cell(hide_code=True)
def _(mo):
    # === MOGRADER: SUBMIT ===
    import os as _os
    mo.stop(_os.environ.get("MOGRADER_DASHBOARD") == "1")
    submit_username = mo.ui.text(label="Username")
    submit_btn = mo.ui.run_button(label="Submit")
    mo.hstack([submit_username, submit_btn])
    return submit_btn, submit_username


@app.cell(hide_code=True)
def _(submit_btn, submit_username, mo):
    mo.stop(not submit_btn.value or not submit_username.value)
    mo.callout(mo.md("Submitted"), kind="success")
    return


if __name__ == "__main__":
    app.run()
"""
    stripped = strip_submit_cells(notebook)
    assert "MOGRADER: SUBMIT" not in stripped
    assert "run_button" not in stripped
    assert "submit_btn" not in stripped
    # Non-submit content preserved
    assert 'response = "hi"' in stripped


def test_strip_submit_cells_no_op_when_absent():
    """Returns the input unchanged when there's no submit cell."""
    from mograder.grading.cells import strip_submit_cells

    notebook = 'import marimo\napp = marimo.App()\n\n\nif __name__ == "__main__":\n    app.run()\n'
    assert strip_submit_cells(notebook) == notebook


def test_cells_has_grading_functions():
    from mograder.grading.cells import (
        extract_marking_scale,
        parse_marks_metadata,
        parse_auto_marks,
        has_grading_cells,
        inject_grading_cells,
        parse_marker_feedback,
        write_marker_feedback,
    )

    assert all(
        callable(f)
        for f in [
            extract_marking_scale,
            parse_marks_metadata,
            parse_auto_marks,
            has_grading_cells,
            inject_grading_cells,
            parse_marker_feedback,
            write_marker_feedback,
        ]
    )
