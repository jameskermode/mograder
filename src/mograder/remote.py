"""Stdlib-only helpers for fetching, submitting, and checking assignment status.

Works in regular Python and in molab server-side Python — no ``requests``
dependency.  Import from ``mograder.runtime`` for convenience::

    from mograder.runtime import fetch, submit, status
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path


def fetch(url: str, assignment: str, dest: str = ".") -> list[Path]:
    """Download all files for an assignment from the server.

    Args:
        url: Base server URL (e.g. ``"https://mograder-demo.onrender.com"``)
        assignment: Assignment name
        dest: Destination directory (default: current dir)

    Returns:
        List of downloaded file paths.
    """
    base = url.rstrip("/")
    dest_path = Path(dest)
    dest_path.mkdir(parents=True, exist_ok=True)

    with urllib.request.urlopen(f"{base}/assignments") as resp:
        assignments = json.loads(resp.read().decode())

    files_meta: list[dict] = []
    for a in assignments:
        if a["name"] == assignment:
            files_meta = a.get("files", [])
            break
    else:
        names = [a["name"] for a in assignments]
        raise ValueError(f"Assignment {assignment!r} not found. Available: {names}")

    downloaded: list[Path] = []
    for f in files_meta:
        file_url = f["url"]
        if file_url.startswith("/"):
            file_url = base + file_url
        out = dest_path / f["filename"]
        urllib.request.urlretrieve(file_url, str(out))
        downloaded.append(out)

    return downloaded


def submit(url: str, assignment: str, filepath: str, user: str) -> str:
    """Submit a file to the assignment server.

    Args:
        url: Base server URL
        assignment: Assignment name
        filepath: Path to the file to submit
        user: Username

    Returns:
        Status string from server (``"ok"`` on success).
    """
    base = url.rstrip("/")
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(filepath)

    data = path.read_bytes()
    boundary = "----MograderBoundary"
    body = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + data
        + f"\r\n--{boundary}--\r\n".encode()
    )

    endpoint = (
        f"{base}/assignments/{urllib.parse.quote(assignment, safe='')}"
        f"/submit?user={urllib.parse.quote(user, safe='')}"
    )
    req = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read().decode())

    return result.get("status", "unknown")


def status(url: str, assignment: str, user: str) -> dict:
    """Check submission status and grade for a user.

    Args:
        url: Base server URL
        assignment: Assignment name
        user: Username

    Returns:
        Dict with keys: ``status``, ``graded``, ``grade``, ``feedback``.
    """
    base = url.rstrip("/")
    endpoint = (
        f"{base}/assignments/{urllib.parse.quote(assignment, safe='')}"
        f"/status?user={urllib.parse.quote(user, safe='')}"
    )
    with urllib.request.urlopen(endpoint) as resp:
        return json.loads(resp.read().decode())
