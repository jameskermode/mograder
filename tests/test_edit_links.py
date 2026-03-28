"""Tests for mograder.transport.edit_links — HTML generation and injection for Moodle."""

from mograder.transport.edit_links import (
    build_edit_link_html,
    inject_edit_links,
    strip_edit_links,
)


# ---------------------------------------------------------------------------
# build_edit_link_html
# ---------------------------------------------------------------------------


class TestBuildEditLinkHtml:
    def test_molab_link(self, tmp_path):
        """Release dir with .py file → HTML with lzstring-compressed molab link."""
        release = tmp_path / "A1-Demo"
        release.mkdir()
        (release / "A1-Demo.py").write_text("print('hello')")

        edit_links = (("molab", "https://molab.marimo.io/new/#code/{content_lz}"),)
        html = build_edit_link_html(release, "A1-Demo", edit_links)

        assert "molab" in html.lower() or "Molab" in html
        assert "https://molab.marimo.io/new/#code/" in html
        assert "mograder:edit-links" not in html  # markers are added by inject

    def test_codespaces_link(self, tmp_path):
        """Codespaces config → includes codespaces link (no lzstring needed)."""
        release = tmp_path / "A1-Demo"
        release.mkdir()
        (release / "A1-Demo.py").write_text("print('hello')")

        edit_links = (("codespaces", "https://github.com/org/repo/codespaces"),)
        html = build_edit_link_html(release, "A1-Demo", edit_links)

        assert "https://github.com/org/repo/codespaces" in html
        assert "codespaces" in html.lower() or "Codespaces" in html

    def test_both_links(self, tmp_path):
        """Both molab and codespaces → both appear in HTML."""
        release = tmp_path / "A1-Demo"
        release.mkdir()
        (release / "A1-Demo.py").write_text("print('hello')")

        edit_links = (
            ("molab", "https://molab.marimo.io/new/#code/{content_lz}"),
            ("codespaces", "https://github.com/org/repo/codespaces"),
        )
        html = build_edit_link_html(release, "A1-Demo", edit_links)

        assert "molab.marimo.io" in html
        assert "github.com/org/repo/codespaces" in html

    def test_no_release_dir(self, tmp_path):
        """No release dir → returns empty string."""
        missing = tmp_path / "nonexistent"
        edit_links = (("molab", "https://molab.marimo.io/new/#code/{content_lz}"),)
        html = build_edit_link_html(missing, "A1-Demo", edit_links)
        assert html == ""

    def test_empty_release_dir(self, tmp_path):
        """Release dir with no .py files → empty string for molab (needs content)."""
        release = tmp_path / "A1-Demo"
        release.mkdir()

        edit_links = (("molab", "https://molab.marimo.io/new/#code/{content_lz}"),)
        html = build_edit_link_html(release, "A1-Demo", edit_links)
        assert html == ""

    def test_no_edit_links_config(self, tmp_path):
        """Empty edit_links config → empty string."""
        release = tmp_path / "A1-Demo"
        release.mkdir()
        (release / "A1-Demo.py").write_text("print('hello')")

        html = build_edit_link_html(release, "A1-Demo", ())
        assert html == ""

    def test_template_with_dir_key(self, tmp_path):
        """Template using {dir} variable → dir_key substituted."""
        release = tmp_path / "A1-Demo"
        release.mkdir()
        (release / "A1-Demo.py").write_text("x")

        edit_links = (("custom", "https://example.com/{dir}"),)
        html = build_edit_link_html(release, "A1-Demo", edit_links)
        assert "https://example.com/A1-Demo" in html


# ---------------------------------------------------------------------------
# inject_edit_links / strip_edit_links
# ---------------------------------------------------------------------------


class TestInjectEditLinks:
    def test_inject_into_empty_intro(self):
        """Empty intro + links → just markers and links."""
        links_html = '<p><a href="https://example.com">Edit</a></p>'
        result = inject_edit_links("", links_html)

        assert "<!-- mograder:edit-links -->" in result
        assert "<!-- /mograder:edit-links -->" in result
        assert links_html in result

    def test_inject_preserves_existing(self):
        """Existing description + links → existing text then markers then links."""
        existing = "<p>Submit your work by Friday.</p>"
        links_html = '<p><a href="https://example.com">Edit</a></p>'
        result = inject_edit_links(existing, links_html)

        assert result.startswith(existing)
        assert links_html in result
        assert "<!-- mograder:edit-links -->" in result

    def test_inject_replaces_old_markers(self):
        """Intro with old markers → old stripped, new appended."""
        existing = (
            "<p>Description</p>\n"
            "<!-- mograder:edit-links -->\n"
            "<p>old link</p>\n"
            "<!-- /mograder:edit-links -->"
        )
        new_links = '<p><a href="https://new.example.com">New Edit</a></p>'
        result = inject_edit_links(existing, new_links)

        assert "old link" not in result
        assert "new.example.com" in result
        assert "<p>Description</p>" in result
        # Only one set of markers
        assert result.count("<!-- mograder:edit-links -->") == 1
        assert result.count("<!-- /mograder:edit-links -->") == 1


class TestStripEditLinks:
    def test_strip_removes_markers(self):
        """Intro with markers → clean intro without mograder section."""
        intro = (
            "<p>Description</p>\n"
            "<!-- mograder:edit-links -->\n"
            "<p>edit link</p>\n"
            "<!-- /mograder:edit-links -->"
        )
        result = strip_edit_links(intro)
        assert "edit link" not in result
        assert "mograder:edit-links" not in result
        assert "<p>Description</p>" in result

    def test_strip_no_markers(self):
        """Intro without markers → unchanged."""
        intro = "<p>Description</p>"
        result = strip_edit_links(intro)
        assert result == intro

    def test_strip_empty(self):
        """Empty intro → empty."""
        assert strip_edit_links("") == ""

    def test_strip_markers_only(self):
        """Only markers, no other content → empty or whitespace."""
        intro = (
            "<!-- mograder:edit-links -->\n"
            "<p>edit link</p>\n"
            "<!-- /mograder:edit-links -->"
        )
        result = strip_edit_links(intro)
        assert result.strip() == ""
