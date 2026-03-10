"""Tests for mograder.auth — token generation and verification."""

from click.testing import CliRunner

from mograder.auth import (
    INSTRUCTOR_USER,
    clear_cached_https_token,
    generate_secret,
    is_instructor,
    load_cached_https_token,
    load_or_create_secret,
    make_token,
    save_cached_https_token,
    verify_token,
)
from mograder.cli import cli


class TestGenerateSecret:
    def test_length(self):
        secret = generate_secret()
        # 32 bytes = 64 hex chars
        assert len(secret) == 64

    def test_unique(self):
        assert generate_secret() != generate_secret()


class TestLoadOrCreateSecret:
    def test_creates_file(self, tmp_path):
        secret = load_or_create_secret(tmp_path)
        assert len(secret) == 64
        assert (tmp_path / ".mograder-secret").is_file()

    def test_reads_existing(self, tmp_path):
        (tmp_path / ".mograder-secret").write_text("mysecret\n")
        assert load_or_create_secret(tmp_path) == "mysecret"

    def test_idempotent(self, tmp_path):
        s1 = load_or_create_secret(tmp_path)
        s2 = load_or_create_secret(tmp_path)
        assert s1 == s2


class TestMakeAndVerifyToken:
    def test_roundtrip(self):
        secret = generate_secret()
        token = make_token(secret, "alice")
        assert verify_token(secret, token) == "alice"

    def test_wrong_secret(self):
        token = make_token("secret1", "alice")
        assert verify_token("secret2", token) is None

    def test_tampered_token(self):
        secret = generate_secret()
        token = make_token(secret, "alice")
        assert verify_token(secret, token + "x") is None

    def test_no_colon(self):
        assert verify_token("secret", "nodelimiter") is None

    def test_instructor_token(self):
        secret = generate_secret()
        token = make_token(secret, INSTRUCTOR_USER)
        user = verify_token(secret, token)
        assert user == INSTRUCTOR_USER
        assert is_instructor(user)

    def test_token_format(self):
        secret = generate_secret()
        token = make_token(secret, "bob")
        assert token.startswith("bob:")


class TestIsInstructor:
    def test_instructor(self):
        assert is_instructor(INSTRUCTOR_USER) is True

    def test_student(self):
        assert is_instructor("alice") is False


class TestHTTPSTokenCache:
    def test_save_and_load(self, tmp_path, monkeypatch):
        cache_path = tmp_path / "https_token.json"
        monkeypatch.setattr("mograder.auth.HTTPS_TOKEN_CACHE", cache_path)

        save_cached_https_token("http://example.com", "tok:abc", "alice")
        result = load_cached_https_token("http://example.com")
        assert result is not None
        assert result["token"] == "tok:abc"
        assert result["user"] == "alice"

    def test_load_wrong_url(self, tmp_path, monkeypatch):
        cache_path = tmp_path / "https_token.json"
        monkeypatch.setattr("mograder.auth.HTTPS_TOKEN_CACHE", cache_path)

        save_cached_https_token("http://example.com", "tok:abc", "alice")
        assert load_cached_https_token("http://other.com") is None

    def test_load_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("mograder.auth.HTTPS_TOKEN_CACHE", tmp_path / "nope.json")
        assert load_cached_https_token("http://x.com") is None

    def test_clear(self, tmp_path, monkeypatch):
        cache_path = tmp_path / "https_token.json"
        monkeypatch.setattr("mograder.auth.HTTPS_TOKEN_CACHE", cache_path)

        save_cached_https_token("http://example.com", "tok:abc", "alice")
        assert cache_path.is_file()
        clear_cached_https_token()
        assert not cache_path.is_file()

    def test_url_trailing_slash(self, tmp_path, monkeypatch):
        cache_path = tmp_path / "https_token.json"
        monkeypatch.setattr("mograder.auth.HTTPS_TOKEN_CACHE", cache_path)

        save_cached_https_token("http://example.com/", "tok:abc", "alice")
        assert load_cached_https_token("http://example.com") is not None


class TestTokenCommand:
    def test_with_secret_flag(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["token", "--secret", "mysecret", "alice", "bob"])
        assert result.exit_code == 0
        assert "alice: alice:" in result.output
        assert "bob: bob:" in result.output
        assert f"instructor: {INSTRUCTOR_USER}:" in result.output

    def test_instructor_always_included(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["token", "--secret", "s", "eve"])
        assert result.exit_code == 0
        lines = [line for line in result.output.strip().splitlines() if line]
        assert len(lines) == 2  # eve + instructor
        assert lines[-1].startswith("instructor:")

    def test_tokens_are_valid(self):
        secret = "testsecret"
        runner = CliRunner()
        result = runner.invoke(cli, ["token", "--secret", secret, "alice"])
        assert result.exit_code == 0
        # Extract the token from "alice: alice:<hmac>"
        token_line = result.output.strip().splitlines()[0]
        token_str = token_line.split(": ", 1)[1]
        assert verify_token(secret, token_str) == "alice"

    def test_secret_file(self, tmp_path):
        secret_file = tmp_path / "secret.txt"
        secret_file.write_text("filesecret\n")
        runner = CliRunner()
        result = runner.invoke(
            cli, ["token", "--secret-file", str(secret_file), "alice"]
        )
        assert result.exit_code == 0
        token_str = result.output.strip().splitlines()[0].split(": ", 1)[1]
        assert verify_token("filesecret", token_str) == "alice"

    def test_secret_stdin(self):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["token", "--secret-stdin", "alice"], input="stdinsecret\n"
        )
        assert result.exit_code == 0
        token_str = result.output.strip().splitlines()[0].split(": ", 1)[1]
        assert verify_token("stdinsecret", token_str) == "alice"

    def test_error_no_secret_source(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["token", "alice"])
        assert result.exit_code != 0
        assert (
            "exactly one" in result.output.lower()
            or "exactly one" in str(result.exception).lower()
        )

    def test_error_multiple_secret_sources(self, tmp_path):
        secret_file = tmp_path / "s.txt"
        secret_file.write_text("x\n")
        runner = CliRunner()
        result = runner.invoke(
            cli, ["token", "--secret", "x", "--secret-file", str(secret_file), "alice"]
        )
        assert result.exit_code != 0

    def test_error_no_usernames(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["token", "--secret", "s"])
        assert result.exit_code != 0
