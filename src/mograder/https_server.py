"""Lightweight HTTP server for assignment distribution and submission.

Serves from a directory structure::

    server_root/
      assignments.json                         <- manifest
      <assignment>/
        files/
          <filename>.py                        <- assignment files
        submissions/
          <username>.py                        <- submitted files
        grades.json                            <- uploaded grades

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
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class AssignmentHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the assignment server."""

    server: AssignmentServer  # type: ignore[assignment]

    def log_message(self, format, *args):
        """Suppress default logging."""

    @property
    def root(self) -> Path:
        return self.server.root_dir

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path):
        if not path.is_file():
            self.send_error(404, f"Not found: {path.name}")
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_error(self, status, message):
        self._send_json({"error": message}, status=status)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = parse_qs(parsed.query)

        if path == "/assignments":
            self._handle_list_assignments()
        elif path.startswith("/assignments/"):
            parts = path.split("/")
            # /assignments/<name>/files/<file>
            if len(parts) == 5 and parts[3] == "files":
                self._handle_download_file(parts[2], parts[4])
            # /assignments/<name>/submissions/<file>
            elif len(parts) == 5 and parts[3] == "submissions":
                self._handle_download_submission(parts[2], parts[4])
            # /assignments/<name>/submissions
            elif len(parts) == 4 and parts[3] == "submissions":
                self._handle_list_submissions(parts[2])
            # /assignments/<name>/status
            elif len(parts) == 4 and parts[3] == "status":
                user = qs.get("user", [None])[0]
                self._handle_status(parts[2], user)
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = parse_qs(parsed.query)

        if not path.startswith("/assignments/"):
            self.send_error(404)
            return

        parts = path.split("/")
        # /assignments/<name>/submit
        if len(parts) == 4 and parts[3] == "submit":
            user = qs.get("user", [None])[0]
            self._handle_submit(parts[2], user)
        # /assignments/<name>/grades
        elif len(parts) == 4 and parts[3] == "grades":
            self._handle_upload_grades(parts[2])
        else:
            self.send_error(404)

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
        file_path = self.root / assignment / "submissions" / filename
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

        sub_dir = self.root / assignment / "submissions"
        sub_dir.mkdir(parents=True, exist_ok=True)
        dest = sub_dir / f"{user}.py"
        dest.write_bytes(file_data)
        self._send_json({"status": "ok", "filename": dest.name})

    def _handle_list_submissions(self, assignment: str):
        sub_dir = self.root / assignment / "submissions"
        result = []
        if sub_dir.is_dir():
            for f in sorted(sub_dir.iterdir()):
                if f.is_file() and f.suffix == ".py":
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

        sub_dir = self.root / assignment / "submissions"
        submitted = (sub_dir / f"{user}.py").is_file() if sub_dir.is_dir() else False

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

    def __init__(self, root_dir: Path, server_address, handler_class):
        self.root_dir = root_dir
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
    root_dir: Path, host: str = "127.0.0.1", port: int = 0
) -> AssignmentServer:
    """Create an AssignmentServer on *host*:*port*.

    Use ``port=0`` to let the OS pick a free port.
    The actual port is available as ``server.server_address[1]``.
    """
    server = AssignmentServer(root_dir, (host, port), AssignmentHandler)
    return server


def run_server_background(
    root_dir: Path, host: str = "127.0.0.1", port: int = 0
) -> tuple[AssignmentServer, threading.Thread]:
    """Start a server in a daemon thread. Returns (server, thread)."""
    server = create_server(root_dir, host, port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
