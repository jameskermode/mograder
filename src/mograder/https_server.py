"""Lightweight HTTP server for assignment distribution and submission.

Serves from a directory structure::

    server_root/
      assignments.json                         <- manifest
      <assignment>/
        files/
          <filename>.py                        <- assignment files
        grades.json                            <- uploaded grades

    submitted_dir/  (defaults to server_root if not specified)
      <assignment>/
        <user>_<timestamp>.py                  <- timestamped submissions
        <user>.py -> <user>_<timestamp>.py     <- symlink to latest

Endpoints::

    GET  /assignments                              -> JSON manifest
    GET  /assignments/<name>/files/<file>          -> download file
    POST /assignments/<name>/submit?user=<u>       -> upload .py (multipart)
    GET  /assignments/<name>/submissions           -> list submissions JSON
    POST /assignments/<name>/grades                -> upload grades JSON
    GET  /assignments/<name>/status?user=<u>       -> submission status JSON
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Regex to detect timestamped submission stems like alice_20260310T200800
_TIMESTAMP_RE = re.compile(r"_\d{8}T\d{6}$")


def _write_submission(target_dir: Path, user: str, file_data: bytes) -> Path:
    """Atomically write a timestamped submission and update the symlink.

    Returns the path to the timestamped file.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    timestamped = target_dir / f"{user}_{ts}.py"
    symlink = target_dir / f"{user}.py"

    # 1. Write to temp file in same dir (same filesystem for atomic rename)
    fd, tmp = tempfile.mkstemp(dir=target_dir, suffix=".py")
    try:
        os.write(fd, file_data)
    finally:
        os.close(fd)
    # 2. Rename temp → timestamped name (atomic on same FS)
    os.rename(tmp, timestamped)
    # 3. Create symlink atomically: make temp symlink, then rename over real one
    tmp_link = timestamped.with_suffix(".py.lnk")
    os.symlink(timestamped.name, tmp_link)  # relative symlink
    os.rename(str(tmp_link), str(symlink))  # atomic replace
    return timestamped


class AssignmentHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the assignment server."""

    server: AssignmentServer  # type: ignore[assignment]

    def log_message(self, format, *args):
        """Suppress default logging."""

    @property
    def root(self) -> Path:
        return self.server.root_dir

    def _add_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._add_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path):
        if not path.is_file():
            self._send_error(404, f"Not found: {path.name}")
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self._add_cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def _send_error(self, status, message):
        self._send_json({"error": message}, status=status)

    def _authenticate(self) -> str | None:
        """Verify the Authorization header. Returns username or None.

        When the server has no secret (no-auth mode), returns ``""``.
        """
        if self.server.secret is None:
            return ""
        from mograder.auth import verify_token

        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return None
        return verify_token(self.server.secret, auth[7:])

    def _require_auth(self) -> str | None:
        """Return username or send 401 and return None."""
        user = self._authenticate()
        if user is None:
            self._send_error(401, "Authentication required")
            return None
        return user

    def _require_instructor(self) -> bool:
        """Return True if authenticated as instructor, else send error."""
        from mograder.auth import is_instructor

        user = self._require_auth()
        if user is None:
            return False
        if self.server.secret is not None and not is_instructor(user):
            self._send_error(403, "Instructor access required")
            return False
        return True

    def _require_user_match(self, target_user: str) -> bool:
        """Return True if token user matches *target_user* or is instructor."""
        from mograder.auth import is_instructor

        user = self._require_auth()
        if user is None:
            return False
        if (
            self.server.secret is not None
            and user != target_user
            and not is_instructor(user)
        ):
            self._send_error(403, "Token user does not match request user")
            return False
        return True

    def do_OPTIONS(self):
        self.send_response(204)
        self._add_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = parse_qs(parsed.query)

        if path in ("", "/"):
            self._send_json({"status": "ok"})
        elif path == "/assignments":
            if self._require_auth() is None:
                return
            self._handle_list_assignments()
        elif path.startswith("/assignments/"):
            parts = path.split("/")
            # /assignments/<name>/files/<file>
            if len(parts) == 5 and parts[3] == "files":
                if self._require_auth() is None:
                    return
                self._handle_download_file(parts[2], parts[4])
            # /assignments/<name>/submissions/<file>
            elif len(parts) == 5 and parts[3] == "submissions":
                if not self._require_instructor():
                    return
                self._handle_download_submission(parts[2], parts[4])
            # /assignments/<name>/submissions
            elif len(parts) == 4 and parts[3] == "submissions":
                if not self._require_instructor():
                    return
                self._handle_list_submissions(parts[2])
            # /assignments/<name>/status
            elif len(parts) == 4 and parts[3] == "status":
                user = qs.get("user", [None])[0]
                if user and not self._require_user_match(user):
                    return
                self._handle_status(parts[2], user)
            else:
                self._send_error(404, "Not found")
        else:
            self._send_error(404, "Not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = parse_qs(parsed.query)

        if not path.startswith("/assignments/"):
            self._send_error(404, "Not found")
            return

        parts = path.split("/")
        # /assignments/<name>/submit
        if len(parts) == 4 and parts[3] == "submit":
            user = qs.get("user", [None])[0]
            if user and not self._require_user_match(user):
                return
            self._handle_submit(parts[2], user)
        # /assignments/<name>/grades
        elif len(parts) == 4 and parts[3] == "grades":
            if not self._require_instructor():
                return
            self._handle_upload_grades(parts[2])
        else:
            self._send_error(404, "Not found")

    def _handle_list_assignments(self):
        manifest_path = self.root / "assignments.json"
        if manifest_path.is_file():
            data = json.loads(manifest_path.read_text())
        else:
            # Auto-discover from directory structure
            data = []
            for d in sorted(self.root.iterdir()):
                if d.is_dir() and (d / "files").is_dir():
                    files = []
                    for f in sorted((d / "files").iterdir()):
                        if f.is_file():
                            files.append(
                                {
                                    "filename": f.name,
                                    "url": f"/assignments/{d.name}/files/{f.name}",
                                }
                            )
                    data.append({"name": d.name, "id": d.name, "files": files})
        self._send_json(data)

    def _handle_download_file(self, assignment: str, filename: str):
        file_path = self.root / assignment / "files" / filename
        self._send_file(file_path)

    def _handle_download_submission(self, assignment: str, filename: str):
        file_path = self.server.submitted_dir / assignment / filename
        self._send_file(file_path)

    def _handle_submit(self, assignment: str, user: str | None):
        if not user:
            self._send_error(400, "Missing 'user' query parameter")
            return

        content_type = self.headers.get("Content-Type", "")
        content_length = int(self.headers.get("Content-Length", 0))

        if "multipart/form-data" in content_type:
            # Parse multipart — simple extraction
            body = self.rfile.read(content_length)
            # Find boundary
            boundary = content_type.split("boundary=")[1].strip()
            file_data = _extract_multipart_file(body, boundary.encode())
        else:
            # Raw body upload
            file_data = self.rfile.read(content_length)

        if not file_data:
            self._send_error(400, "No file data received")
            return

        target_dir = self.server.submitted_dir / assignment
        _write_submission(target_dir, user, file_data)
        self._send_json({"status": "ok", "filename": f"{user}.py"})

    def _handle_list_submissions(self, assignment: str):
        sub_dir = self.server.submitted_dir / assignment
        result = []
        if sub_dir.is_dir():
            for f in sorted(sub_dir.iterdir()):
                if f.suffix == ".py" and not _TIMESTAMP_RE.search(f.stem):
                    result.append(
                        {
                            "username": f.stem,
                            "filename": f.name,
                            "url": f"/assignments/{assignment}/submissions/{f.name}",
                        }
                    )
        self._send_json(result)

    def _handle_upload_grades(self, assignment: str):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            grades_data = json.loads(body)
        except json.JSONDecodeError:
            self._send_error(400, "Invalid JSON")
            return

        grades_path = self.root / assignment / "grades.json"
        grades_path.parent.mkdir(parents=True, exist_ok=True)

        # Merge with existing grades if any
        existing = []
        if grades_path.is_file():
            existing = json.loads(grades_path.read_text())

        # Replace or add grades by userid
        existing_map = {g.get("userid", g.get("username", "")): g for g in existing}
        for g in grades_data.get(
            "grades", grades_data if isinstance(grades_data, list) else []
        ):
            key = g.get("userid", g.get("username", ""))
            existing_map[key] = g
        grades_path.write_text(json.dumps(list(existing_map.values()), indent=2))
        self._send_json({"status": "ok", "count": len(existing_map)})

    def _handle_status(self, assignment: str, user: str | None):
        if not user:
            self._send_error(400, "Missing 'user' query parameter")
            return

        sub_dir = self.server.submitted_dir / assignment
        submitted = (sub_dir / f"{user}.py").exists() if sub_dir.is_dir() else False

        grades_path = self.root / assignment / "grades.json"
        grade = None
        feedback_text = ""
        graded = False
        if grades_path.is_file():
            grades = json.loads(grades_path.read_text())
            for g in grades:
                if g.get("username") == user or g.get("userid") == user:
                    graded = True
                    grade = str(g.get("grade", ""))
                    feedback_text = g.get("feedback", "")
                    break

        self._send_json(
            {
                "status": "submitted" if submitted else "new",
                "graded": graded,
                "grade": grade,
                "feedback": feedback_text,
            }
        )


class AssignmentServer(HTTPServer):
    """HTTPServer subclass that stores the root directory."""

    def __init__(
        self,
        root_dir: Path,
        server_address,
        handler_class,
        submitted_dir: Path | None = None,
        secret: str | None = None,
    ):
        self.root_dir = root_dir
        self.submitted_dir = submitted_dir if submitted_dir is not None else root_dir
        self.secret = secret
        super().__init__(server_address, handler_class)


def _extract_multipart_file(body: bytes, boundary: bytes) -> bytes | None:
    """Extract file content from a multipart/form-data body."""
    parts = body.split(b"--" + boundary)
    for part in parts:
        if b"filename=" in part:
            # Find double CRLF separating headers from content
            header_end = part.find(b"\r\n\r\n")
            if header_end == -1:
                continue
            content = part[header_end + 4 :]
            # Strip trailing CRLF
            if content.endswith(b"\r\n"):
                content = content[:-2]
            return content
    return None


def create_server(
    root_dir: Path,
    host: str = "127.0.0.1",
    port: int = 0,
    submitted_dir: Path | None = None,
    secret: str | None = None,
) -> AssignmentServer:
    """Create an AssignmentServer on *host*:*port*.

    Use ``port=0`` to let the OS pick a free port.
    The actual port is available as ``server.server_address[1]``.

    If *secret* is given, all endpoints require a valid HMAC token.
    """
    server = AssignmentServer(
        root_dir,
        (host, port),
        AssignmentHandler,
        submitted_dir=submitted_dir,
        secret=secret,
    )
    return server


def run_server_background(
    root_dir: Path,
    host: str = "127.0.0.1",
    port: int = 0,
    secret: str | None = None,
    submitted_dir: Path | None = None,
) -> tuple[AssignmentServer, threading.Thread]:
    """Start a server in a daemon thread. Returns (server, thread)."""
    server = create_server(
        root_dir, host, port, submitted_dir=submitted_dir, secret=secret
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def create_starlette_routes(
    root_dir: Path,
    submitted_dir: Path | None = None,
    secret: str | None = None,
):
    """Create a Starlette app serving the assignment API.

    Same endpoints as ``AssignmentHandler`` but as async Starlette routes.
    Import is deferred so the stdlib server path doesn't require starlette.

    Submissions are written atomically to
    ``submitted_dir/<assignment>/<user>_<timestamp>.py`` with a symlink
    ``<user>.py`` pointing to the latest.  Defaults to *root_dir* if
    *submitted_dir* is not given.

    If *secret* is given, all endpoints require a valid HMAC token.
    """
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Route

    root = root_dir.resolve()
    resolved_submitted_dir = (
        submitted_dir if submitted_dir is not None else root_dir
    ).resolve()

    def _cors(response: Response) -> Response:
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response

    def _json(data, status=200):
        return _cors(JSONResponse(data, status_code=status))

    def _file(path: Path):
        if not path.is_file():
            return _json({"error": f"Not found: {path.name}"}, 404)
        return _cors(Response(path.read_bytes(), media_type="application/octet-stream"))

    def _auth_user(request: Request) -> str | None:
        """Verify token, return username or None."""
        if secret is None:
            return ""
        from mograder.auth import verify_token

        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return None
        return verify_token(secret, auth[7:])

    def _check_auth(request: Request) -> Response | None:
        """Return error response if not authenticated, else None."""
        if _auth_user(request) is None:
            return _json({"error": "Authentication required"}, 401)
        return None

    def _check_instructor(request: Request) -> Response | None:
        """Return error response if not instructor, else None."""
        from mograder.auth import is_instructor

        user = _auth_user(request)
        if user is None:
            return _json({"error": "Authentication required"}, 401)
        if secret is not None and not is_instructor(user):
            return _json({"error": "Instructor access required"}, 403)
        return None

    def _check_user_match(request: Request, target_user: str) -> Response | None:
        """Return error response if token user doesn't match, else None."""
        from mograder.auth import is_instructor

        user = _auth_user(request)
        if user is None:
            return _json({"error": "Authentication required"}, 401)
        if secret is not None and user != target_user and not is_instructor(user):
            return _json({"error": "Token user does not match request user"}, 403)
        return None

    async def list_assignments(request: Request):
        err = _check_auth(request)
        if err:
            return err
        manifest_path = root / "assignments.json"
        if manifest_path.is_file():
            data = json.loads(manifest_path.read_text())
        else:
            data = []
            for d in sorted(root.iterdir()):
                if d.is_dir() and (d / "files").is_dir():
                    files = []
                    for f in sorted((d / "files").iterdir()):
                        if f.is_file():
                            files.append(
                                {
                                    "filename": f.name,
                                    "url": f"/assignments/{d.name}/files/{f.name}",
                                }
                            )
                    data.append({"name": d.name, "id": d.name, "files": files})
        return _json(data)

    async def download_file(request: Request):
        err = _check_auth(request)
        if err:
            return err
        name = request.path_params["name"]
        filename = request.path_params["file"]
        return _file(root / name / "files" / filename)

    async def download_submission(request: Request):
        err = _check_instructor(request)
        if err:
            return err
        name = request.path_params["name"]
        filename = request.path_params["file"]
        return _file(resolved_submitted_dir / name / filename)

    async def submit(request: Request):
        name = request.path_params["name"]
        user = request.query_params.get("user")
        if not user:
            return _json({"error": "Missing 'user' query parameter"}, 400)
        err = _check_user_match(request, user)
        if err:
            return err

        content_type = request.headers.get("content-type", "")
        if "multipart/form-data" in content_type:
            form = await request.form()
            upload = form.get("file")
            if upload is None:
                return _json({"error": "No file data received"}, 400)
            file_data = await upload.read()
        else:
            file_data = await request.body()

        if not file_data:
            return _json({"error": "No file data received"}, 400)

        target_dir = resolved_submitted_dir / name
        _write_submission(target_dir, user, file_data)
        return _json({"status": "ok", "filename": f"{user}.py"})

    async def list_submissions(request: Request):
        err = _check_instructor(request)
        if err:
            return err
        name = request.path_params["name"]
        sub_dir = resolved_submitted_dir / name
        result = []
        if sub_dir.is_dir():
            for f in sorted(sub_dir.iterdir()):
                if f.suffix == ".py" and not _TIMESTAMP_RE.search(f.stem):
                    result.append(
                        {
                            "username": f.stem,
                            "filename": f.name,
                            "url": f"/assignments/{name}/submissions/{f.name}",
                        }
                    )
        return _json(result)

    async def upload_grades(request: Request):
        err = _check_instructor(request)
        if err:
            return err
        name = request.path_params["name"]
        body = await request.body()
        try:
            grades_data = json.loads(body)
        except json.JSONDecodeError:
            return _json({"error": "Invalid JSON"}, 400)

        grades_path = root / name / "grades.json"
        grades_path.parent.mkdir(parents=True, exist_ok=True)

        existing = []
        if grades_path.is_file():
            existing = json.loads(grades_path.read_text())

        existing_map = {g.get("userid", g.get("username", "")): g for g in existing}
        for g in grades_data.get(
            "grades", grades_data if isinstance(grades_data, list) else []
        ):
            key = g.get("userid", g.get("username", ""))
            existing_map[key] = g
        grades_path.write_text(json.dumps(list(existing_map.values()), indent=2))
        return _json({"status": "ok", "count": len(existing_map)})

    async def status(request: Request):
        name = request.path_params["name"]
        user = request.query_params.get("user")
        if not user:
            return _json({"error": "Missing 'user' query parameter"}, 400)
        err = _check_user_match(request, user)
        if err:
            return err

        sub_dir = resolved_submitted_dir / name
        submitted = (sub_dir / f"{user}.py").exists() if sub_dir.is_dir() else False

        grades_path = root / name / "grades.json"
        grade = None
        feedback_text = ""
        graded = False
        if grades_path.is_file():
            grades = json.loads(grades_path.read_text())
            for g in grades:
                if g.get("username") == user or g.get("userid") == user:
                    graded = True
                    grade = str(g.get("grade", ""))
                    feedback_text = g.get("feedback", "")
                    break

        return _json(
            {
                "status": "submitted" if submitted else "new",
                "graded": graded,
                "grade": grade,
                "feedback": feedback_text,
            }
        )

    routes = [
        Route("/assignments", list_assignments),
        Route("/assignments/{name:path}/files/{file:path}", download_file),
        Route(
            "/assignments/{name:path}/submissions/{file:path}",
            download_submission,
        ),
        Route("/assignments/{name}/submit", submit, methods=["POST"]),
        Route("/assignments/{name}/submissions", list_submissions),
        Route("/assignments/{name}/grades", upload_grades, methods=["POST"]),
        Route("/assignments/{name}/status", status),
    ]

    return Starlette(routes=routes)
