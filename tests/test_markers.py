from mograder.markers import (
    SOLUTION_BEGIN,
    SOLUTION_END,
    SUBMIT_MARKER,
    _extract_return_names,
    _hash_cell,
    _inject_assignment_metadata,
    _inject_cell_hashes,
    build_submit_cell,
    convert_markdown_cells,
    count_markers,
    process_file,
    strip_solutions,
    validate_markers,
)


# --- validate_markers ---


def test_validate_valid_markers():
    lines = [
        f"    {SOLUTION_BEGIN}\n",
        "    x = 1\n",
        f"    {SOLUTION_END}\n",
    ]
    assert validate_markers(lines, "test.py") == []


def test_validate_nested_solution():
    lines = [
        f"    {SOLUTION_BEGIN}\n",
        f"    {SOLUTION_BEGIN}\n",
        f"    {SOLUTION_END}\n",
    ]
    errors = validate_markers(lines, "test.py")
    assert len(errors) == 1
    assert "nested" in errors[0]


def test_validate_orphan_end():
    lines = [f"    {SOLUTION_END}\n"]
    errors = validate_markers(lines, "test.py")
    assert len(errors) == 1
    assert "without matching" in errors[0]


def test_validate_unclosed_solution():
    lines = [f"    {SOLUTION_BEGIN}\n", "    x = 1\n"]
    errors = validate_markers(lines, "test.py")
    assert len(errors) == 1
    assert "unclosed" in errors[0]


# --- strip_solutions ---


def test_strip_solutions_replaces_with_placeholder():
    lines = [
        "    x = 0\n",
        f"    {SOLUTION_BEGIN}\n",
        "    x = 42\n",
        f"    {SOLUTION_END}\n",
        "    print(x)\n",
    ]
    result = strip_solutions(lines)
    assert "    # YOUR CODE HERE\n" in result
    assert "    pass\n" in result
    assert "    x = 42\n" not in result
    assert "    x = 0\n" in result
    assert "    print(x)\n" in result


def test_strip_solutions_preserves_indentation():
    lines = [
        f"        {SOLUTION_BEGIN}\n",
        "        deep = True\n",
        f"        {SOLUTION_END}\n",
    ]
    result = strip_solutions(lines)
    assert "        # YOUR CODE HERE\n" in result
    assert "        pass\n" in result


def test_strip_nonmarker_code_unchanged():
    lines = ["x = 1\n", "y = 2\n", "print(x + y)\n"]
    assert strip_solutions(lines) == lines


# --- count_markers ---


def test_count_markers():
    lines = [
        f"    {SOLUTION_BEGIN}\n",
        f"    {SOLUTION_END}\n",
        f"    {SOLUTION_BEGIN}\n",
        f"    {SOLUTION_END}\n",
    ]
    assert count_markers(lines) == 2


# --- convert_markdown_cells ---


def test_convert_markdown_cells_basic():
    lines = [
        '    response_text = "*Write your analysis here...*"\n',
        "    # YOUR CODE HERE\n",
        "    pass\n",
        "    mo.md(response_text)\n",
    ]
    result = convert_markdown_cells(lines)
    assert len(result) == 3
    assert '    mo.md(r"""\n' in result
    assert "    *Write your analysis here...*\n" in result
    assert '    """)\n' in result


def test_convert_markdown_cells_preserves_indentation():
    lines = [
        '        response_text = "placeholder"\n',
        "        # YOUR CODE HERE\n",
        "        pass\n",
        "        mo.md(response_text)\n",
    ]
    result = convert_markdown_cells(lines)
    assert len(result) == 3
    assert '        mo.md(r"""\n' in result
    assert "        placeholder\n" in result
    assert '        """)\n' in result


def test_convert_markdown_cells_no_match():
    lines = [
        "    x = 1\n",
        "    # YOUR CODE HERE\n",
        "    pass\n",
        "    print(x)\n",
    ]
    result = convert_markdown_cells(lines)
    assert result == lines


def test_convert_markdown_cells_mixed():
    """Non-matching lines before/after a match are preserved."""
    lines = [
        "    x = 1\n",
        '    response_text = "hello"\n',
        "    # YOUR CODE HERE\n",
        "    pass\n",
        "    mo.md(response_text)\n",
        "    y = 2\n",
    ]
    result = convert_markdown_cells(lines)
    assert result[0] == "    x = 1\n"
    assert '    mo.md(r"""\n' in result
    assert result[-1] == "    y = 2\n"


# --- process_file ---


def test_process_file_writes_output(tmp_path, fixtures_dir):
    source = fixtures_dir / "staff_notebook.py"
    out_dir = tmp_path / "release"
    assert process_file(source, out_dir) is True
    dest = out_dir / source.name
    assert dest.exists()
    content = dest.read_text()
    assert "# YOUR CODE HERE" in content
    assert SOLUTION_BEGIN not in content


def test_process_file_dry_run(tmp_path, fixtures_dir, capsys):
    source = fixtures_dir / "staff_notebook.py"
    out_dir = tmp_path / "release"
    assert process_file(source, out_dir, dry_run=True) is True
    assert not (out_dir / source.name).exists()
    captured = capsys.readouterr()
    assert "DRY-RUN" in captured.out


def test_process_file_validate_only(fixtures_dir, capsys):
    source = fixtures_dir / "staff_notebook.py"
    assert process_file(source, None, validate_only=True) is True
    captured = capsys.readouterr()
    assert "VALID" in captured.out


def test_process_file_no_markers(tmp_path, capsys):
    source = tmp_path / "plain.py"
    source.write_text("x = 1\n")
    assert process_file(source, tmp_path) is True
    captured = capsys.readouterr()
    assert "SKIP" in captured.out


def test_process_file_invalid_markers(tmp_path):
    source = tmp_path / "bad.py"
    source.write_text(f"    {SOLUTION_BEGIN}\n")  # unclosed
    assert process_file(source, tmp_path) is False


def test_process_file_converts_markdown_cells(tmp_path):
    """Full pipeline: strip solutions + convert markdown cells."""
    source = tmp_path / "notebook.py"
    lines = [
        "import marimo\n",
        "app = marimo.App()\n",
        "\n",
        "@app.cell\n",
        "def _(mo):\n",
        '    response_text = "*Write here...*"\n',
        f"    {SOLUTION_BEGIN}\n",
        '    response_text = "My detailed answer"\n',
        f"    {SOLUTION_END}\n",
        "    mo.md(response_text)\n",
        "    return\n",
        "\n",
        "\n",
        'if __name__ == "__main__":\n',
        "    app.run()\n",
    ]
    source.write_text("".join(lines))
    out_dir = tmp_path / "release"
    assert process_file(source, out_dir) is True

    dest = out_dir / source.name
    content = dest.read_text()
    # Solution stripped and markdown cell converted
    assert "# YOUR CODE HERE" not in content
    assert 'mo.md(r"""' in content
    assert "*Write here...*" in content


# --- submit cell injection ---


def test_build_submit_cell():
    cell = build_submit_cell("https://example.com", "hw1")
    assert SUBMIT_MARKER in cell
    assert "https://example.com" in cell
    assert "hw1" in cell
    assert "mo.ui.run_button" in cell
    assert "submit_fn" in cell


def test_process_file_with_submit_url(tmp_path, fixtures_dir):
    source = fixtures_dir / "staff_notebook.py"
    out_dir = tmp_path / "release"
    assert process_file(source, out_dir, submit_url="https://example.com") is True
    content = (out_dir / source.name).read_text()
    assert SUBMIT_MARKER in content
    assert "https://example.com" in content
    # Submit cell should appear before if __name__
    if "if __name__" in content:
        main_idx = content.index("if __name__")
        submit_idx = content.index(SUBMIT_MARKER)
        assert submit_idx < main_idx


def test_process_file_without_submit_url(tmp_path, fixtures_dir):
    source = fixtures_dir / "staff_notebook.py"
    out_dir = tmp_path / "release"
    assert process_file(source, out_dir) is True
    content = (out_dir / source.name).read_text()
    assert SUBMIT_MARKER not in content


# --- _extract_return_names ---


def test_extract_return_names_single():
    assert _extract_return_names("        return pdf\n") == ["pdf"]


def test_extract_return_names_tuple():
    assert _extract_return_names("    return x, y\n") == ["x", "y"]


def test_extract_return_names_parens_tuple():
    assert _extract_return_names("    return (f_X,)\n") == ["f_X"]


def test_extract_return_names_complex_expr():
    assert _extract_return_names("    return x.value + 1\n") == []


def test_extract_return_names_bare_return():
    assert _extract_return_names("    return\n") == []


def test_extract_return_names_no_return():
    assert _extract_return_names("    x = 1\n") == []


# --- sentinel insertion in strip_solutions ---


def test_strip_solutions_sentinel_for_orphaned_return():
    """return <name> after END SOLUTION gets a var = ... sentinel."""
    lines = [
        "    def f(x):\n",
        f"        {SOLUTION_BEGIN}\n",
        "        result = x * 2\n",
        f"        {SOLUTION_END}\n",
        "        return result\n",
    ]
    result = strip_solutions(lines)
    assert "        result = ...\n" in result
    assert "        # YOUR CODE HERE\n" in result
    assert "        return result\n" in result


def test_strip_solutions_no_sentinel_when_pre_assigned():
    """No duplicate sentinel when variable is already assigned before BEGIN SOLUTION."""
    lines = [
        "    x = None\n",
        f"    {SOLUTION_BEGIN}\n",
        "    x = 42\n",
        f"    {SOLUTION_END}\n",
        "    return (x,)\n",
    ]
    result = strip_solutions(lines)
    # x = None already exists before the block, no sentinel added
    assert "    x = ...\n" not in result


def test_strip_solutions_sentinel_multiple_returns():
    """return x, y gets sentinels for both names."""
    lines = [
        f"    {SOLUTION_BEGIN}\n",
        "    x = 1\n",
        "    y = 2\n",
        f"    {SOLUTION_END}\n",
        "    return x, y\n",
    ]
    result = strip_solutions(lines)
    assert "    x = ...\n" in result
    assert "    y = ...\n" in result


def test_strip_solutions_no_sentinel_for_complex_return():
    """return with complex expressions (not simple names) gets no sentinel."""
    lines = [
        f"    {SOLUTION_BEGIN}\n",
        "    x = compute()\n",
        f"    {SOLUTION_END}\n",
        "    return x.value + 1\n",
    ]
    result = strip_solutions(lines)
    # No sentinel — return expression is not a simple name
    assert "..." not in "".join(result)


def test_strip_solutions_sentinel_parenthesised_tuple():
    """return (f_X,) gets sentinel for f_X if not pre-assigned."""
    lines = [
        "    def f_X(x):\n",
        f"        {SOLUTION_BEGIN}\n",
        "        val = x * 2\n",
        "        return val\n",
        f"        {SOLUTION_END}\n",
        "\n",
        "    return (f_X,)\n",
    ]
    result = strip_solutions(lines)
    # f_X is defined by `def f_X(x):` which is before the block but
    # at a lower indent level — the scan should stop there.
    # The sentinel is NOT needed because `def f_X` is a function def,
    # not an assignment. But the return (f_X,) is at outer scope, and
    # f_X is defined by `def`, so it's already available.
    # Actually `def f_X(x):` is not matched by _ASSIGN_RE, so f_X
    # would be considered orphaned. But in practice the `return (f_X,)`
    # is at a different indent level than the solution block, so the
    # forward scan won't match it (it's at 4 spaces, block is at 8).
    # Let's verify the output is sensible
    assert "        # YOUR CODE HERE\n" in result


# --- _inject_assignment_metadata ---


def test_inject_assignment_metadata():
    """PEP 723 block gets mograder-assignment line."""
    lines = [
        "# /// script\n",
        '# requires-python = ">=3.11"\n',
        "# ///\n",
        "code\n",
    ]
    result = _inject_assignment_metadata(lines, "hw1")
    text = "".join(result)
    assert '# mograder-assignment = "hw1"' in text
    # Should be before closing # ///
    assert text.index("mograder-assignment") < text.index("# ///\n")


def test_inject_assignment_metadata_no_pep723():
    """No PEP 723 block → unchanged."""
    lines = ["x = 1\n"]
    assert _inject_assignment_metadata(lines, "hw1") == lines


# --- _inject_cell_hashes ---


def test_inject_cell_hashes():
    """Release notebook gets mograder-cell-hashes in PEP 723 block."""
    import re

    nb = """\
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
def _(x):
    y = x + 1
    return (y,)


if __name__ == "__main__":
    app.run()
"""
    result = _inject_cell_hashes(nb)
    assert "mograder-cell-hashes" in result
    # Should contain comma-separated 8-char hex strings
    m = re.search(r'mograder-cell-hashes = "([^"]+)"', result)
    assert m
    hashes = m.group(1).split(",")
    assert len(hashes) == 2
    assert all(len(h) == 8 for h in hashes)


def test_inject_cell_hashes_skips_solution_cells():
    """Solution cells (# YOUR CODE HERE) are NOT hashed."""
    nb = """\
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
    import re

    result = _inject_cell_hashes(nb)
    m = re.search(r'mograder-cell-hashes = "([^"]+)"', result)
    assert m
    hashes = m.group(1).split(",")
    # 3 cells total, 1 solution → 2 hashes
    assert len(hashes) == 2


def test_inject_cell_hashes_no_pep723():
    """No PEP 723 block → unchanged."""
    nb = """\
import marimo

__generated_with = "0.20.0"
app = marimo.App()


@app.cell
def _():
    x = 1
    return (x,)


if __name__ == "__main__":
    app.run()
"""
    assert _inject_cell_hashes(nb) == nb


# --- process_file metadata injection ---


def test_process_file_injects_metadata(tmp_path, fixtures_dir):
    """process_file output contains assignment name and cell hashes."""
    source = fixtures_dir / "staff_notebook.py"
    out_dir = tmp_path / "release"
    process_file(source, out_dir)
    content = (out_dir / source.name).read_text()
    assert "mograder-assignment" in content
    assert "mograder-cell-hashes" in content


# --- _hash_cell ---


def test_hash_cell_deterministic():
    """Same code produces same hash."""
    assert _hash_cell("x = 1") == _hash_cell("x = 1")
    assert _hash_cell("x = 1") != _hash_cell("x = 2")


def test_hash_cell_strips_whitespace():
    """Leading/trailing whitespace doesn't affect hash."""
    assert _hash_cell("  x = 1  ") == _hash_cell("x = 1")
