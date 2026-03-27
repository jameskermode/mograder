"""Tests for student_common shared helpers."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_load_student_config(tmp_path, monkeypatch):
    """load_student_config reads MOGRADER_COURSE_DIR and returns config + path."""
    from mograder.student_common import load_student_config

    # Write a minimal mograder.toml
    (tmp_path / "mograder.toml").write_text("[defaults]\nheadless_edit = true\n")
    monkeypatch.setenv("MOGRADER_COURSE_DIR", str(tmp_path))

    config, course_dir = load_student_config()
    assert course_dir == tmp_path
    assert config.headless_edit is True


def test_load_student_config_default_cwd(tmp_path, monkeypatch):
    """load_student_config defaults to cwd when env var not set."""
    from mograder.student_common import load_student_config

    (tmp_path / "mograder.toml").write_text("")
    monkeypatch.delenv("MOGRADER_COURSE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    config, course_dir = load_student_config()
    assert course_dir == tmp_path


def test_version_html_returns_string():
    """version_html returns an HTML string."""
    from mograder.student_common import version_html

    html = version_html()
    assert isinstance(html, str)
    assert "v" in html


def test_brand_logo_html_returns_string():
    """brand_logo_html returns an SVG/HTML string."""
    from mograder.student_common import brand_logo_html

    html = brand_logo_html()
    assert isinstance(html, str)


def test_hub_actions_download():
    """hub_download fetches release and uploads to notebook store."""
    import httpx
    from unittest.mock import MagicMock

    from mograder.student_common import hub_download

    # Mock httpx client
    mock_client = MagicMock(spec=httpx.Client)

    release_resp = MagicMock()
    release_resp.status_code = 200
    release_resp.content = b"# notebook content"

    upload_resp = MagicMock()
    upload_resp.status_code = 200

    mock_client.get.return_value = release_resp
    mock_client.post.return_value = upload_resp

    result = hub_download(mock_client, "user1", "A1-Test", {"X-Remote-User": "user1"})
    assert result.success is True
    assert "Downloaded" in result.message


def test_hub_actions_download_failure():
    """hub_download returns failure on bad response."""
    import httpx
    from unittest.mock import MagicMock

    from mograder.student_common import hub_download

    mock_client = MagicMock(spec=httpx.Client)
    release_resp = MagicMock()
    release_resp.status_code = 404
    release_resp.text = "Not found"
    mock_client.get.return_value = release_resp

    result = hub_download(mock_client, "user1", "A1-Test", {"X-Remote-User": "user1"})
    assert result.success is False


def test_hub_actions_validate():
    """hub_validate calls the validate endpoint."""
    import httpx
    from unittest.mock import MagicMock

    from mograder.student_common import hub_validate

    mock_client = MagicMock(spec=httpx.Client)
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "checks": [{"label": "Q1", "passed": True, "message": "ok"}]
    }
    mock_client.post.return_value = resp

    result = hub_validate(mock_client, "user1", "A1-Test", {"X-Remote-User": "user1"})
    assert result.success is True
    assert "1" in result.message  # "1/1 checks pass" or similar


def test_hub_actions_start_edit():
    """hub_start_edit calls start-edit and returns URL."""
    import httpx
    from unittest.mock import MagicMock

    from mograder.student_common import hub_start_edit

    mock_client = MagicMock(spec=httpx.Client)
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"url": "/edit/user1/A1-Test/"}
    mock_client.post.return_value = resp

    result = hub_start_edit(mock_client, "user1", "A1-Test", {"X-Remote-User": "user1"})
    assert result.success is True
    assert "edit/" in result.url
