"""Shared command logic for transport-agnostic operations.

Each ``do_*`` function takes a :class:`Transport` and performs the operation,
printing output via ``click.echo``.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import click

from mograder.transport import Transport, TransportError


def _rel(p: Path) -> str:
    import os

    try:
        return os.path.relpath(p)
    except ValueError:
        return str(p)


def do_fetch(
    transport: Transport,
    assignment: str | None,
    output_dir: Path,
    list_only: bool = False,
) -> None:
    """Download assignment files, or list available assignments."""
    from datetime import datetime, timezone

    try:
        assignments = transport.list_assignments()
    except TransportError as e:
        raise click.ClickException(str(e))

    if list_only:
        click.echo(f"{'ID':<8} {'Name':<40} {'Due date':<20} {'Files':>5}")
        click.echo("-" * 75)
        for a in assignments:
            due = (
                datetime.fromtimestamp(a.duedate, tz=timezone.utc).strftime(
                    "%Y-%m-%d %H:%M"
                )
                if a.duedate
                else "No deadline"
            )
            n_files = len(a.files)
            click.echo(f"{a.id:<8} {a.name:<40} {due:<20} {n_files:>5}")
        return

    if not assignment:
        raise click.UsageError(
            "Provide an assignment name, or use --list to see available assignments"
        )

    # Find matching assignment
    match = _find_remote_assignment(assignments, assignment)
    files = match.files
    if not files:
        click.echo(f"No files attached to assignment '{match.name}'")
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded = []
    for f in files:
        dest = output_dir / f["filename"]
        transport.download_file(f["url"], dest)
        downloaded.append(dest)
        click.echo(f"  Downloaded: {_rel(dest)}")

    # Auto-extract ZIP files
    for dest in downloaded:
        if dest.suffix.lower() == ".zip":
            with zipfile.ZipFile(dest) as zf:
                zf.extractall(output_dir)
                click.echo(f"  Extracted: {dest.name} ({len(zf.namelist())} files)")

    click.echo(f"Fetched {len(downloaded)} file(s) for '{match.name}'")


def do_submit(
    transport: Transport,
    filepath: Path,
    assignment: str,
    dry_run: bool = False,
) -> None:
    """Submit a file to an assignment."""
    if filepath.suffix != ".py":
        raise click.UsageError("Only .py files can be submitted")

    if dry_run:
        click.echo(f"Would submit: {_rel(filepath)}")
        click.echo(f"  Assignment: {assignment}")
        return

    click.echo(f"Uploading {_rel(filepath)}...")
    try:
        transport.submit_file(assignment, filepath)
    except TransportError as e:
        raise click.ClickException(str(e))
    click.echo(f"Submitted '{filepath.name}' to '{assignment}'")


def _load_fetch_meta(output_dir: Path) -> dict:
    """Load previously fetched submission timestamps from sidecar file."""
    import json

    meta_path = output_dir / ".fetch_metadata.json"
    if meta_path.is_file():
        try:
            return json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_fetch_meta(output_dir: Path, meta: dict) -> None:
    """Save fetched submission timestamps to sidecar file."""
    import json

    meta_path = output_dir / ".fetch_metadata.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")


def do_fetch_submissions(
    transport: Transport,
    assignment: str,
    output_dir: Path,
    force: bool = False,
) -> None:
    """Download all student submissions for an assignment.

    Tracks remote ``timemodified`` timestamps in a sidecar metadata file.
    Skips submissions that haven't changed since the last fetch (unless
    *force* is True).
    """
    try:
        submissions = transport.get_submissions(assignment)
    except TransportError as e:
        raise click.ClickException(str(e))
    output_dir.mkdir(parents=True, exist_ok=True)

    meta = _load_fetch_meta(output_dir)
    downloaded = 0
    skipped = 0
    for sub in submissions:
        if sub.status != "submitted":
            continue
        dest = output_dir / f"{sub.username}.py"
        if (
            not force
            and dest.is_file()
            and sub.timemodified
            and meta.get(sub.username) == sub.timemodified
        ):
            skipped += 1
            continue
        transport.download_file(sub.url, dest)
        if sub.timemodified:
            meta[sub.username] = sub.timemodified
        click.echo(f"  {sub.username}.py")
        downloaded += 1

    _save_fetch_meta(output_dir, meta)

    parts = [f"Downloaded {downloaded}"]
    if skipped:
        parts.append(f"skipped {skipped} unchanged")
    click.echo(f"{', '.join(parts)} submission(s) in {_rel(output_dir)}")


def do_upload_feedback(
    transport: Transport,
    assignment: str,
    grades: list[dict],
    dry_run: bool = False,
    workflow_state: str = "",
) -> None:
    """Upload grades and feedback."""
    if dry_run:
        click.echo(f"Would upload {len(grades)} grade(s) to '{assignment}'")
        for g in grades:
            user = g.get("username", g.get("userid", "?"))
            click.echo(f"  {user}: {g.get('grade', '?')}")
        return

    if not grades:
        click.echo("No grades to upload")
        return

    try:
        transport.upload_grades(assignment, grades, workflow_state=workflow_state)
    except TransportError as e:
        raise click.ClickException(str(e))
    click.echo(f"Uploaded {len(grades)} grade(s) to '{assignment}'")


def do_status(
    transport: Transport,
    assignment: str,
) -> None:
    """Show submission status, grade, and feedback."""
    click.echo(f"Assignment: {assignment}")
    try:
        status = transport.get_status(assignment)
    except TransportError as e:
        raise click.ClickException(str(e))
    click.echo(f"Status: {status.status}")

    if status.graded:
        click.echo(f"Grade: {status.grade}")
        if status.feedback:
            click.echo(f"Feedback:\n  {status.feedback}")
    elif status.status == "new":
        click.echo("No submission yet.")
    else:
        click.echo("Not yet graded.")


def _find_remote_assignment(assignments, name):
    """Find assignment by name or ID from a list of RemoteAssignment."""
    # Exact name match
    exact = [a for a in assignments if a.name == name]
    if len(exact) == 1:
        return exact[0]

    # Numeric ID
    try:
        aid = str(int(name))
        by_id = [a for a in assignments if a.id == aid]
        if len(by_id) == 1:
            return by_id[0]
    except ValueError:
        pass

    # Case-insensitive substring
    lower = name.lower()
    matches = [a for a in assignments if lower in a.name.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = "\n  ".join(a.name for a in matches)
        raise click.UsageError(
            f"Ambiguous assignment name '{name}'. Matches:\n  {names}"
        )

    names = "\n  ".join(a.name for a in assignments)
    raise click.UsageError(f"No assignment matching '{name}'. Available:\n  {names}")
