"""Combined ASGI app serving formgrader UI and assignment API.

Environment variables:
    MOGRADER_COURSE_DIR  — course directory for formgrader (default: ".")
    MOGRADER_SERVE_DIR   — directory for assignment API (optional)
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
serve_dir = os.environ.get("MOGRADER_SERVE_DIR", "")

if serve_dir and Path(serve_dir).is_dir():
    from mograder.auth import load_or_create_secret
    from mograder.https_server import create_starlette_routes

    course_dir = Path(os.environ.get("MOGRADER_COURSE_DIR", "."))
    _secret = load_or_create_secret(course_dir)
    api_app = create_starlette_routes(
        Path(serve_dir),
        submitted_dir=course_dir / "submitted",
        secret=_secret,
    )
    marimo_app = server.build()

    # Route /assignments* to API, everything else to formgrader
    async def app(scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            if path.startswith("/assignments"):
                await api_app(scope, receive, send)
                return
        await marimo_app(scope, receive, send)

else:
    app = server.build()
