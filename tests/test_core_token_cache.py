"""Tests for mograder.core._token_cache unified caching."""

import json


def test_roundtrip(tmp_path):
    from mograder.core._token_cache import TokenCache

    cache = TokenCache(tmp_path / "cache.json")
    cache.save({"url": "https://example.com", "token": "abc"})
    loaded = cache.load(match_key="url", match_value="https://example.com")
    assert loaded["token"] == "abc"


def test_load_missing_returns_none(tmp_path):
    from mograder.core._token_cache import TokenCache

    cache = TokenCache(tmp_path / "nonexistent.json")
    assert cache.load(match_key="url", match_value="x") is None


def test_load_wrong_url_returns_none(tmp_path):
    from mograder.core._token_cache import TokenCache

    cache = TokenCache(tmp_path / "cache.json")
    cache.save({"url": "https://example.com", "token": "abc"})
    assert cache.load(match_key="url", match_value="https://other.com") is None


def test_clear_removes_file(tmp_path):
    from mograder.core._token_cache import TokenCache

    p = tmp_path / "cache.json"
    cache = TokenCache(p)
    cache.save({"url": "x", "token": "y"})
    assert p.exists()
    cache.clear()
    assert not p.exists()


def test_save_strips_trailing_slash(tmp_path):
    from mograder.core._token_cache import TokenCache

    cache = TokenCache(tmp_path / "cache.json")
    cache.save({"url": "https://example.com/", "token": "abc"}, url_key="url")
    loaded = cache.load(match_key="url", match_value="https://example.com")
    assert loaded is not None


def test_file_permissions(tmp_path):
    import os
    from mograder.core._token_cache import TokenCache

    p = tmp_path / "cache.json"
    cache = TokenCache(p)
    cache.save({"url": "x", "token": "y"})
    mode = os.stat(p).st_mode & 0o777
    assert mode == 0o600


def test_corrupted_json_returns_none(tmp_path):
    from mograder.core._token_cache import TokenCache

    p = tmp_path / "cache.json"
    p.write_text("not json{{{")
    cache = TokenCache(p)
    assert cache.load(match_key="url", match_value="x") is None
