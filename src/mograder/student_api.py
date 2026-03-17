"""Read-only student API for assignment browsing and file download.

Serves assignment metadata (merged from config + release directory) and
release files.  No authentication required — intended to sit behind an
SSO reverse proxy.

Endpoints::

    GET /assignments                          -> enriched assignment list
    GET /assignments/<dir>/files/<file>       -> download release .py file
    GET /config                               -> public course metadata
"""

from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from mograder.config import MograderConfig
from mograder.wasm_compat import check_wasm_compatible


def create_student_api(course_dir: Path, config: MograderConfig) -> Starlette:
    """Create a read-only Starlette app for the student dashboard.

    Merges assignment metadata from *config* with file discovery from the
    ``release/`` directory.  WASM availability requires **both** a WASM
    export on disk (``.mograder/wasm/{dir}/index.html``) **and** a
    compatible source notebook (no native-extension dependencies).
    """
    release_dir = (course_dir / config.release_dir).resolve()
    wasm_dir = (course_dir / ".mograder" / "wasm").resolve()
    source_dir = (course_dir / config.source_dir).resolve()

    def _cors(response: Response) -> Response:
        # Allow-Origin: * is intentional — this API serves the student WASM app
        # which runs from file:// or arbitrary origins (e.g. molab, Codespaces).
        # All endpoints are read-only and unauthenticated.
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    def _json(data, status=200):
        return _cors(JSONResponse(data, status_code=status))

    def _match_release_dir(dir_key: str) -> Path | None:
        """Find release directory matching *dir_key* via substring match.

        Uses the same logic as ``match_transport_assignment()`` in
        ``formgrader_app.py``: the config ``dir`` field is a substring of
        the release directory name (e.g. ``"A1"`` matches
        ``"ES98E-A1-Intro-to-SciML"``).
        """
        if not release_dir.is_dir():
            return None
        for d in sorted(release_dir.iterdir()):
            if d.is_dir() and dir_key in d.name:
                return d
        return None

    def _match_source_dir(dir_key: str) -> Path | None:
        """Find source directory matching *dir_key* (same substring logic)."""
        if not source_dir.is_dir():
            return None
        for d in sorted(source_dir.iterdir()):
            if d.is_dir() and dir_key in d.name:
                return d
        return None

    # Cache WASM compatibility results (computed once per process)
    _wasm_compat_cache: dict[str, bool] = {}

    def _is_wasm_compatible(dir_key: str) -> bool:
        """Check whether the source notebook for *dir_key* is WASM-compatible."""
        if dir_key in _wasm_compat_cache:
            return _wasm_compat_cache[dir_key]
        src = _match_source_dir(dir_key)
        if src is None:
            _wasm_compat_cache[dir_key] = False
            return False
        py_files = sorted(src.glob("*.py"))
        if not py_files:
            _wasm_compat_cache[dir_key] = False
            return False
        compatible, _ = check_wasm_compatible(py_files[0])
        _wasm_compat_cache[dir_key] = compatible
        return compatible

    _content_lz_cache: dict[str, str] = {}

    def _get_content_lz(dir_key: str, matched: Path) -> str | None:
        """Compress release notebook with lz-string for molab embedding."""
        if dir_key in _content_lz_cache:
            return _content_lz_cache[dir_key]
        try:
            import lzstring
        except ModuleNotFoundError:
            return None

        py_files = sorted(
            f for f in matched.iterdir() if f.is_file() and f.suffix == ".py"
        )
        if not py_files:
            return None
        content = py_files[0].read_text()
        lz = lzstring.LZString()
        compressed = lz.compressToEncodedURIComponent(content)
        _content_lz_cache[dir_key] = compressed
        return compressed

    def _build_edit_links(dir_key: str, matched: Path | None) -> list[dict]:
        """Build edit link dicts from config templates for an assignment."""
        if not config.edit_links:
            return []
        template_vars: dict[str, str] = {"dir": dir_key}
        if matched:
            template_vars["release_dir"] = matched.name
            py_files = sorted(
                f for f in matched.iterdir() if f.is_file() and f.suffix == ".py"
            )
            if py_files:
                template_vars["filename"] = py_files[0].name
        links = []
        for name, template in config.edit_links:
            if "{content_lz}" in template:
                if not matched:
                    continue
                content_lz = _get_content_lz(dir_key, matched)
                if not content_lz:
                    continue
                template_vars["content_lz"] = content_lz
            try:
                url = template.format_map(template_vars)
            except KeyError:
                continue
            links.append({"name": name, "url": url})
        return links

    def _discover_files(matched_dir: Path, dir_key: str) -> list[dict]:
        """List downloadable files in a release directory."""
        files = []
        for f in sorted(matched_dir.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                files.append(
                    {
                        "filename": f.name,
                        "url": f"/assignments/{dir_key}/files/{f.name}",
                    }
                )
        return files

    async def list_assignments(request: Request):
        assignments = config.assignments or config.moodle_assignments
        result = []
        for a in assignments:
            entry: dict = {"name": a["name"]}
            dir_key = a.get("dir", "")
            if dir_key:
                entry["dir"] = dir_key
            if a.get("duedate"):
                entry["duedate"] = a["duedate"]
            if a.get("cmid"):
                entry["cmid"] = a["cmid"]

            # Discover files from release directory
            matched = _match_release_dir(dir_key) if dir_key else None
            entry["files"] = _discover_files(matched, dir_key) if matched else []

            # Check for WASM export (requires both export on disk AND compatible deps)
            if (
                dir_key
                and (wasm_dir / dir_key / "index.html").is_file()
                and _is_wasm_compatible(dir_key)
            ):
                entry["wasm_url"] = f"/wasm/{dir_key}/"

            # Build edit links (molab, codespaces, etc.)
            edit_links = _build_edit_links(dir_key, matched)
            if edit_links:
                entry["edit_links"] = edit_links

            result.append(entry)
        return _json(result)

    async def download_file(request: Request):
        dir_key = request.path_params["dir"]
        filename = request.path_params["file"]

        matched = _match_release_dir(dir_key)
        if matched is None:
            return _json({"error": "Assignment not found"}, 404)

        file_path = matched / filename
        if not file_path.is_file() or not file_path.resolve().is_relative_to(
            release_dir
        ):
            return _json({"error": f"Not found: {filename}"}, 404)

        return _cors(
            Response(file_path.read_bytes(), media_type="application/octet-stream")
        )

    async def get_config(request: Request):
        data: dict = {}
        if config.moodle_url:
            data["moodle_url"] = config.moodle_url
        if config.edit_links:
            data["edit_links"] = {name: tmpl for name, tmpl in config.edit_links}
        return _json(data)

    async def handle_options(request: Request):
        response = Response(status_code=204)
        return _cors(response)

    routes = [
        Route("/assignments", list_assignments),
        Route("/assignments/{dir}/files/{file:path}", download_file),
        Route("/config", get_config),
        Route("/assignments", handle_options, methods=["OPTIONS"]),
        Route(
            "/assignments/{dir}/files/{file:path}",
            handle_options,
            methods=["OPTIONS"],
        ),
        Route("/config", handle_options, methods=["OPTIONS"]),
    ]

    return Starlette(routes=routes)
