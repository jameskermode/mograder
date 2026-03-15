"""TOML configuration file support for mograder."""

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MograderConfig:
    """Configuration loaded from ``mograder.toml``."""

    # top-level
    transport: str = "moodle"
    config_url: str | None = None
    # [[assignments]] — transport-agnostic assignment list
    assignments: tuple[dict, ...] = ()
    # [moodle]
    moodle_csv: str | None = None
    moodle_match_column: str = "Username"
    moodle_name_column: str = "Full name"
    moodle_url: str | None = None
    moodle_course_id: int | None = None
    moodle_assignments: tuple[dict, ...] = ()
    # [https]
    https_url: str | None = None
    https_token: str | None = None
    # [defaults]
    jobs: int = 4
    timeout: int = 300
    no_edit: bool = False
    no_actions: bool = False
    headless_edit: bool = False
    # [rlimits] — resource caps for notebook subprocesses (0 = no limit)
    rlimit_cpu: int = 600  # seconds
    rlimit_nproc: int = 64  # total user processes
    rlimit_nofile: int = 256  # open file descriptors
    # [dirs]
    source_dir: str = "source"
    release_dir: str = "release"
    submitted_dir: str = "submitted"
    autograded_dir: str = "autograded"
    feedback_dir: str = "feedback"
    import_dir: str = "import"
    # [gradebook]
    gradebook: str = "gradebook.db"
    # [sync]
    sync_remote: str | None = None
    sync_remote_course_dir: str | None = None
    sync_remote_venv_dir: str | None = None
    # [edit_links]
    edit_links: tuple[tuple[str, str], ...] = ()


DEFAULT_CONFIG = MograderConfig()


def load_config(course_dir: Path) -> MograderConfig:
    """Load ``mograder.toml`` from *course_dir*. Returns defaults if missing."""
    config_path = course_dir / "mograder.toml"
    if not config_path.is_file():
        return DEFAULT_CONFIG
    with open(config_path, "rb") as f:
        data = tomllib.load(f)
    moodle = data.get("moodle", {})
    https = data.get("https", {})
    defaults = data.get("defaults", {})
    dirs = data.get("dirs", {})
    gradebook = data.get("gradebook", {})
    rlimits = data.get("rlimits", {})
    sync = data.get("sync", {})
    edit_links_data = data.get("edit_links", {})

    # [[assignments]] with fallback to [[moodle.assignments]]
    top_assignments = tuple(data.get("assignments", []))
    moodle_assignments = tuple(moodle.get("assignments", []))
    assignments = top_assignments if top_assignments else moodle_assignments

    return MograderConfig(
        transport=data.get("transport", "moodle"),
        config_url=data.get("config_url"),
        assignments=assignments,
        moodle_csv=moodle.get("csv"),
        moodle_match_column=moodle.get("match_column", "Username"),
        moodle_name_column=moodle.get("name_column", "Full name"),
        moodle_url=moodle.get("url"),
        moodle_course_id=moodle.get("course_id"),
        moodle_assignments=moodle_assignments,
        https_url=https.get("url"),
        https_token=https.get("token"),
        jobs=defaults.get("jobs", 4),
        timeout=defaults.get("timeout", 300),
        no_edit=defaults.get("no_edit", defaults.get("headless", False)),
        no_actions=defaults.get("no_actions", defaults.get("headless", False)),
        headless_edit=defaults.get("headless_edit", False),
        rlimit_cpu=rlimits.get("cpu", 600),
        rlimit_nproc=rlimits.get("nproc", 64),
        rlimit_nofile=rlimits.get("nofile", 256),
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
        edit_links=tuple((k, v) for k, v in edit_links_data.items()),
    )
