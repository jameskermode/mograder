"""Tests for mograder.core._utils shared utilities."""

from pathlib import Path


def test_rel_returns_relative_string(tmp_path):
    from mograder.core._utils import rel

    p = tmp_path / "foo" / "bar.py"
    result = rel(p)
    assert isinstance(result, str)
    assert "bar.py" in result


def test_timestamp_re_matches_valid():
    from mograder.core._utils import TIMESTAMP_RE

    assert TIMESTAMP_RE.search("alice_20260310T200800")


def test_timestamp_re_rejects_plain():
    from mograder.core._utils import TIMESTAMP_RE

    assert TIMESTAMP_RE.search("alice_homework") is None


def test_cors_headers_default():
    from mograder.core._utils import cors_headers

    h = cors_headers()
    assert h["Access-Control-Allow-Origin"] == "*"
    assert "GET" in h["Access-Control-Allow-Methods"]
    assert "POST" in h["Access-Control-Allow-Methods"]


def test_cors_headers_custom_methods():
    from mograder.core._utils import cors_headers

    h = cors_headers(methods="GET, OPTIONS")
    assert "POST" not in h["Access-Control-Allow-Methods"]


def test_add_cors_starlette():
    from mograder.core._utils import add_cors_to_response

    class FakeResponse:
        def __init__(self):
            self.headers = {}

    resp = FakeResponse()
    add_cors_to_response(resp, methods="GET, OPTIONS")
    assert resp.headers["Access-Control-Allow-Origin"] == "*"
    assert "GET" in resp.headers["Access-Control-Allow-Methods"]


def test_match_dir_by_key_finds(tmp_path):
    from mograder.core._utils import match_dir_by_key

    (tmp_path / "ES98E-A1-Intro").mkdir()
    (tmp_path / "ES98E-A2-ML").mkdir()
    assert match_dir_by_key(tmp_path, "A1").name == "ES98E-A1-Intro"


def test_match_dir_by_key_not_found(tmp_path):
    from mograder.core._utils import match_dir_by_key

    (tmp_path / "ES98E-A1-Intro").mkdir()
    assert match_dir_by_key(tmp_path, "A3") is None


def test_match_dir_by_key_missing_parent(tmp_path):
    from mograder.core._utils import match_dir_by_key

    assert match_dir_by_key(tmp_path / "nonexistent", "A1") is None
