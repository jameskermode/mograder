"""Version checking, update detection, and upgrade hints."""

from __future__ import annotations

import importlib.metadata
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

_logger = logging.getLogger(__name__)

_CONFIG_DIR = Path.home() / ".config" / "mograder"
_UPDATE_CHECK_FILE = _CONFIG_DIR / "update_check.json"
_CHECK_INTERVAL_HOURS = 24


def get_version() -> str:
    """Return the installed mograder version."""
    return importlib.metadata.version("mograder")


def is_editable_install() -> bool:
    """Return True if mograder is installed in editable/dev mode."""
    try:
        dist = importlib.metadata.distribution("mograder")
        for f in dist.files or []:
            if f.name == "direct_url.json":
                data = json.loads(dist.locate_file(f).read_text())
                return data.get("dir_info", {}).get("editable", False)
    except Exception:
        pass
    return False


def get_version_info() -> str:
    """Return a version string, including git SHA for editable installs."""
    version = get_version()
    if not is_editable_install():
        return version
    try:
        dist = importlib.metadata.distribution("mograder")
        for f in dist.files or []:
            if f.name == "direct_url.json":
                data = json.loads(dist.locate_file(f).read_text())
                src_dir = data.get("url", "").removeprefix("file://")
                if src_dir:
                    result = subprocess.run(
                        ["git", "rev-parse", "--short", "HEAD"],
                        capture_output=True,
                        text=True,
                        cwd=src_dir,
                        timeout=5,
                    )
                    if result.returncode == 0:
                        sha = result.stdout.strip()
                        return f"{version} (dev, {sha})"
    except Exception:
        pass
    return f"{version} (dev)"


def check_latest_version() -> str | None:
    """Query PyPI for the latest mograder version. Returns None on failure."""
    try:
        with urlopen("https://pypi.org/pypi/mograder/json", timeout=3) as resp:
            return json.loads(resp.read().decode())["info"]["version"]
    except Exception:
        _logger.debug("Failed to check PyPI for latest version", exc_info=True)
        return None


def is_newer(latest: str, current: str) -> bool:
    """Return True if *latest* is a newer version than *current*."""
    try:
        return tuple(int(x) for x in latest.split(".")) > tuple(
            int(x) for x in current.split(".")
        )
    except (ValueError, TypeError):
        return False


def suggest_upgrade_cmd() -> str:
    """Suggest the right upgrade command based on how mograder was installed."""
    exe = sys.executable
    # uvx tool installs live under .cache/uv/tools/ or similar
    if "/uv/tools/" in exe or "\\uv\\tools\\" in exe:
        return "uvx --refresh mograder"
    # uv project context
    if os.environ.get("UV"):
        if Path("uv.lock").exists():
            return "uv add --upgrade mograder"
        return "uv pip install --upgrade mograder"
    return "pip install --upgrade mograder"


def version_html() -> str:
    """Return an HTML snippet showing the current version and update availability."""
    current = get_version()
    latest = check_latest_version()
    if latest and is_newer(latest, current):
        return (
            f'<span style="font-size:0.8em;color:var(--text-secondary,#666)">'
            f"v{current}"
            f'</span> <a href="https://pypi.org/project/mograder/{latest}/" '
            f'target="_blank" style="font-size:0.75em;color:#e67e22;'
            f"text-decoration:none;border:1px solid #e67e22;border-radius:4px;"
            f'padding:1px 6px;margin-left:4px" '
            f'title="Run: {suggest_upgrade_cmd()}">'
            f"update: v{latest}</a>"
        )
    return (
        f'<span style="font-size:0.8em;color:var(--text-secondary,#666)">'
        f"v{current}</span>"
    )


def check_for_update() -> None:
    """Check PyPI for updates and print a message if one is available.

    Rate-limited to once per day. Skipped for editable installs.
    Never raises — all errors are silently logged.
    """
    try:
        if is_editable_install():
            return

        # Rate limit: check at most once per day
        now = datetime.now(timezone.utc)
        if _UPDATE_CHECK_FILE.is_file():
            try:
                state = json.loads(_UPDATE_CHECK_FILE.read_text())
                last = datetime.fromisoformat(state["last_checked"])
                hours = (now - last).total_seconds() / 3600
                if hours < _CHECK_INTERVAL_HOURS:
                    # Use cached result
                    cached_latest = state.get("latest")
                    if cached_latest and is_newer(cached_latest, get_version()):
                        _print_update_message(get_version(), cached_latest)
                    return
            except Exception:
                pass

        latest = check_latest_version()
        if latest is None:
            return

        # Save state
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _UPDATE_CHECK_FILE.write_text(
            json.dumps({"last_checked": now.isoformat(), "latest": latest})
        )

        if is_newer(latest, get_version()):
            _print_update_message(get_version(), latest)
    except Exception:
        _logger.debug("Update check failed", exc_info=True)


def _print_update_message(current: str, latest: str) -> None:
    """Print a coloured update-available message to stderr."""
    import click

    click.echo(
        click.style(f"Update available: {current} → {latest}", fg="yellow", bold=True),
        err=True,
    )
    click.echo(
        click.style(f"  Run: {suggest_upgrade_cmd()}", fg="yellow"),
        err=True,
    )
