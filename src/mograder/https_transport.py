"""HTTPS transport — fetches/submits assignments via a simple HTTP server."""

from __future__ import annotations

from pathlib import Path

import requests

from mograder.models import RemoteAssignment, RemoteStatus, RemoteSubmission


class HTTPSTransport:
    """Transport backed by the mograder HTTPS assignment server."""

    def __init__(self, base_url: str, user: str = "", token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.user = user
        self.token = token

    def _headers(self) -> dict[str, str]:
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}

    def list_assignments(self) -> list[RemoteAssignment]:
        resp = requests.get(
            f"{self.base_url}/assignments", headers=self._headers(), timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            RemoteAssignment(
                name=a["name"],
                id=str(a.get("id", a["name"])),
                files=[
                    {
                        "filename": f["filename"],
                        "url": f"{self.base_url}{f['url']}"
                        if f["url"].startswith("/")
                        else f["url"],
                    }
                    for f in a.get("files", [])
                ],
                duedate=a.get("duedate", 0),
            )
            for a in data
        ]

    def download_file(self, url: str, dest: Path) -> Path:
        resp = requests.get(url, headers=self._headers(), stream=True, timeout=60)
        resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return dest

    def submit_file(self, assignment: str, filepath: Path) -> None:
        with open(filepath, "rb") as f:
            resp = requests.post(
                f"{self.base_url}/assignments/{assignment}/submit",
                params={"user": self.user},
                files={"file": (filepath.name, f)},
                headers=self._headers(),
                timeout=60,
            )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(data["error"])

    def get_submissions(self, assignment: str) -> list[RemoteSubmission]:
        resp = requests.get(
            f"{self.base_url}/assignments/{assignment}/submissions",
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            RemoteSubmission(
                userid=s.get("userid", s.get("username", "")),
                username=s["username"],
                filename=s["filename"],
                url=f"{self.base_url}{s['url']}"
                if s["url"].startswith("/")
                else s["url"],
                status=s.get("status", "submitted"),
            )
            for s in data
        ]

    def upload_grades(
        self,
        assignment: str,
        grades: list[dict],
        workflow_state: str = "",
    ) -> None:
        resp = requests.post(
            f"{self.base_url}/assignments/{assignment}/grades",
            json={"grades": grades, "workflow_state": workflow_state},
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(data["error"])

    def get_status(self, assignment: str) -> RemoteStatus:
        resp = requests.get(
            f"{self.base_url}/assignments/{assignment}/status",
            params={"user": self.user},
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return RemoteStatus(
            status=data.get("status", "new"),
            graded=data.get("graded", False),
            grade=data.get("grade"),
            feedback=data.get("feedback", ""),
        )
