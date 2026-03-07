"""Moodle REST Web Services API client for mograder."""

from __future__ import annotations

import json
import os
from pathlib import Path

import click
import requests


class MoodleAPIError(Exception):
    """Raised when a Moodle API call returns an error."""

    def __init__(self, message: str, error_code: str | None = None):
        self.error_code = error_code
        super().__init__(message)


class MoodleAPIClient:
    """Client for Moodle's REST Web Services API."""

    def __init__(self, url: str, token: str):
        self.base_url = url.rstrip("/")
        self.endpoint = f"{self.base_url}/webservice/rest/server.php"
        self.upload_endpoint = f"{self.base_url}/webservice/upload.php"
        self.token = token

    def _call(self, wsfunction: str, **params) -> dict | list:
        """Make a Moodle web service API call."""
        data = {
            "wstoken": self.token,
            "moodlewsrestformat": "json",
            "wsfunction": wsfunction,
            **params,
        }
        resp = requests.post(self.endpoint, data=data, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        if isinstance(result, dict) and "exception" in result:
            raise MoodleAPIError(
                result.get("message", result.get("exception", "Unknown error")),
                error_code=result.get("errorcode"),
            )
        return result

    def get_site_info(self) -> dict:
        """Get site info for the authenticated user.

        Returns dict with: userid, username, fullname, sitename.
        """
        result = self._call("core_webservice_get_site_info")
        return {
            "userid": result["userid"],
            "username": result["username"],
            "fullname": result["fullname"],
            "sitename": result["sitename"],
        }

    def get_assignments(self, course_id: int) -> list[dict]:
        """Get assignments for a course.

        Returns a flat list of assignment dicts with keys:
        id, name, duedate, introattachments.
        """
        result = self._call("mod_assign_get_assignments", **{"courseids[0]": course_id})
        assignments = []
        for course in result.get("courses", []):
            for assign in course.get("assignments", []):
                assignments.append(
                    {
                        "id": assign["id"],
                        "name": assign["name"],
                        "duedate": assign.get("duedate", 0),
                        "introattachments": assign.get("introattachments", []),
                    }
                )
        return assignments

    def get_assignment_files(self, assignment_id: int) -> list[dict]:
        """Get files attached to an assignment's description.

        Returns list of {filename, fileurl, filesize}.
        """
        # We need to call get_assignments and filter — Moodle doesn't have
        # a get-single-assignment endpoint, but the data is already cached
        # by the caller via get_assignments/find_assignment.
        # This method is for when we already have the assignment dict.
        raise NotImplementedError(
            "Use the introattachments from the assignment dict directly"
        )

    def download_file(self, file_url: str, dest: Path) -> Path:
        """Download a file from Moodle, appending the token for auth."""
        sep = "&" if "?" in file_url else "?"
        authed_url = f"{file_url}{sep}token={self.token}"
        resp = requests.get(authed_url, stream=True, timeout=60)
        resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return dest

    def upload_file(self, filepath: Path) -> int:
        """Upload a file to the user's draft area.

        Returns the draft area itemid.
        """
        with open(filepath, "rb") as f:
            resp = requests.post(
                self.upload_endpoint,
                params={"token": self.token},
                files={"file_1": (filepath.name, f)},
                data={"itemid": 0},
                timeout=60,
            )
        resp.raise_for_status()
        result = resp.json()
        if isinstance(result, dict) and "exception" in result:
            raise MoodleAPIError(
                result.get("message", "Upload failed"),
                error_code=result.get("errorcode"),
            )
        return result[0]["itemid"]

    def save_submission(self, assignment_id: int, item_id: int) -> None:
        """Save a file submission draft for an assignment."""
        self._call(
            "mod_assign_save_submission",
            assignmentid=assignment_id,
            **{
                "plugindata[files_filemanager]": item_id,
            },
        )

    def submit_for_grading(self, assignment_id: int) -> None:
        """Finalize a submission so it's visible to graders."""
        self._call(
            "mod_assign_submit_for_grading",
            assignmentid=assignment_id,
            acceptsubmissionstatement=1,
        )

    def get_submissions(self, assignment_id: int) -> list[dict]:
        """Get all submissions for an assignment.

        Returns list of dicts with keys: userid, status, files.
        Each file has: filename, fileurl, filesize.
        """
        result = self._call(
            "mod_assign_get_submissions", **{"assignmentids[0]": assignment_id}
        )
        submissions = []
        for assign in result.get("assignments", []):
            for sub in assign.get("submissions", []):
                files = []
                for plugin in sub.get("plugins", []):
                    if plugin.get("type") == "file":
                        for filearea in plugin.get("fileareas", []):
                            for f in filearea.get("files", []):
                                files.append(
                                    {
                                        "filename": f["filename"],
                                        "fileurl": f["fileurl"],
                                        "filesize": f.get("filesize", 0),
                                    }
                                )
                submissions.append(
                    {
                        "userid": sub["userid"],
                        "status": sub.get("status", ""),
                        "files": files,
                    }
                )
        return submissions

    def list_participants(self, assignment_id: int) -> list[dict]:
        """List participants for an assignment.

        Returns list of {id, username, fullname}.
        """
        result = self._call(
            "mod_assign_list_participants",
            assignid=assignment_id,
            groupid=0,
            filter="",
        )
        return [
            {
                "id": p["id"],
                "username": p.get("username", ""),
                "fullname": p.get("fullname", ""),
            }
            for p in result
        ]

    def save_grades(
        self,
        assignment_id: int,
        grades: list[dict],
    ) -> None:
        """Save grades for multiple students.

        Each grade dict should have: userid, grade, feedback (text).
        """
        params: dict = {
            "assignmentid": assignment_id,
        }
        for i, g in enumerate(grades):
            params[f"grades[{i}][userid]"] = g["userid"]
            params[f"grades[{i}][grade]"] = g["grade"]
            params[f"grades[{i}][attemptnumber]"] = g.get("attemptnumber", -1)
            params[f"grades[{i}][addattempt]"] = 0
            params[f"grades[{i}][workflowstate]"] = ""
            params[f"grades[{i}][plugindata][assignfeedbackcomments_editor][text]"] = (
                g.get("feedback", "")
            )
            params[
                f"grades[{i}][plugindata][assignfeedbackcomments_editor][format]"
            ] = 1  # HTML
        self._call("mod_assign_save_grades", **params)


def resolve_credentials(
    cli_url: str | None,
    cli_token: str | None,
    config,
) -> tuple[str, str]:
    """Resolve Moodle URL and token from CLI flags, env vars, or config.

    Priority: CLI flag > environment variable > config file.
    """
    url = (
        cli_url
        or os.environ.get("MOGRADER_MOODLE_URL")
        or getattr(config, "moodle_url", None)
    )
    token = cli_token or os.environ.get("MOGRADER_MOODLE_TOKEN")

    if not url:
        raise click.UsageError(
            "Moodle URL not set. Provide --url, set MOGRADER_MOODLE_URL, "
            "or add url to [moodle] in mograder.toml"
        )
    if not token:
        raise click.UsageError(
            "Moodle token not set. Provide --token or set MOGRADER_MOODLE_TOKEN"
        )

    if url.startswith("http://"):
        click.echo("WARNING: using HTTP — consider HTTPS for security", err=True)

    return url, token


def find_assignment(
    client: MoodleAPIClient,
    course_id: int,
    name: str,
) -> dict:
    """Find an assignment by name within a course.

    Tries exact match first, then case-insensitive substring.
    Raises click.UsageError if no match or ambiguous.
    """
    assignments = client.get_assignments(course_id)
    if not assignments:
        raise click.UsageError(f"No assignments found for course {course_id}")

    # Try exact match
    exact = [a for a in assignments if a["name"] == name]
    if len(exact) == 1:
        return exact[0]

    # Try numeric ID
    try:
        aid = int(name)
        by_id = [a for a in assignments if a["id"] == aid]
        if len(by_id) == 1:
            return by_id[0]
    except ValueError:
        pass

    # Try case-insensitive substring
    lower = name.lower()
    matches = [a for a in assignments if lower in a["name"].lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = "\n  ".join(a["name"] for a in matches)
        raise click.UsageError(
            f"Ambiguous assignment name '{name}'. Matches:\n  {names}"
        )

    names = "\n  ".join(a["name"] for a in assignments)
    raise click.UsageError(f"No assignment matching '{name}'. Available:\n  {names}")


# ---------------------------------------------------------------------------
# Token authentication and caching
# ---------------------------------------------------------------------------

TOKEN_CACHE = Path.home() / ".config" / "mograder" / "token.json"


def request_token(
    url: str,
    username: str,
    password: str,
    service: str = "moodle_mobile_app",
) -> str:
    """Exchange username/password for a web service token via /login/token.php.

    Returns the token string.  Raises ``MoodleAPIError`` on failure.
    """
    resp = requests.post(
        f"{url.rstrip('/')}/login/token.php",
        data={"username": username, "password": password, "service": service},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "token" not in data:
        raise MoodleAPIError(
            data.get("error", "Login failed"),
            error_code=data.get("errorcode"),
        )
    return data["token"]


def load_cached_token(url: str) -> dict | None:
    """Load a cached token for *url* from ``~/.config/mograder/token.json``.

    Returns ``{"url", "token", "fullname"}`` if the URL matches, else ``None``.
    """
    if not TOKEN_CACHE.is_file():
        return None
    try:
        data = json.loads(TOKEN_CACHE.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if data.get("url") == url.rstrip("/"):
        return data
    return None


def save_cached_token(url: str, token: str, fullname: str) -> None:
    """Persist a token to ``~/.config/mograder/token.json``."""
    TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_CACHE.write_text(
        json.dumps({"url": url.rstrip("/"), "token": token, "fullname": fullname})
    )


def clear_cached_token() -> None:
    """Remove the cached token file."""
    TOKEN_CACHE.unlink(missing_ok=True)
