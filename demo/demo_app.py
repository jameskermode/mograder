"""Combined ASGI app serving formgrader UI and assignment API.

Environment variables:
    MOGRADER_COURSE_DIR       — course directory for formgrader (default: ".")
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
formgrader_path = str(
    Path(__file__).parent / ".." / "src" / "mograder" / "formgrader_app.py"
)
server = marimo.create_asgi_app(include_code=True)
server = server.with_app(path="/", root=formgrader_path)

# Check if we should also serve the assignment API
course_dir = Path(os.environ.get("MOGRADER_COURSE_DIR", "."))

if (course_dir / "release").is_dir():
    from mograder.https_server import create_starlette_routes

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

    from starlette.types import Receive, Scope, Send

    async def _router(scope: Scope, receive: Receive, send: Send):
        """Route requests to API or formgrader."""
        path = scope.get("path", "")
        if scope["type"] in ("http", "websocket"):
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
