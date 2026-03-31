"""Hub FastAPI application — multi-user marimo server."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from mograder.hub.auth import ALLOWED_USERS_FILE, RemoteUserMiddleware
from mograder.hub.proxy import create_proxy_router
from mograder.hub.spawner import SessionManager
from mograder.hub.storage import StorageManager
from mograder.grading.runner import run_notebook
from mograder.grading.safety import check_safety

log = logging.getLogger("mograder.hub")


def create_hub_app(
    course_dir: Path,
    *,
    dev: bool = False,
    notebooks_dir: Path | None = None,
    release_dir: Path | None = None,
    secret: str | None = None,
    port: int = 8080,
    session_ttl: int = 3600,
    trusted_header: str = "X-Remote-User",
    trusted_proxies: set[str] | None = None,
    use_bubblewrap: bool = False,
    uv_cache_dir: str = "",
) -> FastAPI:
    """Create the hub FastAPI application."""
    from mograder.core.config import load_config

    config = load_config(course_dir)

    # Resolve directories
    nb_dir = Path(notebooks_dir or course_dir / config.hub_notebooks_dir)
    rel_dir = Path(release_dir or course_dir / config.hub_release_dir)
    nb_dir.mkdir(parents=True, exist_ok=True)
    rel_dir.mkdir(parents=True, exist_ok=True)

    # Resolve secret
    if secret is None:
        secret = os.environ.get("MOGRADER_HUB_SECRET", "")
    if not secret and dev:
        import secrets as _secrets

        secret = _secrets.token_hex(32)
        log.warning("Dev mode: using ephemeral secret")
    if not secret:
        raise ValueError(
            "MOGRADER_HUB_SECRET must be set (or use --dev for ephemeral secret)"
        )

    storage = StorageManager(notebooks_dir=nb_dir, release_dir=rel_dir)
    session_mgr = SessionManager(
        notebooks_dir=nb_dir,
        session_ttl=session_ttl,
        use_bubblewrap=use_bubblewrap,
        uv_cache_dir=uv_cache_dir,
        release_dir=rel_dir,
    )

    @asynccontextmanager
    async def lifespan(app):
        culler = asyncio.create_task(session_mgr.start_culler())
        yield
        culler.cancel()
        await session_mgr.shutdown_all()

    app = FastAPI(lifespan=lifespan)

    # Expose managers on app.state for testing
    app.state.session_mgr = session_mgr
    app.state.storage = storage

    # Auth middleware — always trust localhost for internal API calls
    _proxies = trusted_proxies or set()
    _proxies.add("127.0.0.1")
    app.add_middleware(
        RemoteUserMiddleware,
        secret=secret,
        trusted_proxies=_proxies,
        trusted_header=trusted_header,
        dev=dev,
        allowed_users_file=course_dir / ALLOWED_USERS_FILE,
    )

    # Include proxy router
    proxy_router = create_proxy_router(session_mgr)
    app.include_router(proxy_router)

    # -- Helper to check user owns the resource --

    def _check_owner(request: Request, username: str) -> str:
        """Verify current user matches username or is instructor."""
        user = request.scope.get("user", {})
        current = user.get("username", "")
        if not current:
            raise HTTPException(status_code=403, detail="Authentication required")
        if user.get("is_instructor") or current == username:
            return current
        raise HTTPException(
            status_code=403, detail="Cannot access another user's resources"
        )

    # -- Upload --

    @app.post("/upload/{username}/{assignment}")
    async def upload(
        request: Request, username: str, assignment: str, file: UploadFile
    ):
        _check_owner(request, username)
        content = (await file.read()).decode("utf-8", errors="replace")

        # Safety check
        result = check_safety(content)
        if not result.safe:
            details = "; ".join(f.description for f in result.findings)
            raise HTTPException(status_code=400, detail=f"Unsafe code: {details}")

        # Archive existing
        nb = storage.assignment_path(username, assignment)
        if nb.exists():
            ts = time.strftime("%Y%m%dT%H%M%S")
            archive = nb.with_suffix(f".bak.{ts}.py")
            shutil.move(str(nb), str(archive))

        # Write new file
        storage.ensure_dir(username, assignment)
        nb.write_text(content)
        storage.mark_uploaded(username, assignment)

        # Kill running session if any
        if (username, assignment) in session_mgr.sessions:
            await session_mgr.terminate(username, assignment)

        return {"status": "ok", "path": str(nb)}

    # -- Export --

    @app.get("/export/{username}/{assignment}")
    async def export(request: Request, username: str, assignment: str):
        _check_owner(request, username)
        nb = storage.assignment_path(username, assignment)
        if not nb.exists():
            raise HTTPException(status_code=404, detail="Notebook not found")
        storage.mark_exported(username, assignment)
        return FileResponse(
            nb,
            filename=f"{assignment}.py",
            media_type="text/x-python",
        )

    # -- Validate --

    @app.post("/validate/{username}/{assignment}")
    async def validate(request: Request, username: str, assignment: str):
        _check_owner(request, username)
        nb = storage.assignment_path(username, assignment)
        if not nb.exists():
            raise HTTPException(status_code=404, detail="Notebook not found")

        # Integrity check
        integrity_level = "hash"
        warnings = []
        try:
            from mograder.grading.integrity import validate_cell_hashes

            text = nb.read_text()
            hash_warnings = validate_cell_hashes(text)
            warnings = [str(w) for w in hash_warnings]

            # Source reinjection if release available
            release = storage.release_path(assignment)
            if release:
                from mograder.grading.integrity import fix_modified_cells

                release_text = release.read_text()
                result = fix_modified_cells(release_text, text)
                if result.fixed_source != text:
                    nb.write_text(result.fixed_source)
                integrity_level = "source"
        except Exception as e:
            warnings.append(f"Integrity check error: {e}")

        # Run notebook
        try:
            nb_result = await asyncio.to_thread(
                run_notebook, nb, timeout=120, html_dir=nb.parent
            )
            checks = [
                {
                    "label": c.label,
                    "status": c.status,
                    "details": c.details,
                }
                for c in nb_result.checks
            ]
            html_available = (
                nb_result.html_path is not None and nb_result.html_path.exists()
            )
            return {
                "checks": checks,
                "cell_errors": nb_result.cell_errors,
                "export_ok": nb_result.export_ok,
                "export_error": nb_result.export_error,
                "html_available": html_available,
                "integrity_level": integrity_level,
                "integrity_warnings": warnings,
            }
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"detail": f"Validation failed: {e}"},
            )

    # -- Validation report (HTML preview) --

    @app.get("/validate-report/{username}/{assignment}")
    async def validate_report(request: Request, username: str, assignment: str):
        _check_owner(request, username)
        html = storage.assignment_path(username, assignment).with_suffix(".html")
        if not html.exists():
            raise HTTPException(status_code=404, detail="No validation report")
        return FileResponse(html, media_type="text/html")

    # -- Reset --

    @app.post("/reset/{username}/{assignment}")
    async def reset(request: Request, username: str, assignment: str):
        _check_owner(request, username)

        # Kill running session if any
        if (username, assignment) in session_mgr.sessions:
            await session_mgr.terminate(username, assignment)

        archive = storage.reset_to_release(username, assignment)
        status = storage.assignment_status(username, assignment)
        return {"status": "ok", "file_status": status, "archive": str(archive)}

    # -- Status --

    @app.get("/status/{username}/{assignment}")
    async def status(request: Request, username: str, assignment: str):
        _check_owner(request, username)
        file_status = storage.assignment_status(username, assignment)
        session_active = (username, assignment) in session_mgr.sessions
        has_release = storage.has_release(assignment)
        return {
            "file_status": file_status,
            "session_active": session_active,
            "has_release": has_release,
        }

    # -- Start edit session --

    @app.post("/start-edit/{username}/{assignment}")
    async def start_edit(request: Request, username: str, assignment: str):
        _check_owner(request, username)
        nb = storage.assignment_path(username, assignment)
        if not nb.exists():
            raise HTTPException(status_code=404, detail="Notebook not found")
        try:
            session = await session_mgr.get_or_spawn(username, assignment)
            return {
                "status": "ok",
                "url": f"/edit/{username}/{assignment}/",
                "port": session.port,
            }
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Notebook not found")
        except TimeoutError as e:
            raise HTTPException(status_code=504, detail=str(e))

    # -- Stop edit session --

    @app.post("/stop-edit/{username}/{assignment}")
    async def stop_edit(request: Request, username: str, assignment: str):
        _check_owner(request, username)
        killed = await session_mgr.terminate(username, assignment)
        return {"status": "ok", "terminated": killed}

    # -- List active sessions for current user --

    @app.get("/sessions")
    async def list_sessions(request: Request):
        user = request.scope.get("user", {})
        username = user.get("username", "")
        if not username:
            raise HTTPException(status_code=403, detail="Authentication required")
        result = []
        for (u, a), s in list(session_mgr.sessions.items()):
            if u != username and not user.get("is_instructor"):
                continue
            alive = s.process is not None and s.process.returncode is None
            if not alive:
                continue
            result.append(
                {
                    "username": u,
                    "assignment": a,
                    "port": s.port,
                    "url": f"edit/{u}/{a}/",
                    "last_seen": s.last_seen,
                }
            )
        return result

    # -- List assignments --

    @app.get("/assignments")
    async def list_assignments(request: Request):
        user = request.scope.get("user", {})
        if not user.get("username"):
            raise HTTPException(status_code=403, detail="Authentication required")
        username = user["username"]

        result = []
        # Assignments
        for name in storage.list_assignments():
            status = storage.assignment_status(username, name)
            has_release = storage.has_release(name)
            session_active = (username, name) in session_mgr.sessions
            result.append(
                {
                    "name": name,
                    "type": "assignment",
                    "file_status": status,
                    "has_release": has_release,
                    "session_active": session_active,
                }
            )
        # Lectures
        for name in storage.list_lectures():
            session_active = ("__lecture__", name) in session_mgr.sessions
            result.append(
                {
                    "name": name,
                    "type": "lecture",
                    "file_status": "n/a",
                    "has_release": True,
                    "session_active": session_active,
                }
            )
        return result

    # -- Start lecture run session --

    @app.post("/start-run/{lecture}")
    async def start_run(request: Request, lecture: str):
        """Start a shared ``marimo run`` session for a lecture."""
        user = request.scope.get("user", {})
        if not user.get("username"):
            raise HTTPException(status_code=403, detail="Authentication required")

        if storage.item_type(lecture) != "lecture":
            raise HTTPException(status_code=400, detail="Not a lecture")

        try:
            session = await session_mgr.get_or_spawn_run(lecture)
            return {
                "status": "ok",
                "url": f"/run/{lecture}/",
                "port": session.port,
            }
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Lecture not found")
        except TimeoutError as e:
            raise HTTPException(status_code=504, detail=str(e))

    # -- Mark exported --

    @app.post("/mark-exported/{username}/{assignment}")
    async def mark_exported(request: Request, username: str, assignment: str):
        _check_owner(request, username)
        storage.mark_exported(username, assignment)
        return {"status": "ok"}

    # -- Release download --

    @app.get("/release/{assignment}/{filename:path}")
    async def release_download(request: Request, assignment: str, filename: str):
        # Any authenticated user can download releases
        user = request.scope.get("user", {})
        if not user.get("username"):
            raise HTTPException(status_code=403, detail="Authentication required")

        if ".." in filename:
            raise HTTPException(status_code=400, detail="Invalid filename")

        if not rel_dir.is_dir():
            raise HTTPException(status_code=404, detail="No releases available")

        file_path = rel_dir / assignment / filename
        # Safety: verify resolved path stays under release_dir
        try:
            resolved = file_path.resolve()
            if not str(resolved).startswith(str(rel_dir.resolve())):
                raise HTTPException(status_code=400, detail="Path traversal")
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid path")

        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        return FileResponse(file_path)

    # -- Publish (instructor only) --

    @app.post("/publish/{assignment}")
    async def publish(request: Request, assignment: str, files: list[UploadFile] = []):
        user = request.scope.get("user", {})
        if not user.get("is_instructor"):
            raise HTTPException(status_code=403, detail="Instructor access required")

        # Read item type from query params (default: "assignment")
        item_type = request.query_params.get("type", "assignment")

        assignment_dir = rel_dir / assignment
        assignment_dir.mkdir(parents=True, exist_ok=True)

        for f in files:
            content = await f.read()
            if f.filename:
                target = assignment_dir / f.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)

        # Build manifest from directory (excluding files.json and dotfiles)
        all_files = sorted(
            p.name
            for p in assignment_dir.iterdir()
            if p.is_file() and not p.name.startswith(".") and p.name != "files.json"
        )
        manifest = {"files": all_files, "type": item_type}
        (assignment_dir / "files.json").write_text(json.dumps(manifest, indent=2))

        # Auto-warm cache for the published notebook
        nb = assignment_dir / f"{assignment}.py"
        if nb.exists():
            from mograder.hub.spawner import warm_notebook_cache

            try:
                await asyncio.to_thread(warm_notebook_cache, nb)
            except Exception as e:
                log.warning("warm-cache failed for %s: %s", assignment, e)

        return {"status": "ok", "files": all_files, "type": item_type}

    # -- Warm cache --

    @app.post("/warm-cache")
    async def warm_cache(request: Request):
        user = request.scope.get("user", {})
        if not user.get("is_instructor"):
            raise HTTPException(status_code=403, detail="Instructor access required")

        from mograder.hub.spawner import warm_notebook_cache

        notebooks = []
        if rel_dir.is_dir():
            for d in sorted(rel_dir.iterdir()):
                if d.is_dir():
                    nb = d / f"{d.name}.py"
                    if nb.is_file():
                        notebooks.append(nb)

        warmed = []
        for nb in notebooks:
            try:
                await asyncio.to_thread(warm_notebook_cache, nb)
                warmed.append(nb.stem)
            except Exception as e:
                log.warning("warm-cache failed for %s: %s", nb.stem, e)

        return {"status": "ok", "warmed": warmed}

    # -- Sync allowed users --

    @app.post("/sync-users")
    async def sync_users(request: Request):
        user = request.scope.get("user", {})
        if not user.get("is_instructor"):
            raise HTTPException(status_code=403, detail="Instructor access required")

        body = await request.json()
        users = body.get("users", [])
        if not isinstance(users, list):
            raise HTTPException(status_code=400, detail="'users' must be a list")

        # Write allowed_users.txt
        allowed_path = course_dir / ALLOWED_USERS_FILE
        lines = sorted(set(u.strip() for u in users if u.strip()))
        allowed_path.write_text(
            "# Allowed users — managed by mograder sync-users\n"
            + "\n".join(lines)
            + "\n"
        )
        log.info("sync-users: wrote %d users to %s", len(lines), allowed_path)
        return {"status": "ok", "count": len(lines)}

    # -- Intercept /api/status for marimo dashboard --
    # marimo's /api/status requires "edit" permission but run-mode only
    # grants "read", causing a 401 that breaks the JS client.  Return a
    # minimal status response so the dashboard loads.

    @app.get("/api/status")
    async def marimo_status(request: Request):
        return {"status": "ok", "mode": "run", "sessions": 0}

    # -- Mount workshop routes for workshop assignments --
    # Workshop assignments are identified by having a keys_all.json file
    if rel_dir.is_dir():
        from mograder.transport.workshop import generate_dashboard_html
        from mograder.transport.workshop_server import (
            create_workshop_starlette_routes,
        )

        for _ws_dir in sorted(rel_dir.iterdir()):
            _keys_all_path = _ws_dir / "keys_all.json"
            if _ws_dir.is_dir() and _keys_all_path.is_file():
                _keys_all = json.loads(_keys_all_path.read_text())
                _keys_path = _ws_dir / "keys.json"
                if not _keys_path.exists():
                    _keys_path.write_text("{}")
                # Generate dashboard HTML for instructor control
                (_ws_dir / "dashboard.html").write_text(
                    generate_dashboard_html(list(_keys_all.keys()))
                )
                _ws_app = create_workshop_starlette_routes(
                    export_dir=_ws_dir,
                    keys_path=_keys_path,
                    keys_all=_keys_all,
                    secret=secret,
                )
                app.mount(f"/workshop/{_ws_dir.name}", _ws_app)
                log.info("Mounted workshop routes for %s", _ws_dir.name)

    # -- Mount student dashboard at / --
    # Explicit API routes above take priority over this catch-all mount.
    os.environ["MOGRADER_HUB_MODE"] = "1"
    import marimo

    from mograder.core.edit_sessions import MarimoOptimizeMiddleware

    _student_app_path = str(Path(__file__).parent / "student_app.py")
    _builder = marimo.create_asgi_app(quiet=True, token="")
    _builder = _builder.with_app(
        path="/",
        root=_student_app_path,
        middleware=[MarimoOptimizeMiddleware],
    )
    _dashboard = _builder.build()
    app.mount("/", _dashboard)

    return app


# Module-level app for uvicorn entry point
_course_dir = Path(os.environ.get("MOGRADER_COURSE_DIR", "."))
_dev = os.environ.get("MOGRADER_HUB_DEV") == "1"

try:
    app = create_hub_app(_course_dir, dev=_dev)
except Exception:
    # Allow import to succeed even without proper config
    app = None
