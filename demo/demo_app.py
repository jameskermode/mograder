"""Combined ASGI app serving formgrader UI and assignment API.

Environment variables:
    MOGRADER_COURSE_DIR       — course directory for formgrader (default: ".")
"""

from __future__ import annotations

import os
from pathlib import Path

import marimo

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

    from starlette.types import Receive, Scope, Send

    async def _router(scope: Scope, receive: Receive, send: Send):
        """Route requests to API or formgrader."""
        path = scope.get("path", "")
        if scope["type"] in ("http", "websocket"):
            if path.startswith("/assignments") or path == "/register":
                await api_app(scope, receive, send)
                return
        await marimo_app(scope, receive, send)

    app = _router

else:
    app = server.build()
