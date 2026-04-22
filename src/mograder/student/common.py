"""Shared helpers for student dashboard apps (hub and local modes).

This module contains config loading, display helpers, and hub action
functions used by both ``student_app.py`` (local) and
``hub_student_app.py`` (hub).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


# -- Config helpers --


def load_student_config():
    """Load mograder config from MOGRADER_COURSE_DIR (or cwd).

    Returns (config, course_dir).
    """
    from mograder.core.config import load_config

    course_dir = Path(os.environ.get("MOGRADER_COURSE_DIR", ".")).resolve()
    config = load_config(course_dir)
    return config, course_dir


# -- Display helpers (re-exported from version module) --


def version_html() -> str:
    """Return an HTML version badge."""
    from mograder.version import version_html as _version_html

    return _version_html()


def brand_logo_html() -> str:
    """Return the mograder brand logo as an HTML/SVG string."""
    try:
        from mograder.brand import logo_html

        return logo_html()
    except ImportError:
        return ""


# -- Hub action results --


@dataclass
class ActionResult:
    """Result of a hub action (download, validate, edit, etc.)."""

    success: bool
    message: str
    url: str = ""


# -- Hub actions (httpx-based, used by hub_student_app.py) --


def hub_download(client, username: str, assignment: str, headers: dict) -> ActionResult:
    """Copy release notebook into the user's notebook store (server-side)."""
    try:
        resp = client.post(
            f"/download-release/{username}/{assignment}",
            headers=headers,
            timeout=30,
        )
        if resp.status_code != 200:
            return ActionResult(False, f"Download failed: {resp.text}")
        return ActionResult(True, f"Downloaded **{assignment}**")
    except Exception as exc:
        return ActionResult(False, f"Download failed: {exc}")


def hub_validate(client, username: str, assignment: str, headers: dict) -> ActionResult:
    """Run validation on a hub notebook."""
    try:
        resp = client.post(
            f"/validate/{username}/{assignment}",
            headers=headers,
            timeout=300,
        )
        if resp.status_code != 200:
            return ActionResult(False, f"Validation failed: {resp.text}")

        data = resp.json()
        checks = data.get("checks", [])
        passed = sum(1 for c in checks if c.get("status") == "success")
        total = len(checks)
        report_url = (
            f"/validate-report/{username}/{assignment}"
            if data.get("html_available")
            else ""
        )
        return ActionResult(
            True,
            f"Validated **{assignment}**: {passed}/{total} checks pass",
            url=report_url,
        )
    except Exception as exc:
        return ActionResult(False, f"Validation failed: {exc}")


def hub_submit(client, username: str, assignment: str, headers: dict) -> ActionResult:
    """Copy the hub notebook into the course submitted/ dir for grading."""
    try:
        resp = client.post(
            f"/submit/{username}/{assignment}",
            headers=headers,
            timeout=60,
        )
        if resp.status_code != 200:
            return ActionResult(False, f"Submit failed: {resp.text}")
        data = resp.json()
        parts = [f"Submitted **{assignment}**"]
        if data.get("tampered_checks") or data.get("tampered_marks"):
            bits = []
            if data.get("tampered_checks"):
                bits.append(f"checks: {', '.join(data['tampered_checks'])}")
            if data.get("tampered_marks"):
                bits.append("marks")
            parts.append(f"(reinjected {'; '.join(bits)})")
        return ActionResult(True, " ".join(parts))
    except Exception as exc:
        return ActionResult(False, f"Submit failed: {exc}")


def hub_start_edit(
    client, username: str, assignment: str, headers: dict
) -> ActionResult:
    """Start a marimo edit session on the hub."""
    try:
        resp = client.post(
            f"/start-edit/{username}/{assignment}",
            headers=headers,
            timeout=120,
        )
        if resp.status_code != 200:
            return ActionResult(False, f"Failed to start editor: {resp.text}")

        data = resp.json()
        url = data.get("url", "").lstrip("/")
        return ActionResult(True, f"Editing **{assignment}**", url=url)
    except Exception as exc:
        return ActionResult(False, f"Failed to start editor: {exc}")
