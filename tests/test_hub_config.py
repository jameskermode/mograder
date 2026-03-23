"""Tests for hub configuration and models (Phase 1)."""

from mograder.config import MograderConfig, load_config


def test_hub_config_defaults():
    """Default hub config values when no [hub] section."""
    config = MograderConfig()
    assert config.hub_port == 8080
    assert config.hub_notebooks_dir == "hub-notebooks"
    assert config.hub_release_dir == "hub-release"
    assert config.hub_session_ttl == 3600
    assert config.hub_trusted_header == "X-Remote-User"
    assert config.hub_uv_cache_dir == ""


def test_hub_config_defaults_from_file(tmp_path):
    """Loading config without [hub] section returns defaults."""
    (tmp_path / "mograder.toml").write_text("")
    config = load_config(tmp_path)
    assert config.hub_port == 8080
    assert config.hub_notebooks_dir == "hub-notebooks"
    assert config.hub_release_dir == "hub-release"
    assert config.hub_session_ttl == 3600
    assert config.hub_trusted_header == "X-Remote-User"
    assert config.hub_uv_cache_dir == ""


def test_hub_config_from_toml(tmp_path):
    """[hub] section is fully parsed from TOML."""
    (tmp_path / "mograder.toml").write_text(
        "[hub]\n"
        "port = 9090\n"
        'notebooks_dir = "student-work"\n'
        'release_dir = "releases"\n'
        "session_ttl = 7200\n"
        'trusted_header = "X-Forwarded-User"\n'
        'uv_cache_dir = "/shared/uv-cache"\n'
    )
    config = load_config(tmp_path)
    assert config.hub_port == 9090
    assert config.hub_notebooks_dir == "student-work"
    assert config.hub_release_dir == "releases"
    assert config.hub_session_ttl == 7200
    assert config.hub_trusted_header == "X-Forwarded-User"
    assert config.hub_uv_cache_dir == "/shared/uv-cache"


def test_hub_config_partial(tmp_path):
    """Partial [hub] section uses defaults for missing keys."""
    (tmp_path / "mograder.toml").write_text("[hub]\nport = 3000\nsession_ttl = 1800\n")
    config = load_config(tmp_path)
    assert config.hub_port == 3000
    assert config.hub_notebooks_dir == "hub-notebooks"  # default
    assert config.hub_release_dir == "hub-release"  # default
    assert config.hub_session_ttl == 1800
    assert config.hub_trusted_header == "X-Remote-User"  # default
    assert config.hub_uv_cache_dir == ""  # default


def test_hub_config_coexists_with_other_sections(tmp_path):
    """[hub] section coexists with other sections."""
    (tmp_path / "mograder.toml").write_text(
        "[defaults]\njobs = 8\n\n[hub]\nport = 9090\n"
    )
    config = load_config(tmp_path)
    assert config.jobs == 8
    assert config.hub_port == 9090


def test_hub_models_marimo_session():
    """MarimoSession dataclass stores session info."""
    from mograder.hub.models import MarimoSession

    session = MarimoSession(
        username="alice",
        assignment="hw1",
        port=18001,
        process=None,
        notebook_path="/tmp/alice/hw1/hw1.py",
        last_seen=1000.0,
    )
    assert session.username == "alice"
    assert session.assignment == "hw1"
    assert session.port == 18001
    assert session.process is None
    assert session.notebook_path == "/tmp/alice/hw1/hw1.py"
    assert session.last_seen == 1000.0
