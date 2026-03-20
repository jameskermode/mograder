"""Build and inject edit-link HTML for Moodle assignment descriptions."""

from __future__ import annotations

import re
from pathlib import Path

_MARKER_START = "<!-- mograder:edit-links -->"
_MARKER_END = "<!-- /mograder:edit-links -->"
_MARKER_RE = re.compile(
    rf"\n?{re.escape(_MARKER_START)}.*?{re.escape(_MARKER_END)}\n?",
    re.DOTALL,
)


def build_edit_link_html(
    release_dir: Path,
    dir_key: str,
    edit_links: tuple[tuple[str, str], ...],
) -> str:
    """Build an HTML snippet with edit links for one assignment.

    *release_dir* is the path to the release directory (may not exist).
    *dir_key* is the assignment directory key (e.g. ``"A1-Demo"``).
    *edit_links* is a sequence of ``(name, url_template)`` pairs from config.

    Returns an HTML string (without markers) or ``""`` if nothing to generate.
    """
    if not edit_links:
        return ""
    if not release_dir.is_dir():
        return ""

    py_files = sorted(
        f for f in release_dir.iterdir() if f.is_file() and f.suffix == ".py"
    )

    template_vars: dict[str, str] = {"dir": dir_key}
    if py_files:
        template_vars["filename"] = py_files[0].name

    content_lz: str | None = None
    links: list[str] = []
    for name, template in edit_links:
        if "{content_lz}" in template:
            if not py_files:
                continue
            if content_lz is None:
                content_lz = _compress_lz(py_files[0])
                if not content_lz:
                    continue
            template_vars["content_lz"] = content_lz
        try:
            url = template.format_map(template_vars)
        except KeyError:
            continue
        links.append(f'<a href="{url}">{name}</a>')

    if not links:
        return ""
    return "<p>" + " &nbsp;|&nbsp; ".join(links) + "</p>"


def _compress_lz(py_file: Path) -> str | None:
    """Compress a .py file with lzstring for molab embedding."""
    try:
        import lzstring
    except ModuleNotFoundError:
        return None
    content = py_file.read_text()
    lz = lzstring.LZString()
    return lz.compressToEncodedURIComponent(content)


def inject_edit_links(existing_intro: str, new_links_html: str) -> str:
    """Inject edit-link HTML into a Moodle intro field.

    Strips any previous mograder-managed section (between markers),
    then appends the new section.
    """
    cleaned = strip_edit_links(existing_intro)
    section = f"\n{_MARKER_START}\n{new_links_html}\n{_MARKER_END}"
    return cleaned + section


def strip_edit_links(intro: str) -> str:
    """Remove any mograder edit-links section from an intro field."""
    return _MARKER_RE.sub("", intro)
