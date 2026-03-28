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
