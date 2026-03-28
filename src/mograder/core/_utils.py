"""Shared low-level utilities used across mograder."""

from __future__ import annotations

import os
import re
from pathlib import Path

TIMESTAMP_RE = re.compile(r"_\d{8}T\d{6}$")


def rel(p: Path) -> str:
    """Return a short relative path string for display."""
    try:
        return os.path.relpath(p)
    except ValueError:
        return str(p)


def cors_headers(
    methods: str = "GET, POST, OPTIONS",
    headers: str = "Content-Type, Authorization",
) -> dict[str, str]:
    """Return a dict of standard permissive CORS headers."""
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": methods,
        "Access-Control-Allow-Headers": headers,
    }


def add_cors_to_response(
    response,
    methods: str = "GET, POST, OPTIONS",
    headers: str = "Content-Type, Authorization",
):
    """Add CORS headers to a Starlette-style Response object."""
    for k, v in cors_headers(methods, headers).items():
        response.headers[k] = v
    return response


def match_dir_by_key(parent: Path, key: str) -> Path | None:
    """Find first subdirectory of *parent* whose name contains *key*."""
    if not parent.is_dir():
        return None
    for d in sorted(parent.iterdir()):
        if d.is_dir() and key in d.name:
            return d
    return None
