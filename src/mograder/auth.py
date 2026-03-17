"""Token generation and verification for HTTPS transport authentication.

Uses HMAC-SHA256 tokens: ``username:hmac_hex``.  A special
``__instructor__`` username grants admin access to instructor-only endpoints.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from pathlib import Path

INSTRUCTOR_USER = "__instructor__"
SECRET_FILENAME = ".mograder-secret"
HTTPS_TOKEN_CACHE = Path.home() / ".config" / "mograder" / "https_token.json"


def generate_secret() -> str:
    """Return a random 32-byte hex secret."""
    return secrets.token_hex(32)


def load_or_create_secret(root_dir: Path) -> str:
    """Read or create the secret file in *root_dir*."""
    secret_path = root_dir / SECRET_FILENAME
    if secret_path.is_file():
        return secret_path.read_text().strip()
    secret = generate_secret()
    # Create with restrictive permissions (owner-only read/write)
    import os

    fd = os.open(str(secret_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, (secret + "\n").encode())
    finally:
        os.close(fd)
    return secret


def make_token(secret: str, username: str) -> str:
    """Create an HMAC token for *username*."""
    mac = hmac.new(secret.encode(), username.encode(), hashlib.sha256).hexdigest()
    return f"{username}:{mac}"


def verify_token(secret: str, token: str) -> str | None:
    """Verify *token* and return the username, or ``None`` if invalid."""
    if ":" not in token:
        return None
    username, mac_hex = token.split(":", 1)
    expected = hmac.new(secret.encode(), username.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(mac_hex, expected):
        return username
    return None


def is_instructor(username: str) -> bool:
    """Return True if *username* is the instructor user."""
    return username == INSTRUCTOR_USER


# --- HTTPS token cache (mirrors moodle_api.py pattern) ---


def load_cached_https_token(url: str) -> dict | None:
    """Load a cached HTTPS token for *url*.

    Returns ``{"url", "token", "user"}`` if the URL matches, else ``None``.
    """
    if not HTTPS_TOKEN_CACHE.is_file():
        return None
    try:
        data = json.loads(HTTPS_TOKEN_CACHE.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if data.get("url") == url.rstrip("/"):
        return data
    return None


def save_cached_https_token(url: str, token: str, user: str) -> None:
    """Persist an HTTPS token to the cache file."""
    import os

    HTTPS_TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    HTTPS_TOKEN_CACHE.write_text(
        json.dumps({"url": url.rstrip("/"), "token": token, "user": user})
    )
    os.chmod(HTTPS_TOKEN_CACHE, 0o600)


def clear_cached_https_token() -> None:
    """Remove the cached HTTPS token file."""
    HTTPS_TOKEN_CACHE.unlink(missing_ok=True)
