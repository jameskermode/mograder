"""Unified file-based token caching."""

from __future__ import annotations

import json
import os
from pathlib import Path


class TokenCache:
    """JSON file cache keyed on a URL field.

    Used by both HTTPS and Moodle authentication to persist tokens.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self, match_key: str = "url", match_value: str = "") -> dict | None:
        """Load cached data if *match_key* equals *match_value*."""
        if not self.path.is_file():
            return None
        try:
            data = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        if data.get(match_key) == match_value.rstrip("/"):
            return data
        return None

    def save(self, data: dict, url_key: str = "url") -> None:
        """Write *data* to the cache file (mode 0o600).

        If *url_key* is present in *data*, strips a trailing slash for
        consistent matching.
        """
        if url_key in data:
            data = {**data, url_key: data[url_key].rstrip("/")}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data))
        os.chmod(self.path, 0o600)

    def clear(self) -> None:
        """Remove the cache file."""
        self.path.unlink(missing_ok=True)
