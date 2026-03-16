"""Tests for mograder.workshop — crypto, parsing, reveal, generation, server."""

import json
import textwrap
import threading

from mograder.workshop import (
    build_exercises_dict,
    build_solution_cell,
    extract_solution_for_key,
    generate_dashboard_html,
    make_salt_hash,
    parse_exercises_metadata,
    process_workshop,
    release_key,
    reveal_solution,
    verify_key,
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


def test_verify_key():
    salt = "mysecret"
    h = make_salt_hash(salt)
    assert verify_key("mysecret", h)
    assert not verify_key("wrong", h)


# ---------------------------------------------------------------------------
# reveal_solution
# ---------------------------------------------------------------------------


def test_reveal_passed_with_key():
    salt = "testsalt"
    salt_hash = make_salt_hash(salt)
    solution_code = "x = 42"
    encrypted = xor_encrypt(solution_code, salt)
    exercises = {"Q1": {"solution": encrypted}}

    status, solution = reveal_solution("Q1", True, exercises, {}, salt, salt_hash)
    assert status == "passed"
    assert solution == solution_code


def test_reveal_passed_no_key():
    salt = "testsalt"
    salt_hash = make_salt_hash(salt)
    encrypted = xor_encrypt("x = 42", salt)
    exercises = {"Q1": {"solution": encrypted}}

    status, solution = reveal_solution("Q1", True, exercises, {}, "", salt_hash)
    assert status == "no_key"
    assert solution is None


def test_reveal_locked():
    salt = "testsalt"
    salt_hash = make_salt_hash(salt)
    encrypted = xor_encrypt("x = 42", salt)
    exercises = {"Q1": {"solution": encrypted}}

    status, solution = reveal_solution("Q1", False, exercises, {}, salt, salt_hash)
    assert status == "locked"
    assert solution is None


def test_reveal_released_with_salt_in_keys():
    salt = "testsalt"
    salt_hash = make_salt_hash(salt)
    solution_code = "x = 42"
    encrypted = xor_encrypt(solution_code, salt)
    exercises = {"Q1": {"solution": encrypted}}
    released_keys = {"Q1": salt}  # salt as decryption key

    status, solution = reveal_solution(
        "Q1", False, exercises, released_keys, "", salt_hash
    )
    assert status == "released"
    assert solution == solution_code


def test_reveal_unknown_exercise():
    status, solution = reveal_solution("Q99", True, {}, {}, "salt", "hash")
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
    assert "SALT_HASH" in cell
    assert "workshop_key" in cell


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

    # Should have key fetch cell and workshop key input
    assert "released_keys" in content
    assert "workshop_key" in content

    # Salt hash present, but NOT the salt itself as SALT = ...
    assert "SALT_HASH" in content
    assert "SALT =" not in content or "SALT_HASH =" in content

    # Check cells should return check_passed_<key> booleans
    assert "check_passed_Q1" in content
    assert "check_passed_Q2" in content


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def test_write_keys_empty(tmp_path):
    path = tmp_path / "keys.json"
    write_keys(["Q1", "Q2"], "salt", path, which="empty")
    assert json.loads(path.read_text()) == {}


def test_write_keys_all(tmp_path):
    path = tmp_path / "keys.json"
    write_keys(["Q1", "Q2"], "testsalt", path, which="all")
    keys = json.loads(path.read_text())
    assert keys == {"Q1": "testsalt", "Q2": "testsalt"}


def test_release_key(tmp_path):
    path = tmp_path / "keys.json"
    path.write_text("{}\n")
    release_key(path, "Q1", "mysalt")
    keys = json.loads(path.read_text())
    assert keys == {"Q1": "mysalt"}


def test_release_key_new_file(tmp_path):
    path = tmp_path / "keys.json"
    release_key(path, "Q1", "mysalt")
    keys = json.loads(path.read_text())
    assert keys == {"Q1": "mysalt"}


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
        cli,
        ["workshop", "encrypt", str(source), "-o", str(output_dir), "--salt", "abc"],
    )
    assert result.exit_code == 0, result.output
    assert (output_dir / "ws.py").exists()
    assert "Workshop key" in result.output


def test_workshop_release_key_cli(tmp_path):
    from click.testing import CliRunner

    from mograder.cli import cli

    keys_file = tmp_path / "keys.json"
    keys_file.write_text("{}\n")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["workshop", "release-key", str(keys_file), "Q1", "--salt", "mysalt"],
    )
    assert result.exit_code == 0, result.output
    keys = json.loads(keys_file.read_text())
    assert keys == {"Q1": "mysalt"}


# ---------------------------------------------------------------------------
# Dashboard HTML generation
# ---------------------------------------------------------------------------


def test_generate_dashboard_html():
    html = generate_dashboard_html(["Q1", "Q2", "Q3"], title="Test Workshop")
    assert "Test Workshop" in html
    assert "Q1" in html
    assert "Q2" in html
    assert "Q3" in html
    assert "checkbox" in html
    assert "releaseAll" in html
    assert "token=" in html


# ---------------------------------------------------------------------------
# Workshop server
# ---------------------------------------------------------------------------


def _make_workshop_server(tmp_path, secret="testsecret"):
    """Create a workshop server on a random port for testing."""
    from mograder.workshop_server import create_workshop_server

    keys_all = {"Q1": "salt1", "Q2": "salt2", "Q3": "salt3"}
    keys_path = tmp_path / "keys.json"
    keys_path.write_text("{}\n")

    # Write a minimal index.html
    (tmp_path / "index.html").write_text("<html>student notebook</html>")

    # Write dashboard.html
    dashboard_html = generate_dashboard_html(list(keys_all.keys()))
    (tmp_path / "dashboard.html").write_text(dashboard_html)

    server = create_workshop_server(
        export_dir=tmp_path,
        keys_path=keys_path,
        keys_all=keys_all,
        secret=secret,
        host="127.0.0.1",
        port=0,  # random port
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, keys_path


def test_workshop_server_exercises(tmp_path):
    import urllib.request

    server, _ = _make_workshop_server(tmp_path)
    port = server.server_address[1]
    try:
        url = f"http://127.0.0.1:{port}/workshop/exercises?token=testsecret"
        with urllib.request.urlopen(url) as resp:  # noqa: S310
            data = json.loads(resp.read())
        assert set(data["exercises"]) == {"Q1", "Q2", "Q3"}
        assert data["released"] == {"Q1": False, "Q2": False, "Q3": False}
    finally:
        server.shutdown()


def test_workshop_server_release(tmp_path):
    import urllib.request

    server, keys_path = _make_workshop_server(tmp_path)
    port = server.server_address[1]
    try:
        # Release Q1
        url = f"http://127.0.0.1:{port}/workshop/release?token=testsecret"
        body = json.dumps({"exercise": "Q1", "released": True}).encode()
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:  # noqa: S310
            data = json.loads(resp.read())
        assert data["released"]["Q1"] is True
        assert data["released"]["Q2"] is False

        # Verify keys.json on disk
        keys = json.loads(keys_path.read_text())
        assert "Q1" in keys
        assert "Q2" not in keys

        # Lock Q1
        body = json.dumps({"exercise": "Q1", "released": False}).encode()
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:  # noqa: S310
            data = json.loads(resp.read())
        assert data["released"]["Q1"] is False
    finally:
        server.shutdown()


def test_workshop_server_release_all(tmp_path):
    import urllib.request

    server, keys_path = _make_workshop_server(tmp_path)
    port = server.server_address[1]
    try:
        # Release all
        url = f"http://127.0.0.1:{port}/workshop/release-all?token=testsecret"
        body = json.dumps({"released": True}).encode()
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:  # noqa: S310
            data = json.loads(resp.read())
        assert all(data["released"].values())

        # Verify keys.json has all keys
        keys = json.loads(keys_path.read_text())
        assert set(keys.keys()) == {"Q1", "Q2", "Q3"}

        # Lock all
        body = json.dumps({"released": False}).encode()
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:  # noqa: S310
            data = json.loads(resp.read())
        assert not any(data["released"].values())
    finally:
        server.shutdown()


def test_workshop_server_auth(tmp_path):
    import urllib.error
    import urllib.request

    server, _ = _make_workshop_server(tmp_path)
    port = server.server_address[1]
    try:
        # No token → 403
        url = f"http://127.0.0.1:{port}/workshop/exercises"
        try:
            urllib.request.urlopen(url)  # noqa: S310
            assert False, "Should have raised"
        except urllib.error.HTTPError as e:
            assert e.code == 403

        # Wrong token → 403
        url = f"http://127.0.0.1:{port}/workshop/exercises?token=wrong"
        try:
            urllib.request.urlopen(url)  # noqa: S310
            assert False, "Should have raised"
        except urllib.error.HTTPError as e:
            assert e.code == 403

        # keys.json is public (no token needed)
        url = f"http://127.0.0.1:{port}/keys.json"
        with urllib.request.urlopen(url) as resp:  # noqa: S310
            data = json.loads(resp.read())
        assert data == {}
    finally:
        server.shutdown()
