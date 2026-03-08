"""Formgrader UI tests: smoke test (no browser) + Playwright e2e test.

Smoke test validates the marimo notebook structure without execution.
Playwright test launches the formgrader and checks the rendered UI.

Run all:     uv run pytest tests/test_formgrader_ui.py -v
Skip slow:   uv run pytest tests/test_formgrader_ui.py -v -m "not slow"
"""

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).parent.parent / "examples"
FORMGRADER_APP = Path(__file__).parent.parent / "src" / "mograder" / "formgrader_app.py"


# ---------------------------------------------------------------------------
# Smoke test — no browser, validates notebook structure
# ---------------------------------------------------------------------------


def test_formgrader_app_parses_as_valid_marimo():
    """The formgrader app should parse as a valid marimo notebook."""
    from marimo._convert import MarimoConvert

    source = FORMGRADER_APP.read_text(encoding="utf-8")
    ir = MarimoConvert.from_py(source).to_ir()
    assert ir.valid, f"Notebook is invalid: {ir.violations}"
    assert len(ir.cells) > 0


def test_formgrader_app_has_expected_cells():
    """The formgrader app should have the key structural cells."""
    source = FORMGRADER_APP.read_text(encoding="utf-8")
    assert "mo.ui.tabs" in source
    assert "assignments_content" in source
    assert "submissions_content" in source
    assert "grading_content" in source
    assert "students_content" in source
    assert "imp_uploads" in source
    assert "extract_submissions" in source


def test_formgrader_app_no_script_header():
    """The app must not have a PEP 723 script header."""
    header = FORMGRADER_APP.read_text(encoding="utf-8")[:200]
    assert "/// script" not in header


# ---------------------------------------------------------------------------
# Playwright e2e test — launches formgrader, checks rendered UI
# ---------------------------------------------------------------------------


def _get_free_port():
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _wait_for_app(page, timeout_ms=120000):
    """Wait for the marimo app to fully render.

    In ``marimo run`` mode there are no ``<marimo-cell-output>`` custom
    elements.  We wait for the ``marimo-tabs`` widget which is part of the
    formgrader layout cell and only appears once the app has executed.
    """
    page.wait_for_selector("marimo-tabs", state="attached", timeout=timeout_ms)
    page.wait_for_timeout(3000)


@pytest.fixture(scope="module")
def _course_dir(tmp_path_factory):
    """Set up a course directory with source + release + import fixtures."""
    tmp_path = tmp_path_factory.mktemp("course")

    src = tmp_path / "source" / "demo-holistic"
    src.mkdir(parents=True)
    shutil.copy(
        EXAMPLES / "source" / "demo-holistic" / "demo-holistic.py",
        src / "demo-holistic.py",
    )

    rel = tmp_path / "release" / "demo-holistic"
    rel.mkdir(parents=True)
    shutil.copy(
        EXAMPLES / "release" / "demo-holistic" / "demo-holistic.py",
        rel / "demo-holistic.py",
    )

    imp = tmp_path / "import"
    imp.mkdir()
    shutil.copy(
        EXAMPLES / "import-test" / "demo-holistic.csv", imp / "demo-holistic.csv"
    )
    shutil.copy(
        EXAMPLES / "import-test" / "demo-holistic.zip", imp / "demo-holistic.zip"
    )

    return tmp_path


@pytest.fixture(scope="module")
def formgrader_url(_course_dir):
    """Launch formgrader as a subprocess and yield the URL (shared across tests)."""
    port = _get_free_port()
    env = {**os.environ, "MOGRADER_COURSE_DIR": str(_course_dir)}
    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "marimo",
            "-q",
            "run",
            str(FORMGRADER_APP),
            "-p",
            str(port),
            "--headless",
            "--no-token",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    url = f"http://localhost:{port}"
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            with socket.create_connection(("localhost", port), timeout=1):
                break
        except OSError:
            time.sleep(0.5)
    else:
        proc.terminate()
        pytest.fail("Formgrader server did not start within 60s")

    yield url

    proc.terminate()
    proc.wait(timeout=5)


@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("CI") == "true", reason="marimo too slow in CI")
def test_formgrader_renders_assignments_table(formgrader_url, page):
    """The Assignments tab should render with expected columns and content."""
    page.goto(formgrader_url)
    _wait_for_app(page)

    content = page.content()
    assert "Assignments" in content, "Assignments tab not rendered"
    assert "demo-holistic" in content
    assert "Source" in content
    assert "Release" in content
    assert "Export" in content


@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("CI") == "true", reason="marimo too slow in CI")
def test_formgrader_tabs_navigation(formgrader_url, page):
    """All four tabs should be clickable and render content."""
    page.goto(formgrader_url)
    _wait_for_app(page)

    for tab_name in ["Submissions", "Grading", "Students", "Assignments"]:
        tab = page.get_by_text(tab_name, exact=True)
        tab.click()
        page.wait_for_timeout(500)


@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("CI") == "true", reason="marimo too slow in CI")
def test_formgrader_assignment_dropdown(formgrader_url, page):
    """The assignment dropdown should be visible in the Submissions tab."""
    page.goto(formgrader_url)
    _wait_for_app(page)

    # Dropdown lives inside the Submissions tab, not the header
    page.get_by_text("Submissions", exact=True).click()
    page.wait_for_timeout(1000)
    dropdown = page.get_by_test_id("marimo-plugin-dropdown").first
    assert dropdown.is_visible()
