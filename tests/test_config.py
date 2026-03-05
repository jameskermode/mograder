"""Tests for mograder.config — TOML configuration loading."""

from mograder.config import DEFAULT_CONFIG, MograderConfig, load_config


def test_load_config_no_file(tmp_path):
    """Missing mograder.toml returns DEFAULT_CONFIG."""
    config = load_config(tmp_path)
    assert config == DEFAULT_CONFIG


def test_load_config_empty_file(tmp_path):
    """Empty mograder.toml returns all defaults."""
    (tmp_path / "mograder.toml").write_text("")
    config = load_config(tmp_path)
    assert config == DEFAULT_CONFIG


def test_load_config_partial_moodle_only(tmp_path):
    """Only [moodle] section; rest defaults."""
    (tmp_path / "mograder.toml").write_text(
        '[moodle]\ncsv = "grading.csv"\nmatch_column = "ID number"\n'
    )
    config = load_config(tmp_path)
    assert config.moodle_csv == "grading.csv"
    assert config.moodle_match_column == "ID number"
    assert config.moodle_name_column == "Full name"
    assert config.jobs == 4
    assert config.timeout == 300
    assert config.source_dir == "source"


def test_load_config_partial_defaults_only(tmp_path):
    """Only [defaults] section."""
    (tmp_path / "mograder.toml").write_text("[defaults]\njobs = 8\ntimeout = 600\n")
    config = load_config(tmp_path)
    assert config.jobs == 8
    assert config.timeout == 600
    assert config.moodle_csv is None
    assert config.source_dir == "source"


def test_load_config_partial_dirs_only(tmp_path):
    """Only [dirs] section."""
    (tmp_path / "mograder.toml").write_text(
        '[dirs]\nsource = "src"\nautograded = "graded"\n'
    )
    config = load_config(tmp_path)
    assert config.source_dir == "src"
    assert config.autograded_dir == "graded"
    assert config.release_dir == "release"
    assert config.submitted_dir == "submitted"
    assert config.feedback_dir == "feedback"


def test_load_config_full(tmp_path):
    """All sections populated."""
    (tmp_path / "mograder.toml").write_text(
        '[moodle]\ncsv = "moodle.csv"\nmatch_column = "Email"\n'
        'name_column = "Display name"\n\n'
        "[defaults]\njobs = 2\ntimeout = 120\n\n"
        '[dirs]\nsource = "src"\nrelease = "rel"\n'
        'submitted = "sub"\nautograded = "auto"\nfeedback = "fb"\n'
    )
    config = load_config(tmp_path)
    assert config == MograderConfig(
        moodle_csv="moodle.csv",
        moodle_match_column="Email",
        moodle_name_column="Display name",
        jobs=2,
        timeout=120,
        source_dir="src",
        release_dir="rel",
        submitted_dir="sub",
        autograded_dir="auto",
        feedback_dir="fb",
    )


def test_load_config_unknown_keys_ignored(tmp_path):
    """Unknown keys in TOML are silently ignored (forward compat)."""
    (tmp_path / "mograder.toml").write_text(
        '[moodle]\ncsv = "grades.csv"\nfuture_key = true\n\n'
        "[unknown_section]\nfoo = 42\n"
    )
    config = load_config(tmp_path)
    assert config.moodle_csv == "grades.csv"
    assert config.jobs == 4  # default


def test_load_config_gradebook(tmp_path):
    """[gradebook] section sets path."""
    (tmp_path / "mograder.toml").write_text('[gradebook]\npath = "grades.db"\n')
    config = load_config(tmp_path)
    assert config.gradebook == "grades.db"


def test_load_config_gradebook_default(tmp_path):
    """Missing [gradebook] section uses default."""
    (tmp_path / "mograder.toml").write_text("")
    config = load_config(tmp_path)
    assert config.gradebook == "gradebook.db"


def test_config_is_frozen():
    """MograderConfig is immutable."""
    config = MograderConfig()
    try:
        config.jobs = 8  # type: ignore[misc]
        assert False, "Should have raised"
    except AttributeError:
        pass
