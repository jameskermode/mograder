"""Tests for mograder.student_api — read-only student assignment API."""

import pytest
from starlette.testclient import TestClient

from mograder.config import MograderConfig
from mograder.student_api import create_student_api


def _make_config(**kwargs) -> MograderConfig:
    """Create a MograderConfig with test defaults."""
    return MograderConfig(**kwargs)


@pytest.fixture()
def course_dir(tmp_path):
    """Set up a minimal course directory with config and release files."""
    # Create release directory with one assignment
    release = tmp_path / "release" / "ES98E-A1-Intro-to-SciML"
    release.mkdir(parents=True)
    (release / "ES98E-A1-Intro-to-SciML.py").write_text("# A1 starter code")

    return tmp_path


@pytest.fixture()
def config():
    """Minimal config with one assignment."""
    return _make_config(
        assignments=(
            {
                "name": "A1. Introduction to Scientific Machine Learning",
                "dir": "A1",
                "id": 45061,
                "cmid": 2452685,
                "duedate": 1737633600,
            },
        ),
        moodle_url="https://moodle.example.com",
    )


@pytest.fixture()
def client(course_dir, config):
    """TestClient for the student API."""
    app = create_student_api(course_dir, config)
    return TestClient(app, raise_server_exceptions=False)


class TestListAssignments:
    def test_list_assignments(self, client):
        resp = client.get("/assignments")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        a = data[0]
        assert a["name"] == "A1. Introduction to Scientific Machine Learning"
        assert a["dir"] == "A1"
        assert a["duedate"] == 1737633600
        assert a["cmid"] == 2452685
        assert len(a["files"]) == 1
        assert a["files"][0]["filename"] == "ES98E-A1-Intro-to-SciML.py"

    def test_dir_matching(self, client):
        """Config dir='A1' matches release dir 'ES98E-A1-Intro-to-SciML'."""
        resp = client.get("/assignments")
        data = resp.json()
        assert len(data[0]["files"]) == 1
        assert "ES98E-A1-Intro-to-SciML.py" in data[0]["files"][0]["filename"]

    def test_no_release_dir(self, tmp_path):
        """When release dir doesn't exist, files list is empty."""
        config = _make_config(
            assignments=({"name": "A2. Missing", "dir": "A2"},),
        )
        app = create_student_api(tmp_path, config)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/assignments")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["files"] == []

    def test_wasm_url_present(self, course_dir, config):
        """wasm_url included when export exists AND source is WASM-compatible."""
        # Create WASM export on disk
        wasm = course_dir / ".mograder" / "wasm" / "A1"
        wasm.mkdir(parents=True)
        (wasm / "index.html").write_text("<html>wasm</html>")

        # Create a WASM-compatible source notebook (no blocklisted deps)
        src = course_dir / "source" / "ES98E-A1-Intro-to-SciML"
        src.mkdir(parents=True)
        (src / "ES98E-A1-Intro-to-SciML.py").write_text(
            '# /// script\n# dependencies = [\n#     "numpy",\n#     "marimo",\n# ]\n# ///\n'
            "import marimo\napp = marimo.App()\n"
        )

        app = create_student_api(course_dir, config)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/assignments")
        data = resp.json()
        assert data[0]["wasm_url"] == "/wasm/A1/"

    def test_wasm_url_blocked_for_incompatible(self, course_dir, config):
        """wasm_url NOT included when export exists but source uses JAX/torch."""
        # Create WASM export on disk
        wasm = course_dir / ".mograder" / "wasm" / "A1"
        wasm.mkdir(parents=True)
        (wasm / "index.html").write_text("<html>wasm</html>")

        # Create a source notebook with blocklisted deps
        src = course_dir / "source" / "ES98E-A1-Intro-to-SciML"
        src.mkdir(parents=True)
        (src / "ES98E-A1-Intro-to-SciML.py").write_text(
            '# /// script\n# dependencies = [\n#     "jax",\n#     "torch",\n# ]\n# ///\n'
            "import marimo\napp = marimo.App()\n"
        )

        app = create_student_api(course_dir, config)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/assignments")
        data = resp.json()
        assert "wasm_url" not in data[0]

    def test_wasm_url_absent(self, client):
        """wasm_url not included when no WASM export exists."""
        resp = client.get("/assignments")
        data = resp.json()
        assert "wasm_url" not in data[0]

    def test_multiple_assignments(self, tmp_path):
        """Multiple assignments, some with files, some without."""
        # A1 has release files
        release_a1 = tmp_path / "release" / "ES98E-A1-Intro"
        release_a1.mkdir(parents=True)
        (release_a1 / "A1.py").write_text("# A1")

        # A2 has no release dir
        config = _make_config(
            assignments=(
                {"name": "A1", "dir": "A1", "duedate": 1000},
                {"name": "A2", "dir": "A2", "duedate": 2000},
            ),
        )
        app = create_student_api(tmp_path, config)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/assignments")
        data = resp.json()
        assert len(data) == 2
        assert len(data[0]["files"]) == 1
        assert data[1]["files"] == []


    def test_list_assignments_prefers_zip(self, course_dir, config):
        """When a .zip file exists in release dir, only the zip appears."""
        release = course_dir / "release" / "ES98E-A1-Intro-to-SciML"
        (release / "ES98E-A1-Intro-to-SciML.zip").write_bytes(b"PK\x03\x04fake")

        app = create_student_api(course_dir, config)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/assignments")
        data = resp.json()
        files = data[0]["files"]
        assert len(files) == 1
        assert files[0]["filename"] == "ES98E-A1-Intro-to-SciML.zip"

    def test_list_assignments_falls_back_to_py(self, client):
        """Without a .zip file, .py files are returned (existing behaviour)."""
        resp = client.get("/assignments")
        data = resp.json()
        files = data[0]["files"]
        assert len(files) == 1
        assert files[0]["filename"] == "ES98E-A1-Intro-to-SciML.py"


class TestDownloadFile:
    def test_download_file(self, client):
        resp = client.get("/assignments/A1/files/ES98E-A1-Intro-to-SciML.py")
        assert resp.status_code == 200
        assert b"A1 starter code" in resp.content

    def test_missing_file_404(self, client):
        resp = client.get("/assignments/A1/files/nonexistent.py")
        assert resp.status_code == 404

    def test_missing_assignment_404(self, client):
        resp = client.get("/assignments/A99/files/something.py")
        assert resp.status_code == 404


class TestConfig:
    def test_config_endpoint(self, client):
        resp = client.get("/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["moodle_url"] == "https://moodle.example.com"

    def test_config_no_moodle_url(self, tmp_path):
        """Config without moodle_url returns empty dict."""
        config = _make_config(assignments=())
        app = create_student_api(tmp_path, config)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/config")
        assert resp.status_code == 200
        assert resp.json() == {}


class TestEditLinks:
    def test_edit_links_with_content_lz(self, course_dir):
        """Template with {content_lz} produces URL containing lz-compressed content."""
        pytest.importorskip("lzstring")
        config = _make_config(
            assignments=({"name": "A1", "dir": "A1", "duedate": 1000},),
            edit_links=(("molab", "https://molab.marimo.io/new/#code/{content_lz}"),),
        )
        app = create_student_api(course_dir, config)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/assignments")
        data = resp.json()
        assert "edit_links" in data[0]
        links = data[0]["edit_links"]
        assert len(links) == 1
        assert links[0]["name"] == "molab"
        assert links[0]["url"].startswith("https://molab.marimo.io/new/#code/")
        # The compressed part should be non-empty
        compressed = links[0]["url"].split("#code/")[1]
        assert len(compressed) > 0

    def test_edit_links_static_url(self, course_dir):
        """Template without placeholders appears for all assignments."""
        config = _make_config(
            assignments=({"name": "A1", "dir": "A1", "duedate": 1000},),
            edit_links=(("codespaces", "https://github.com/example/codespaces"),),
        )
        app = create_student_api(course_dir, config)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/assignments")
        data = resp.json()
        links = data[0]["edit_links"]
        assert len(links) == 1
        assert links[0]["name"] == "codespaces"
        assert links[0]["url"] == "https://github.com/example/codespaces"

    def test_edit_links_missing_release_dir(self, tmp_path):
        """Template needing {content_lz} omitted when no release dir exists."""
        config = _make_config(
            assignments=({"name": "A2", "dir": "A2"},),
            edit_links=(
                ("molab", "https://molab.marimo.io/new/#code/{content_lz}"),
                ("codespaces", "https://github.com/example/codespaces"),
            ),
        )
        app = create_student_api(tmp_path, config)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/assignments")
        data = resp.json()
        # molab link should be absent (needs content_lz but no release dir)
        # codespaces should be present (static URL)
        links = data[0]["edit_links"]
        assert len(links) == 1
        assert links[0]["name"] == "codespaces"

    def test_edit_links_absent_when_no_config(self, course_dir):
        """No edit_links config → no edit_links key in response."""
        config = _make_config(
            assignments=({"name": "A1", "dir": "A1"},),
        )
        app = create_student_api(course_dir, config)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/assignments")
        data = resp.json()
        assert "edit_links" not in data[0]

    def test_config_endpoint_includes_edit_links(self, course_dir):
        """/config returns raw edit_links templates."""
        config = _make_config(
            assignments=(),
            edit_links=(
                ("molab", "https://molab.marimo.io/new/#code/{content_lz}"),
                ("codespaces", "https://github.com/example/codespaces"),
            ),
        )
        app = create_student_api(course_dir, config)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/config")
        data = resp.json()
        assert "edit_links" in data
        assert (
            data["edit_links"]["molab"]
            == "https://molab.marimo.io/new/#code/{content_lz}"
        )
        assert (
            data["edit_links"]["codespaces"] == "https://github.com/example/codespaces"
        )


class TestCORS:
    def test_cors_on_assignments(self, client):
        resp = client.get("/assignments")
        assert resp.headers.get("access-control-allow-origin") == "*"

    def test_cors_on_file_download(self, client):
        resp = client.get("/assignments/A1/files/ES98E-A1-Intro-to-SciML.py")
        assert resp.headers.get("access-control-allow-origin") == "*"

    def test_cors_on_config(self, client):
        resp = client.get("/config")
        assert resp.headers.get("access-control-allow-origin") == "*"

    def test_cors_on_404(self, client):
        resp = client.get("/assignments/A1/files/nope.py")
        assert resp.headers.get("access-control-allow-origin") == "*"
