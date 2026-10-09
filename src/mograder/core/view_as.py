"""'View as': an instructor temporarily sees an app as a student or marker.

Like Moodle's "Switch role to…": the instructor keeps their own identity
(username, their own copies) but gets the other role's permissions, so what
they see and can do is what that role sees and can do. On the hub an "as of"
date can be added, so scheduled visibility is evaluated at that moment
(preview the release schedule).

The choice is a cookie, honoured only when the real user is an instructor,
so it can only ever reduce privileges; a student who sets it changes
nothing. Apps call :func:`apply` in their auth middleware after resolving the
real user, and offer a ``view-as`` endpoint (see :func:`cookie_header`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote, unquote

COOKIE = "mograder_view_as"
MAX_AGE = 8 * 3600  # a test session, not a permanent switch


def parse(value: str | None) -> tuple[str, str | None] | None:
    """``"student"`` or ``"student|<ISO datetime>"`` → ``(role, as_of)``."""
    if not value:
        return None
    role, _, as_of = unquote(value).partition("|")
    role = role.strip()
    if not role:
        return None
    if as_of:
        try:
            dt = datetime.fromisoformat(as_of)
        except ValueError:
            as_of = ""
        else:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            as_of = dt.isoformat()
    return role, as_of or None


def apply(user: dict, cookie_value: str | None, roles: set[str]) -> dict:
    """The user as seen by the app: switched to the cookie's role if the real
    user is an instructor and the role is one of *roles*; unchanged otherwise.

    A switched user has ``is_instructor`` False, ``is_<role>`` True,
    ``view_as`` (the role), ``as_of`` (ISO datetime or None) and
    ``real_is_instructor`` True.
    """
    if not user or not user.get("is_instructor"):
        return user
    parsed = parse(cookie_value)
    if parsed is None or parsed[0] not in roles:
        return {**user, "real_is_instructor": True}
    role, as_of = parsed
    switched = {**user, "is_instructor": False, "view_as": role, "as_of": as_of}
    switched[f"is_{role}"] = True
    switched["real_is_instructor"] = True
    return switched


def as_of_timestamp(user: dict | None) -> float | None:
    """The 'as of' moment of a switched user, as a POSIX timestamp."""
    as_of = (user or {}).get("as_of")
    if not as_of:
        return None
    try:
        return datetime.fromisoformat(as_of).timestamp()
    except ValueError:
        return None


def cookie_header(role: str | None, as_of: str | None = None) -> bytes:
    """``Set-Cookie`` value switching to *role* (None/"" clears the switch).

    No ``Path``: the browser scopes it to the directory of the view-as URL,
    i.e. the app's base path (e.g. ``/live/hub/``), whatever proxy prefix.
    """
    if not role:
        return f"{COOKIE}=; Max-Age=0; HttpOnly; SameSite=Lax".encode()
    value = role + (f"|{as_of}" if as_of else "")
    return (
        f"{COOKIE}={quote(value, safe='')}; Max-Age={MAX_AGE}; HttpOnly; SameSite=Lax"
    ).encode()


def read_cookie(headers: list[tuple[bytes, bytes]]) -> str | None:
    """The view-as cookie from raw ASGI request headers."""
    for key, value in headers:
        if key == b"cookie":
            for part in value.decode("latin-1").split(";"):
                name, _, val = part.strip().partition("=")
                if name == COOKIE:
                    return val
    return None
