"""Tests for hub CLI commands (Phase 7)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from mograder.cli import cli


def test_hub_check_reports_status(tmp_path):
    """mograder hub check exits with status output."""
    (tmp_path / "mograder.toml").write_text("")
    runner = CliRunner()
    result = runner.invoke(cli, ["hub", "check", str(tmp_path)])
    assert result.exit_code == 0
    assert "hub" in result.output.lower() or "check" in result.output.lower()


def test_hub_generate_token():
    """mograder hub generate-token prints a valid HMAC token."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["hub", "generate-token", "testuser"],
        env={"MOGRADER_HUB_SECRET": "test-secret"},
    )
    assert result.exit_code == 0
    assert "testuser:" in result.output


def test_hub_generate_token_instructor():
    """mograder hub generate-token --role instructor prints instructor token."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["hub", "generate-token", "--role", "instructor", "testuser"],
        env={"MOGRADER_HUB_SECRET": "test-secret"},
    )
    assert result.exit_code == 0
    assert "__instructor__:" in result.output


def test_hub_start_requires_secret(tmp_path):
    """mograder hub without secret fails (unless --dev)."""
    (tmp_path / "mograder.toml").write_text("")
    runner = CliRunner()
    env = {k: v for k, v in os.environ.items() if k != "MOGRADER_HUB_SECRET"}
    result = runner.invoke(
        cli,
        ["hub", "-C", str(tmp_path)],
        env=env,
    )
    assert result.exit_code != 0 or "secret" in result.output.lower()


def test_hub_warm_cache_dry_run(tmp_path):
    """mograder hub warm-cache --dry-run shows deps but doesn't invoke uv."""
    nb_file = tmp_path / "test.py"
    nb_file.write_text(
        '# /// script\n# dependencies = ["numpy"]\n# ///\nimport numpy\n'
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["hub", "warm-cache", str(nb_file), "--dry-run"],
    )
    assert result.exit_code == 0
    assert "numpy" in result.output


def test_hub_warm_cache_remote(tmp_path):
    """mograder hub warm-cache --url posts to remote hub."""
    runner = CliRunner()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "ok", "warmed": ["hw1", "hw2"]}

    with patch("requests.post", return_value=mock_resp) as mock_post:
        result = runner.invoke(
            cli,
            [
                "hub",
                "warm-cache",
                "--url",
                "http://localhost:8080",
                "--token",
                "fake-token",
            ],
        )
    assert result.exit_code == 0
    assert "Warmed 2 notebooks" in result.output
    mock_post.assert_called_once()


def _setup_publish_dir(tmp_path):
    """Create a release directory structure for publish tests."""
    release_dir = tmp_path / "release"
    assignment_dir = release_dir / "hw1"
    assignment_dir.mkdir(parents=True)
    (assignment_dir / "hw1.py").write_text("# code\n")
    (assignment_dir / "data.csv").write_text("a,b\n1,2\n")
    (tmp_path / "mograder.toml").write_text("")
    return assignment_dir


def test_hub_publish_force(tmp_path, monkeypatch):
    """mograder hub publish --force skips Moodle check and POSTs to hub."""
    _setup_publish_dir(tmp_path)
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    publish_resp = MagicMock()
    publish_resp.status_code = 200
    publish_resp.json.return_value = {"status": "ok", "files": ["data.csv", "hw1.py"]}
    warm_resp = MagicMock()
    warm_resp.status_code = 200
    warm_resp.json.return_value = {"warmed": ["hw1"]}

    with patch("requests.post", side_effect=[publish_resp, warm_resp]) as mock_post:
        result = runner.invoke(
            cli,
            [
                "hub",
                "publish",
                "hw1",
                "--url",
                "http://localhost:8080",
                "--token",
                "fake-token",
                "--force",
            ],
        )
    assert result.exit_code == 0, result.output
    assert "Published 2 files" in result.output
    # publish POST + warm-cache POST
    assert mock_post.call_count == 2
    assert "/publish/hw1" in mock_post.call_args_list[0].args[0]
    assert "/warm-cache" in mock_post.call_args_list[1].args[0]
    assert "Warmed" in result.output


def test_hub_publish_dry_run(tmp_path, monkeypatch):
    """mograder hub publish --dry-run --force does not POST."""
    _setup_publish_dir(tmp_path)
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    with patch("requests.post") as mock_post:
        result = runner.invoke(
            cli,
            ["hub", "publish", "hw1", "--force", "--dry-run"],
        )
    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    mock_post.assert_not_called()


def test_hub_publish_moodle_mismatch(tmp_path, monkeypatch):
    """mograder hub publish with Moodle mismatch exits 1."""
    _setup_publish_dir(tmp_path)
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()

    # Mock Moodle transport returning different content
    mock_transport = MagicMock()
    mock_assignment = MagicMock()
    mock_assignment.name = "hw1"
    mock_assignment.files = [
        {"filename": "hw1.py", "url": "http://moodle/hw1.py"},
    ]
    mock_transport.list_assignments.return_value = [mock_assignment]

    def mock_download(url, dest):
        dest.write_text("# DIFFERENT code\n")
        return dest

    mock_transport.download_file.side_effect = mock_download

    with patch("mograder.cli._build_moodle_transport", return_value=mock_transport):
        result = runner.invoke(
            cli,
            [
                "hub",
                "publish",
                "hw1",
                "--url",
                "http://localhost:8080",
                "--token",
                "fake-token",
            ],
        )
    assert result.exit_code == 1
    assert "FAILED" in result.output or "differs" in result.output


def test_hub_publish_moodle_match(tmp_path, monkeypatch):
    """mograder hub publish with matching Moodle files succeeds."""
    assignment_dir = _setup_publish_dir(tmp_path)
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()

    # Mock Moodle transport returning identical content
    mock_transport = MagicMock()
    mock_assignment = MagicMock()
    mock_assignment.name = "hw1"
    mock_assignment.files = [
        {"filename": "hw1.py", "url": "http://moodle/hw1.py"},
        {"filename": "data.csv", "url": "http://moodle/data.csv"},
    ]
    mock_transport.list_assignments.return_value = [mock_assignment]

    def mock_download(url, dest):
        local = assignment_dir / dest.name
        dest.write_bytes(local.read_bytes())
        return dest

    mock_transport.download_file.side_effect = mock_download

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "ok", "files": ["data.csv", "hw1.py"]}

    with (
        patch("mograder.cli._build_moodle_transport", return_value=mock_transport),
        patch("requests.post", return_value=mock_resp),
    ):
        result = runner.invoke(
            cli,
            [
                "hub",
                "publish",
                "hw1",
                "--url",
                "http://localhost:8080",
                "--token",
                "fake-token",
            ],
        )
    assert result.exit_code == 0, result.output
    assert "Moodle verification: OK" in result.output
    assert "Published 2 files" in result.output
