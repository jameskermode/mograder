"""Tests for mograder.workshop — crypto, parsing, reveal, generation."""

import json
import textwrap

from mograder.workshop import (
    build_exercises_dict,
    build_solution_cell,
    extract_solution_for_key,
    parse_exercises_metadata,
    process_workshop,
    release_key,
    reveal_solution,
    write_keys,
    xor_decrypt,
    xor_encrypt,
)


# ---------------------------------------------------------------------------
# Crypto primitives
# ---------------------------------------------------------------------------


def test_xor_roundtrip():
    plaintext = "x = np.linspace(0, 2 * np.pi, 50)"
    key = "somekey"
    encrypted = xor_encrypt(plaintext, key)
    assert encrypted != plaintext
    decrypted = xor_decrypt(encrypted, key)
    assert decrypted == plaintext


def test_xor_roundtrip_unicode():
    plaintext = "résultat = π * r²"
    key = "clé"
    encrypted = xor_encrypt(plaintext, key)
    decrypted = xor_decrypt(encrypted, key)
    assert decrypted == plaintext


def test_xor_empty():
    assert xor_encrypt("", "key") == ""


# ---------------------------------------------------------------------------
# reveal_solution
# ---------------------------------------------------------------------------


def test_reveal_passed():
    salt = "testsalt"
    solution_code = "x = 42"
    encrypted = xor_encrypt(solution_code, salt)
    exercises = {"Q1": {"solution": encrypted}}

    status, solution = reveal_solution("Q1", True, exercises, {}, salt)
    assert status == "passed"
    assert solution == solution_code


def test_reveal_locked():
    salt = "testsalt"
    encrypted = xor_encrypt("x = 42", salt)
    exercises = {"Q1": {"solution": encrypted}}

    status, solution = reveal_solution("Q1", False, exercises, {}, salt)
    assert status == "locked"
    assert solution is None


def test_reveal_released():
    salt = "testsalt"
    solution_code = "x = 42"
    encrypted = xor_encrypt(solution_code, salt)
    exercises = {"Q1": {"solution": encrypted}}
    released_keys = {"Q1": True}

    status, solution = reveal_solution("Q1", False, exercises, released_keys, salt)
    assert status == "released"
    assert solution == solution_code


def test_reveal_unknown_exercise():
    status, solution = reveal_solution("Q99", True, {}, {}, "salt")
    assert status == "locked"
    assert solution is None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_SOURCE_NOTEBOOK = textwrap.dedent("""\
    import marimo
    app = marimo.App()

    @app.cell(hide_code=True)
    def _():
        import marimo as mo
        from mograder.runtime import check

        # === MOGRADER: EXERCISES ===
        _exercises = ["Q1", "Q2"]
        return check, mo

    @app.cell
    def _(np):
        x = None
        ### BEGIN SOLUTION
        x = np.linspace(0, 2 * np.pi, 50)
        ### END SOLUTION
        return (x,)

    @app.cell(hide_code=True)
    def _(check, x):
        check("Q1: Array creation", [
            (x is not None, "x should not be None"),
        ])
        return

    @app.cell
    def _():
        answer = None
        ### BEGIN SOLUTION
        answer = 42
        ### END SOLUTION
        return (answer,)

    @app.cell(hide_code=True)
    def _(check, answer):
        check("Q2: The answer", [
            (answer == 42, "answer should be 42"),
        ])
        return

    if __name__ == "__main__":
        app.run()
""")


def test_parse_exercises_metadata():
    lines = _SOURCE_NOTEBOOK.splitlines(keepends=True)
    exercises = parse_exercises_metadata(lines)
    assert exercises == ["Q1", "Q2"]


def test_parse_exercises_no_marker():
    lines = ["import marimo\n", "app = marimo.App()\n"]
    assert parse_exercises_metadata(lines) is None


def test_extract_solution_for_key():
    lines = _SOURCE_NOTEBOOK.splitlines(keepends=True)
    sol = extract_solution_for_key(lines, "Q1")
    assert sol is not None
    assert "np.linspace" in sol


def test_extract_solution_for_key_q2():
    lines = _SOURCE_NOTEBOOK.splitlines(keepends=True)
    sol = extract_solution_for_key(lines, "Q2")
    assert sol is not None
    assert "answer = 42" in sol


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def test_build_exercises_dict():
    lines = _SOURCE_NOTEBOOK.splitlines(keepends=True)
    salt = "testsalt"
    exercises = build_exercises_dict(["Q1", "Q2"], salt, lines)
    assert "Q1" in exercises
    assert "Q2" in exercises
    assert "solution" in exercises["Q1"]

    # Verify roundtrip
    sol = xor_decrypt(exercises["Q1"]["solution"], salt)
    assert "np.linspace" in sol


def test_build_solution_cell():
    cell = build_solution_cell("Q1")
    assert "Q1" in cell
    assert "@app.cell" in cell
    assert "reveal_solution" in cell
    assert "WORKSHOP SOLUTION" in cell


def test_process_workshop_e2e(tmp_path):
    source = tmp_path / "source" / "workshop" / "workshop.py"
    source.parent.mkdir(parents=True)
    source.write_text(_SOURCE_NOTEBOOK)

    output_dir = tmp_path / "release" / "workshop"
    result = process_workshop(source, output_dir, salt="test123")

    assert result.exists()
    content = result.read_text()

    # Solutions should be stripped
    assert "### BEGIN SOLUTION" not in content
    assert "# YOUR CODE HERE" in content

    # Should have solution reveal cells
    assert "reveal_solution" in content

    # Should have key fetch cell
    assert "released_keys" in content

    # Check cells should return check_passed_<key> booleans
    assert "check_passed_Q1" in content
    assert "check_passed_Q2" in content


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def test_write_keys_empty(tmp_path):
    path = tmp_path / "keys.json"
    write_keys(["Q1", "Q2"], path, which="empty")
    assert json.loads(path.read_text()) == {}


def test_write_keys_all(tmp_path):
    path = tmp_path / "keys.json"
    write_keys(["Q1", "Q2"], path, which="all")
    keys = json.loads(path.read_text())
    assert keys == {"Q1": True, "Q2": True}


def test_release_key(tmp_path):
    path = tmp_path / "keys.json"
    path.write_text("{}\n")
    release_key(path, "Q1")
    keys = json.loads(path.read_text())
    assert keys == {"Q1": True}


def test_release_key_new_file(tmp_path):
    path = tmp_path / "keys.json"
    release_key(path, "Q1")
    keys = json.loads(path.read_text())
    assert keys == {"Q1": True}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_workshop_encrypt_cli(tmp_path):
    from click.testing import CliRunner

    from mograder.cli import cli

    source = tmp_path / "source" / "ws" / "ws.py"
    source.parent.mkdir(parents=True)
    source.write_text(_SOURCE_NOTEBOOK)

    output_dir = tmp_path / "release" / "ws"
    runner = CliRunner()
    result = runner.invoke(
        cli, ["workshop", "encrypt", str(source), "-o", str(output_dir)]
    )
    assert result.exit_code == 0, result.output
    assert (output_dir / "ws.py").exists()


def test_workshop_release_key_cli(tmp_path):
    from click.testing import CliRunner

    from mograder.cli import cli

    keys_file = tmp_path / "keys.json"
    keys_file.write_text("{}\n")

    runner = CliRunner()
    result = runner.invoke(cli, ["workshop", "release-key", str(keys_file), "Q1"])
    assert result.exit_code == 0, result.output
    keys = json.loads(keys_file.read_text())
    assert keys == {"Q1": True}
