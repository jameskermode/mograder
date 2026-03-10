"""Tests for mograder.auth — token generation and verification."""

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
