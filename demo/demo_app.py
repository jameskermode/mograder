"""Combined ASGI app serving grader UI and assignment API.

Environment variables:
    MOGRADER_COURSE_DIR       — course directory for grader (default: ".")
    MOGRADER_WORKSHOP_DIR     — workshop export directory (optional)
    MOGRADER_WORKSHOP_SALT    — workshop encryption salt (optional)
    MOGRADER_WORKSHOP_SECRET  — workshop dashboard token (optional, auto-generated)
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

import marimo

logger = logging.getLogger(__name__)

# Formgrader marimo app
grader_path = str(
    Path(__file__).parent / ".." / "src" / "mograder" / "grader_app.py"
)
server = marimo.create_asgi_app(include_code=True)
server = server.with_app(path="/", root=grader_path)

# Check if we should also serve the assignment API
course_dir = Path(os.environ.get("MOGRADER_COURSE_DIR", "."))

if (course_dir / "release").is_dir():
    from mograder.transport.https_server import create_starlette_routes

    api_app = create_starlette_routes(
        course_dir,
        release_dir=course_dir / "release",
        submitted_dir=course_dir / "submitted",
        grades_dir=course_dir / ".mograder" / "server",
        secret=None,
    )
    marimo_app = server.build()

    mograder_bin = str(Path(sys.executable).parent / "mograder")

    def _run_autograde(assignment: str, username: str):
        """Run autograde for a single submission in a subprocess."""
        submitted = course_dir / "submitted" / assignment / f"{username}.py"
        source_dir = course_dir / "source" / assignment
        source_candidates = list(source_dir.glob("*.py")) if source_dir.is_dir() else []
        if not submitted.is_file() or not source_candidates:
            return
        source = source_candidates[0]
        cmd = [
            mograder_bin,
            "autograde",
            str(submitted),
            "--source",
            str(source),
            "--force",
            "--safety-check",
        ]
        logger.info("Autograding %s/%s: %s", assignment, username, " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(course_dir),
            )
            if result.returncode == 0:
                logger.info("Autograde OK: %s/%s", assignment, username)
            else:
                logger.warning(
                    "Autograde failed: %s/%s\n%s", assignment, username, result.stderr
                )
        except Exception:
            logger.exception("Autograde error: %s/%s", assignment, username)

    # Optional workshop routes
    workshop_app = None
    workshop_dir = os.environ.get("MOGRADER_WORKSHOP_DIR")
    if workshop_dir:
        import json
        import secrets

        from mograder.transport.workshop_server import create_workshop_starlette_routes

        _ws_dir = Path(workshop_dir)
        _ws_keys_all_path = _ws_dir / "keys_all.json"
        if _ws_keys_all_path.is_file():
            _ws_keys_all = json.loads(_ws_keys_all_path.read_text())
            _ws_salt = os.environ.get("MOGRADER_WORKSHOP_SALT", "workshop")
            _ws_secret = os.environ.get(
                "MOGRADER_WORKSHOP_SECRET", secrets.token_urlsafe(16)
            )
            _ws_keys_path = _ws_dir / "keys.json"

            # Generate dashboard HTML
            from mograder.transport.workshop import generate_dashboard_html

            (_ws_dir / "dashboard.html").write_text(
                generate_dashboard_html(list(_ws_keys_all.keys()))
            )

            workshop_app = create_workshop_starlette_routes(
                export_dir=_ws_dir,
                keys_path=_ws_keys_path,
                keys_all=_ws_keys_all,
                secret=_ws_secret,
            )
            logger.info("Workshop dashboard secret: %s", _ws_secret)

    from starlette.types import Receive, Scope, Send

    async def _router(scope: Scope, receive: Receive, send: Send):
        """Route requests to API, workshop, or grader."""
        path = scope.get("path", "")
        if scope["type"] in ("http", "websocket"):
            # Workshop routes
            if workshop_app and (
                path.startswith("/workshop/")
                or path == "/keys.json"
                or path == "/dashboard.html"
            ):
                await workshop_app(scope, receive, send)
                return

            if path == "/mograder.toml":
                body = (
                    'title = "mograder demo"\n'
                    'transport = "https"\n'
                    'config_url = "https://mograder-demo.jrkermode.uk/mograder.toml"\n'
                    "\n"
                    "[https]\n"
                    'url = "https://mograder-demo.jrkermode.uk"\n'
                ).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [
                            [b"content-type", b"application/toml; charset=utf-8"],
                            [b"content-length", str(len(body)).encode()],
                            [b"access-control-allow-origin", b"*"],
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return

            if path.startswith("/assignments") or path == "/register":
                # Intercept submit responses to trigger autograde
                if "/submit" in path and scope.get("method") == "POST":
                    # Capture the response status
                    response_started = False
                    response_status = 0

                    async def send_wrapper(message):
                        nonlocal response_started, response_status
                        if message["type"] == "http.response.start":
                            response_started = True
                            response_status = message.get("status", 0)
                        await send(message)

                    await api_app(scope, receive, send_wrapper)
                    # Trigger autograde in background if submit succeeded
                    if response_started and 200 <= response_status < 300:
                        parts = path.strip("/").split("/")
                        # /assignments/<name>/submit?user=<u>
                        if len(parts) >= 3:
                            assignment = parts[1]
                            qs = scope.get("query_string", b"").decode()
                            user = ""
                            for param in qs.split("&"):
                                if param.startswith("user="):
                                    user = param[5:]
                            if user:
                                loop = asyncio.get_event_loop()
                                loop.run_in_executor(
                                    None, _run_autograde, assignment, user
                                )
                    return
                await api_app(scope, receive, send)
                return
        await marimo_app(scope, receive, send)

    app = _router

else:
    app = server.build()
