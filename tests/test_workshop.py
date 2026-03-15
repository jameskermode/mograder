"""Tests for mograder.workshop — crypto, parsing, check_answer, generation."""

import json
import textwrap
from mograder.workshop import (
    build_checker_cell,
    build_exercises_cell,
    build_exercises_dict,
    check_answer,
    extract_solution_for_key,
    make_hash,
    normalize_answer,
    parse_answers_metadata,
    process_workshop,
    release_key,
    write_keys,
    xor_decrypt,
    xor_encrypt,
)


# ---------------------------------------------------------------------------
# Crypto primitives
# ---------------------------------------------------------------------------


def test_normalize_int():
    assert normalize_answer(42) == "42"


def test_normalize_float():
    assert normalize_answer(3.14) == "3.14"


def test_normalize_string():
    assert normalize_answer("hello") == '"hello"'


def test_normalize_list():
    result = normalize_answer([2.54, 0.07])
    assert json.loads(result) == [2.54, 0.07]


def test_normalize_float_tolerance():
    result = normalize_answer(3.14159265358979, tolerance=3)
    assert json.loads(result) == 3.142


def test_make_hash_deterministic():
    h1 = make_hash("42", "salt1")
    h2 = make_hash("42", "salt1")
    assert h1 == h2
    assert len(h1) == 64  # SHA256 hex digest


def test_make_hash_salt_matters():
    h1 = make_hash("42", "salt1")
    h2 = make_hash("42", "salt2")
    assert h1 != h2


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
# check_answer
# ---------------------------------------------------------------------------


def test_check_answer_correct():
    salt = "testsalt"
    answer = 42
    normalized = normalize_answer(answer)
    answer_hash = make_hash(normalized, salt)
    solution_code = "x = 42"
    encrypted = xor_encrypt(solution_code, answer_hash)

    exercises = {"Q1": {"hash": answer_hash, "solution": encrypted}}
    status, solution = check_answer("Q1", 42, exercises, {}, salt)
    assert status == "correct"
    assert solution == solution_code


def test_check_answer_wrong():
    salt = "testsalt"
    answer = 42
    normalized = normalize_answer(answer)
    answer_hash = make_hash(normalized, salt)
    encrypted = xor_encrypt("x = 42", answer_hash)

    exercises = {"Q1": {"hash": answer_hash, "solution": encrypted}}
    status, solution = check_answer("Q1", 99, exercises, {}, salt)
    assert status == "incorrect"
    assert solution is None


def test_check_answer_released():
    salt = "testsalt"
    answer = 42
    normalized = normalize_answer(answer)
    answer_hash = make_hash(normalized, salt)
    solution_code = "x = 42"
    encrypted = xor_encrypt(solution_code, answer_hash)

    exercises = {"Q1": {"hash": answer_hash, "solution": encrypted}}
    released_keys = {"Q1": normalized}
    status, solution = check_answer("Q1", 99, exercises, released_keys, salt)
    assert status == "released"
    assert solution == solution_code


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

        # === MOGRADER: ANSWERS ===
        _answers = {"Q1": [2.54, 0.07], "Q2": 42}
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


def test_parse_answers_metadata():
    lines = _SOURCE_NOTEBOOK.splitlines(keepends=True)
    answers = parse_answers_metadata(lines)
    assert answers == {"Q1": [2.54, 0.07], "Q2": 42}


def test_parse_answers_no_marker():
    lines = ["import marimo\n", "app = marimo.App()\n"]
    assert parse_answers_metadata(lines) is None


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


def test_build_exercises_cell():
    exercises = {
        "Q1": {"hash": "abc123", "solution": "encrypted_blob"},
    }
    cell = build_exercises_cell(exercises, "salt123")
    assert "EXERCISES" in cell
    assert "SALT" in cell
    assert "abc123" in cell
    assert "salt123" in cell
    # Should be valid Python-ish (contains @app.cell)
    assert "@app.cell" in cell


def test_build_checker_cell():
    cell = build_checker_cell("Q1", "Array creation")
    assert "Q1" in cell
    assert "@app.cell" in cell
    assert "check_answer" in cell
    assert "mo.stop" in cell


def test_build_exercises_dict():
    lines = _SOURCE_NOTEBOOK.splitlines(keepends=True)
    answers = {"Q1": [2.54, 0.07], "Q2": 42}
    salt = "testsalt"
    exercises = build_exercises_dict(answers, salt, lines)
    assert "Q1" in exercises
    assert "Q2" in exercises
    assert "hash" in exercises["Q1"]
    assert "solution" in exercises["Q1"]

    # Verify hash matches
    expected_hash = make_hash(normalize_answer([2.54, 0.07]), salt)
    assert exercises["Q1"]["hash"] == expected_hash


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

    # Should have checker cells
    assert "WORKSHOP CHECKER" in content or "check_answer" in content

    # Should have key fetch cell
    assert "released_keys" in content


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def test_write_keys_empty(tmp_path):
    path = tmp_path / "keys.json"
    write_keys({"Q1": 42}, "salt", path, which="empty")
    assert json.loads(path.read_text()) == {}


def test_write_keys_all(tmp_path):
    path = tmp_path / "keys.json"
    write_keys({"Q1": 42, "Q2": "hello"}, "salt", path, which="all")
    keys = json.loads(path.read_text())
    assert "Q1" in keys
    assert "Q2" in keys


def test_release_key(tmp_path):
    path = tmp_path / "keys.json"
    path.write_text("{}\n")
    release_key(path, "Q1", "42")
    keys = json.loads(path.read_text())
    assert "Q1" in keys
    assert json.loads(keys["Q1"]) == 42


def test_release_key_new_file(tmp_path):
    path = tmp_path / "keys.json"
    release_key(path, "Q1", "[2.54, 0.07]")
    keys = json.loads(path.read_text())
    assert "Q1" in keys


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
    result = runner.invoke(cli, ["workshop", "release-key", str(keys_file), "Q1", "42"])
    assert result.exit_code == 0, result.output
    keys = json.loads(keys_file.read_text())
    assert "Q1" in keys
