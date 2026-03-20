"""Tests for hidden test markers: stripping, extraction, reinjection, and scoring."""

from mograder.markers import (
    count_hidden_markers,
    extract_hidden_tests,
    strip_hidden_tests,
    validate_markers,
)
from mograder.models import CheckResult


class TestStripHiddenTests:
    def test_basic_strip(self):
        lines = [
            "    check('Q1', [...])\n",
            "    ### BEGIN HIDDEN TESTS\n",
            "    check('Q1: Edge', [...])\n",
            "    ### END HIDDEN TESTS\n",
            "    return\n",
        ]
        result = strip_hidden_tests(lines)
        assert len(result) == 3
        assert result[0] == "    check('Q1', [...])\n"
        assert result[1] == "    # HIDDEN TESTS\n"
        assert result[2] == "    return\n"

    def test_preserves_indentation(self):
        lines = [
            "        ### BEGIN HIDDEN TESTS\n",
            "        check('Q1', [])\n",
            "        ### END HIDDEN TESTS\n",
        ]
        result = strip_hidden_tests(lines)
        assert result == ["        # HIDDEN TESTS\n"]

    def test_no_hidden_tests(self):
        lines = ["    check('Q1', [...])\n", "    return\n"]
        result = strip_hidden_tests(lines)
        assert result == lines

    def test_multiple_blocks(self):
        lines = [
            "    check('Q1', [])\n",
            "    ### BEGIN HIDDEN TESTS\n",
            "    check('Q1: Hidden', [])\n",
            "    ### END HIDDEN TESTS\n",
            "    check('Q2', [])\n",
            "    ### BEGIN HIDDEN TESTS\n",
            "    check('Q2: Hidden', [])\n",
            "    ### END HIDDEN TESTS\n",
        ]
        result = strip_hidden_tests(lines)
        assert len(result) == 4
        assert "# HIDDEN TESTS" in result[1]
        assert "# HIDDEN TESTS" in result[3]


class TestExtractHiddenTests:
    def test_extract_single_block(self):
        lines = [
            "    ### BEGIN HIDDEN TESTS\n",
            "    check('Q1: Edge', [...])\n",
            "    ### END HIDDEN TESTS\n",
        ]
        blocks = extract_hidden_tests(lines)
        assert len(blocks) == 1
        indent, block_lines = blocks[0]
        assert indent == "    "
        assert len(block_lines) == 1
        assert "check('Q1: Edge'" in block_lines[0]

    def test_extract_multiple_blocks(self):
        lines = [
            "    ### BEGIN HIDDEN TESTS\n",
            "    check('Q1: H', [])\n",
            "    ### END HIDDEN TESTS\n",
            "    ### BEGIN HIDDEN TESTS\n",
            "    check('Q2: H', [])\n",
            "    check('Q2: H2', [])\n",
            "    ### END HIDDEN TESTS\n",
        ]
        blocks = extract_hidden_tests(lines)
        assert len(blocks) == 2
        assert len(blocks[1][1]) == 2

    def test_no_blocks(self):
        lines = ["    check('Q1', [])\n"]
        assert extract_hidden_tests(lines) == []


class TestValidateMarkers:
    def test_valid_hidden_and_solution(self):
        lines = [
            "### BEGIN SOLUTION\n",
            "x = 1\n",
            "### END SOLUTION\n",
            "### BEGIN HIDDEN TESTS\n",
            "check('Q1', [])\n",
            "### END HIDDEN TESTS\n",
        ]
        errors = validate_markers(lines, "test.py")
        assert errors == []

    def test_nested_hidden_in_solution(self):
        lines = [
            "### BEGIN SOLUTION\n",
            "### BEGIN HIDDEN TESTS\n",
            "### END HIDDEN TESTS\n",
            "### END SOLUTION\n",
        ]
        errors = validate_markers(lines, "test.py")
        assert any("inside solution block" in e for e in errors)

    def test_nested_solution_in_hidden(self):
        lines = [
            "### BEGIN HIDDEN TESTS\n",
            "### BEGIN SOLUTION\n",
            "### END SOLUTION\n",
            "### END HIDDEN TESTS\n",
        ]
        errors = validate_markers(lines, "test.py")
        assert any("inside hidden tests block" in e for e in errors)

    def test_unclosed_hidden(self):
        lines = ["### BEGIN HIDDEN TESTS\n", "check()\n"]
        errors = validate_markers(lines, "test.py")
        assert any("unclosed" in e for e in errors)

    def test_unmatched_end_hidden(self):
        lines = ["### END HIDDEN TESTS\n"]
        errors = validate_markers(lines, "test.py")
        assert any("without matching" in e for e in errors)


class TestCountHiddenMarkers:
    def test_count(self):
        lines = [
            "### BEGIN HIDDEN TESTS\n",
            "### END HIDDEN TESTS\n",
            "### BEGIN HIDDEN TESTS\n",
            "### END HIDDEN TESTS\n",
        ]
        assert count_hidden_markers(lines) == 2

    def test_zero(self):
        assert count_hidden_markers(["pass\n"]) == 0


class TestCheckResultHiddenFlag:
    def test_default_false(self):
        cr = CheckResult(label="Q1", status="success")
        assert cr.hidden is False

    def test_set_true(self):
        cr = CheckResult(label="Q1", status="success", hidden=True)
        assert cr.hidden is True
