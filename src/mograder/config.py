"""TOML configuration file support for mograder."""

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MograderConfig:
    """Configuration loaded from ``mograder.toml``."""

    # [moodle]
    moodle_csv: str | None = None
    moodle_match_column: str = "Username"
    moodle_name_column: str = "Full name"
    moodle_url: str | None = None
    moodle_course_id: int | None = None
    moodle_assignments: tuple[dict, ...] = ()
    # [defaults]
    jobs: int = 4
    timeout: int = 300
    headless: bool = False
    # [dirs]
    source_dir: str = "source"
    release_dir: str = "release"
    submitted_dir: str = "submitted"
    autograded_dir: str = "autograded"
    feedback_dir: str = "feedback"
    import_dir: str = "import"
    # [gradebook]
    gradebook: str = "gradebook.db"
    # top-level
    config_url: str | None = None
    # [sync]
    sync_remote: str | None = None
    sync_remote_course_dir: str | None = None
    sync_remote_venv_dir: str | None = None


DEFAULT_CONFIG = MograderConfig()


def load_config(course_dir: Path) -> MograderConfig:
    """Load ``mograder.toml`` from *course_dir*. Returns defaults if missing."""
    config_path = course_dir / "mograder.toml"
    if not config_path.is_file():
        return DEFAULT_CONFIG
    with open(config_path, "rb") as f:
        data = tomllib.load(f)
    moodle = data.get("moodle", {})
    defaults = data.get("defaults", {})
    dirs = data.get("dirs", {})
    gradebook = data.get("gradebook", {})
    sync = data.get("sync", {})
    return MograderConfig(
        config_url=data.get("config_url"),
        moodle_csv=moodle.get("csv"),
        moodle_match_column=moodle.get("match_column", "Username"),
        moodle_name_column=moodle.get("name_column", "Full name"),
        moodle_url=moodle.get("url"),
        moodle_course_id=moodle.get("course_id"),
        moodle_assignments=tuple(moodle.get("assignments", [])),
        jobs=defaults.get("jobs", 4),
        timeout=defaults.get("timeout", 300),
        headless=defaults.get("headless", False),
        source_dir=dirs.get("source", "source"),
        release_dir=dirs.get("release", "release"),
        submitted_dir=dirs.get("submitted", "submitted"),
        autograded_dir=dirs.get("autograded", "autograded"),
        feedback_dir=dirs.get("feedback", "feedback"),
        import_dir=dirs.get("import", "import"),
        gradebook=gradebook.get("path", "gradebook.db"),
        sync_remote=sync.get("remote"),
        sync_remote_course_dir=sync.get("remote_course_dir"),
        sync_remote_venv_dir=sync.get("remote_venv_dir"),
    )
