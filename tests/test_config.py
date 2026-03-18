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
        import_dir="import",
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


def test_load_config_import_dir_default(tmp_path):
    """Missing import key uses default 'import'."""
    (tmp_path / "mograder.toml").write_text("")
    config = load_config(tmp_path)
    assert config.import_dir == "import"


def test_load_config_import_dir_custom(tmp_path):
    """[dirs] import key overrides default."""
    (tmp_path / "mograder.toml").write_text('[dirs]\nimport = "worksheets"\n')
    config = load_config(tmp_path)
    assert config.import_dir == "worksheets"


def test_config_is_frozen():
    """MograderConfig is immutable."""
    config = MograderConfig()
    try:
        config.jobs = 8  # type: ignore[misc]
        assert False, "Should have raised"
    except AttributeError:
        pass


def test_load_config_transport_default(tmp_path):
    """Default transport is moodle."""
    (tmp_path / "mograder.toml").write_text("")
    config = load_config(tmp_path)
    assert config.transport == "moodle"


def test_load_config_transport_https(tmp_path):
    """transport field is read from top-level."""
    (tmp_path / "mograder.toml").write_text(
        'transport = "https"\n\n[https]\nurl = "http://localhost:8080"\n'
    )
    config = load_config(tmp_path)
    assert config.transport == "https"
    assert config.https_url == "http://localhost:8080"


def test_load_config_top_level_assignments(tmp_path):
    """[[assignments]] is read from top-level."""
    (tmp_path / "mograder.toml").write_text(
        '[[assignments]]\nname = "HW1"\nid = "10"\n'
    )
    config = load_config(tmp_path)
    assert len(config.assignments) == 1
    assert config.assignments[0]["name"] == "HW1"


def test_load_config_assignments_fallback_to_moodle(tmp_path):
    """[[moodle.assignments]] is used when [[assignments]] is absent."""
    (tmp_path / "mograder.toml").write_text(
        '[moodle]\nurl = "https://moodle.example.com"\n\n'
        '[[moodle.assignments]]\nname = "HW2"\nid = 20\n'
    )
    config = load_config(tmp_path)
    assert len(config.assignments) == 1
    assert config.assignments[0]["name"] == "HW2"
    # moodle_assignments also populated
    assert len(config.moodle_assignments) == 1


def test_load_config_top_level_assignments_override_moodle(tmp_path):
    """[[assignments]] takes precedence over [[moodle.assignments]]."""
    (tmp_path / "mograder.toml").write_text(
        '[[assignments]]\nname = "HW1"\nid = "10"\n\n'
        '[moodle]\nurl = "https://moodle.example.com"\n\n'
        '[[moodle.assignments]]\nname = "HW2"\nid = 20\n'
    )
    config = load_config(tmp_path)
    assert len(config.assignments) == 1
    assert config.assignments[0]["name"] == "HW1"


def test_load_config_https_section(tmp_path):
    """[https] url is read."""
    (tmp_path / "mograder.toml").write_text('[https]\nurl = "http://localhost:9000"\n')
    config = load_config(tmp_path)
    assert config.https_url == "http://localhost:9000"


def test_load_config_rlimits_defaults(tmp_path):
    """Missing [rlimits] section uses defaults."""
    (tmp_path / "mograder.toml").write_text("")
    config = load_config(tmp_path)
    assert config.rlimit_cpu == 600
    assert config.rlimit_nproc == 512
    assert config.rlimit_nofile == 256


def test_load_config_rlimits_custom(tmp_path):
    """[rlimits] section overrides defaults."""
    (tmp_path / "mograder.toml").write_text(
        "[rlimits]\ncpu = 120\nnproc = 0\nnofile = 512\n"
    )
    config = load_config(tmp_path)
    assert config.rlimit_cpu == 120
    assert config.rlimit_nproc == 0
    assert config.rlimit_nofile == 512


def test_load_config_edit_links(tmp_path):
    """[edit_links] section is parsed into tuple of (name, template) pairs."""
    (tmp_path / "mograder.toml").write_text(
        "[edit_links]\n"
        'molab = "https://molab.marimo.io/new/#code/{content_lz}"\n'
        'codespaces = "https://github.com/example/codespaces"\n'
    )
    config = load_config(tmp_path)
    assert len(config.edit_links) == 2
    assert config.edit_links[0] == (
        "molab",
        "https://molab.marimo.io/new/#code/{content_lz}",
    )
    assert config.edit_links[1] == (
        "codespaces",
        "https://github.com/example/codespaces",
    )


def test_load_config_edit_links_default(tmp_path):
    """Missing [edit_links] section defaults to empty tuple."""
    (tmp_path / "mograder.toml").write_text("")
    config = load_config(tmp_path)
    assert config.edit_links == ()
