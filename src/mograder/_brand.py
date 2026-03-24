"""Branding constants: favicon link tag, inline logo HTML, and version display."""

from __future__ import annotations

from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent


def _read_head_html() -> str:
    return (_PKG_DIR / "head.html").read_text()


FAVICON_LINK = _read_head_html()

_LOGO_B64 = (
    "PHN2ZyB3aWR0aD0iMjU2IiBoZWlnaHQ9IjI1NiIgdmlld0JveD0iMCAwIDI1NiAyNTYiIHhtbG5z"
    "PSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPGRlZnM+CiAgICA8c3R5bGU+CiAgICAg"
    "IC5saW5lIHsKICAgICAgICBzdHJva2U6ICMwQUFENjk7CiAgICAgICAgc3Ryb2tlLXdpZHRoOiAxMD"
    "sKICAgICAgICBzdHJva2UtbGluZWNhcDogcm91bmQ7CiAgICAgICAgc3Ryb2tlLWxpbmVqb2luOiBy"
    "b3VuZDsKICAgICAgICBmaWxsOiBub25lOwogICAgICB9CiAgICAgIC5ncmlkIHsKICAgICAgICBzdH"
    "Jva2U6ICMwQUFENjk7CiAgICAgICAgc3Ryb2tlLXdpZHRoOiA2OwogICAgICAgIHN0cm9rZS1saW5l"
    "Y2FwOiByb3VuZDsKICAgICAgICBvcGFjaXR5OiAwLjU7CiAgICAgIH0KICAgICAgLnRleHQgewogIC"
    "AgICAgIGZvbnQtZmFtaWx5OiAtYXBwbGUtc3lzdGVtLCBCbGlua01hY1N5c3RlbUZvbnQsICJTZWdv"
    "ZSBVSSIsIFJvYm90bywgc2Fucy1zZXJpZjsKICAgICAgICBmb250LXNpemU6IDM2cHg7CiAgICAgI"
    "CAgZmlsbDogIzFmMjkzNzsKICAgICAgfQogICAgPC9zdHlsZT4KICA8L2RlZnM+CgogIDwhLS0gUm"
    "91bmRlZCBzcXVhcmUgLS0+CiAgPHJlY3QgeD0iMjgiIHk9IjI4IiB3aWR0aD0iMjAwIiBoZWlnaH"
    "Q9IjIwMCIgcng9IjM2IiBjbGFzcz0ibGluZSI+PC9yZWN0PgoKICA8IS0tIEdyaWQgKDN4MykgLS0+"
    "CiAgPCEtLSBWZXJ0aWNhbCBsaW5lcyAtLT4KICA8bGluZSB4MT0iOTYiIHkxPSI2NCIgeDI9Ijk2"
    "IiB5Mj0iMTkyIiBjbGFzcz0iZ3JpZCI+PC9saW5lPgogIDxsaW5lIHgxPSIxNjAiIHkxPSI2NCIg"
    "eDI9IjE2MCIgeTI9IjE5MiIgY2xhc3M9ImdyaWQiPjwvbGluZT4KCiAgPCEtLSBIb3Jpem9udGFs"
    "IGxpbmVzIC0tPgogIDxsaW5lIHgxPSI2NCIgeTE9Ijk2IiB4Mj0iMTkyIiB5Mj0iOTYiIGNsYXNz"
    "PSJncmlkIj48L2xpbmU+CiAgPGxpbmUgeDE9IjY0IiB5MT0iMTYwIiB4Mj0iMTkyIiB5Mj0iMTYw"
    "IiBjbGFzcz0iZ3JpZCI+PC9saW5lPgoKICA8IS0tIENoZWNrbWFyayAodG9wLXJpZ2h0IGNlbGwpIC"
    "0tPgogIDxwYXRoIGQ9Ik0xNTAgODAgTDE3MCAxMDAgTDIwMCA2MCIgY2xhc3M9ImxpbmUiPjwvcG"
    "F0aD4KPC9zdmc+"
)


def logo_html(size: int = 48) -> str:
    """Return an ``<img>`` tag with the mograder logo as an inline data URI."""
    return (
        f'<img src="data:image/svg+xml;base64,{_LOGO_B64}"'
        f' width="{size}" height="{size}" alt="mograder"'
        f' style="vertical-align: middle;">'
    )


# Re-export version functions so marimo app imports don't need to change.
from mograder.version import version_html  # noqa: E402, F401
