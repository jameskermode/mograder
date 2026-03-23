# mograder-hub: Complete Implementation Spec

This document specifies `mograder hub` — a new command that runs a
multi-user server on a cloud instance (RONIN/AWS), providing per-student
persistent Marimo edit sessions behind a university SSO proxy. It also
specifies the accompanying changes to the student dashboard.

Read `CLAUDE.md`, the existing `src/mograder/` source, and the docs at
`https://jameskermode.github.io/mograder/` before starting. Pay particular
attention to the existing FastAPI app structure (used for `mograder serve`
and `mograder formgrader`) as `mograder hub` extends the same patterns.

---

## Overview and context

### Deployment context

```
browser
  → sciml.warwick.ac.uk  (Warwick SSO gateway, injects X-Remote-User header)
      → RONIN EC2 instance
          → mograder hub (FastAPI ASGI app)
              ├── /                 student dashboard (user-aware Marimo app)
              ├── /edit/<user>/     per-student marimo edit process (proxied)
              ├── /ws/<user>/       websocket proxy for marimo reactivity
              ├── /upload/<user>/   file upload endpoint
              └── /export/<user>/   file download endpoint

moriarty (unchanged)
  → mograder formgrader  (instructor/GTA use, as now)
  → mograder autograde   (batch, triggered manually after Moodle collection)

Moodle (web UI only for students — no student API calls)
  - instructor uses existing mograder moodle fetch-submissions /
    upload-feedback as before
```

### Key design decisions

1. **No Moodle API calls from students.** Students submit to Moodle via
   the web UI (export from hub, upload to Moodle assignment page). For
   fetching assignments: when the instructor has published the release to
   the hub via `mograder hub publish`, students can download directly
   from the hub dashboard with one click — no Moodle download required.
   When no release is available on the hub, students download from Moodle
   manually and upload to the hub. Both paths avoid Moodle token
   management complexity.

2. **Auth via X-Remote-User only.** The sciml SSO proxy authenticates
   the user and injects their username as `X-Remote-User`. The hub trusts
   this header (it must only be reachable via the proxy in production).
   No passwords, no tokens, no OAuth.

3. **Session cookies for hub auth.** The hub issues a signed session
   cookie on first request (HMAC-SHA256 over `username:timestamp`, using
   `MOGRADER_HUB_SECRET`). This is the only credential in play; it
   contains no Moodle credentials.

4. **Persistent per-user notebook directories.** Student work lives in
   `{notebooks_dir}/{username}/{assignment}/` on the EBS volume. It
   persists indefinitely across logins and instance restarts.

5. **On-demand marimo edit processes.** Each student gets a `marimo edit`
   subprocess spawned when they first click Edit for an assignment. Idle
   processes are culled after `session_ttl` seconds of inactivity (default
   3600). Files are untouched by culling — the student resumes exactly
   where they left off on next Edit click.

6. **Single shared dashboard process.** One Marimo app serves all
   students; it reads `X-Remote-User` (forwarded via the session cookie
   or a request context variable) to show each student only their own
   assignments and files.

7. **Optional release directory.** The hub can optionally store release
   notebooks in `{release_dir}/{assignment}/{assignment}.py`, deployed
   via `mograder hub publish`. When present, this enables four
   improvements: (a) full source reinjection during validate (reinserting
   deleted or heavily-modified check cells from the canonical source),
   (b) self-contained `warm-cache --all`, (c) Reset restores from release
   rather than requiring re-upload from Moodle, and (d) students can
   download the release directly from the hub dashboard — no Moodle
   download + re-upload step needed.

   **Note on integrity checking:** basic integrity checking via cell
   hashes works regardless of whether `release_dir` is present, because
   `mograder generate` embeds cell hashes in the PEP 723 metadata block
   of the release `.py`. These hashes travel with the file through the
   Moodle download → hub upload path. The hub validate endpoint can
   therefore always perform hash-based integrity checking on the uploaded
   file. The `release_dir` enables the stronger check: full source
   reinjection of tampered cells (the same mechanism as `mograder
   autograde --source`). When `release_dir` is absent, validate degrades
   gracefully to hash-based checking only — still meaningful, just
   without the ability to restore deleted check cells before execution.

   The `release_dir` is written by `mograder hub publish` (instructor
   command) and is read-only to students.

---

## Task 1: `mograder hub` command

### 1.1 CLI interface

Add to the CLI (in `src/mograder/cli.py` or equivalent):

```
mograder hub [OPTIONS] COURSE_DIR

  Launch the multi-user hub server.

Options:
  --port INTEGER          Port to listen on [default: 8080]
  --host TEXT             Host to bind [default: 0.0.0.0]
  --notebooks-dir PATH    Directory for per-student notebook storage
                          [default: {COURSE_DIR}/hub-notebooks]
  --session-ttl INTEGER   Seconds before idle marimo sessions are culled
                          [default: 3600]
  --trusted-header TEXT   Header name for remote user [default: X-Remote-User]
  --dev                   Trust X-Remote-User from any source (local dev only)
  --headless              Do not open browser on start
```

#### `mograder hub check`

Run preflight checks before starting the hub (see Task 3.1).

#### `mograder hub warm-cache`

```
mograder hub warm-cache [NOTEBOOK ...] [--all]

  Pre-populate the shared uv cache for one or more release notebooks
  so that the first student session for each assignment starts quickly.

  Each notebook's PEP 723 dependency block is parsed and its dependencies
  are installed into the shared uv cache via `uv run --with <deps>
  python -c pass`. This is idempotent — running it again after a uv
  update refreshes the cache.

Arguments:
  NOTEBOOK ...   One or more release .py notebook paths

Options:
  --all          Warm cache for all .py files found under release/
  --dry-run      Print what would be installed without running uv
```

Run this once after deployment and again whenever you publish a new
assignment or update dependencies. Takes a few minutes; saves every
student from a slow first-session install.

There is no `--release-dir` option on the server start command — the
release directory is managed by `mograder hub publish` (see below).

Configuration keys under `[hub]` in `mograder.toml`:

```toml
[hub]
port = 8080
notebooks_dir = "hub-notebooks"
release_dir = "hub-release"     # optional; populated by 'mograder hub publish'
session_ttl = 3600
trusted_header = "X-Remote-User"
uv_cache_dir = ""   # default: ~/.cache/uv — leave empty to use default
```

#### `mograder hub publish`

Instructor-only command, run from the instructor's local machine or
moriarty **after** uploading the release files to Moodle manually.
Before publishing to the hub, fetches the assignment files from Moodle
using the existing `mograder moodle fetch` machinery and asserts they
match the local release files byte-for-byte. Only proceeds if the
content matches exactly. This makes Moodle the gating authority —
you can only publish to the hub what is already live on Moodle, and
the content is verified not just the filename.

```
mograder hub publish ASSIGNMENT_DIR --moodle-assignment NAME
                     --url HUB_URL --token INSTRUCTOR_TOKEN

  Publish a release assignment to the hub.

  Fetches the assignment files from Moodle and verifies they match
  the local release files exactly before uploading to the hub.
  Refuses to publish if there is any mismatch, unless --force is used.
  On success, warms the uv cache for the assignment's dependencies.

Arguments:
  ASSIGNMENT_DIR        Local path to the release assignment directory
                        (e.g. release/hw1/)

Options:
  --moodle-assignment   Moodle assignment name to verify against
                        [required unless --force]
  --url TEXT            Hub base URL [or set MOGRADER_HUB_URL]
  --token TEXT          Instructor token [or set MOGRADER_HUB_INSTRUCTOR_TOKEN]
  --force               Skip Moodle verification and publish anyway.
                        Not recommended — hub will be out of sync with Moodle.
  --dry-run             Fetch from Moodle, run verification, and show
                        what would be published without sending anything
```

**Publish flow:**

1. Fetch the Moodle assignment files into a temp directory using the
   existing `mograder moodle fetch` logic (reuse, do not duplicate)
2. Compare each file byte-for-byte against the local `ASSIGNMENT_DIR`:
   - All files present in `ASSIGNMENT_DIR` must exist on Moodle with
     identical content
   - Files present on Moodle but absent locally are reported as a
     warning (not a failure — Moodle may have auxiliary files not in
     the local release dir)
   - Any content mismatch or missing-from-Moodle file is a hard failure
3. On mismatch, print a clear diff and refuse:
   ```
   ✗ Moodle assignment "HW1" files do not match local release:
       hw1.py: content differs (local: 4821 bytes, Moodle: 4819 bytes)
       data.csv: present locally, not found on Moodle

     Upload the correct files to Moodle first, then re-run publish.
     Use --force to publish anyway (not recommended).
   ```
4. On match, proceed to POST files to the hub publish endpoint:
   ```
   ✓ Moodle "HW1" matches local release exactly (2 files)
     Publishing to hub...
     ✓ Published hw1.py, data.csv
     ✓ Cache warmed for hw1 dependencies
   ```
5. Clean up temp directory

**Hub-side publish endpoint** (`POST /publish/{assignment}`,
instructor token required):

```python
@app.post("/publish/{assignment}")
async def publish_assignment(
    assignment: str,
    files: list[UploadFile],
    current_user: str = Depends(require_instructor),
):
    """
    Write uploaded files to release_dir/{assignment}/.
    Run warm-cache for the .py notebook after writing.
    Only accessible with an instructor token, not a student session cookie.
    The Moodle verification is enforced client-side by mograder hub publish;
    this endpoint trusts that the caller has already verified the content
    matches Moodle. --force bypasses client-side verification only.
    """
    release_assignment_dir = config.release_dir / assignment
    release_assignment_dir.mkdir(parents=True, exist_ok=True)

    for f in files:
        dest = release_assignment_dir / f.filename
        dest.write_bytes(await f.read())

    # Write a manifest of all files in this release assignment,
    # used by the dashboard's hub-side Download action.
    # Exclude files.json itself and dotfiles.
    all_files = [
        p.name for p in release_assignment_dir.iterdir()
        if p.is_file() and not p.name.startswith(".")
        and p.name != "files.json"
    ]
    (release_assignment_dir / "files.json").write_text(
        json.dumps({"files": sorted(all_files)})
    )

    # Warm cache for the newly published notebook
    nb = release_assignment_dir / f"{assignment}.py"
    if nb.exists():
        await warm_cache([nb])

    log.info("Published assignment %s (%d files)", assignment, len(files))
    return {
        "status": "ok",
        "assignment": assignment,
        "files": [f.filename for f in files],
    }
```

The instructor token is a separate long-lived HMAC token generated
once at deployment time:

```bash
mograder hub generate-token --role instructor
# outputs: <token>  (store in MOGRADER_HUB_INSTRUCTOR_TOKEN)
```

`require_instructor` is a separate FastAPI dependency from `require_user`
that validates the `Authorization: Bearer <token>` header against the
instructor HMAC token. It does not accept student session cookies.

#### `mograder hub warm-cache`

```
mograder hub warm-cache [NOTEBOOK ...] [--all] [--url HUB_URL] [--token TOKEN]

  Pre-populate the shared uv cache for one or more release notebooks.

  When run locally (no --url): operates directly on local notebook files.
  When run with --url: POSTs a warm-cache request to the hub's instructor
  endpoint, which runs warm-cache server-side.

  Each notebook's PEP 723 dependency block is parsed and its dependencies
  are installed into the shared uv cache via `uv run --with <deps>
  python -c pass`. This is idempotent.

Arguments:
  NOTEBOOK ...   One or more release .py notebook paths (local mode only)

Options:
  --all          Warm cache for all notebooks in release_dir (server mode)
                 or all .py files in the current release/ directory (local)
  --url TEXT     Hub base URL (triggers server-side warm-cache)
  --token TEXT   Instructor token (required with --url)
  --dry-run      Print what would be installed without running uv
```

Running `mograder hub publish` automatically warms the cache for the
published assignment, so explicit `warm-cache` calls are only needed
for bulk pre-warming at deployment time or after uv updates.

**Note:** `release_dir` on the hub is not required for basic validate
integrity checking — cell hashes are embedded in the release `.py`
and travel with the file. The `release_dir` enables the stronger
source-reinjection check and is required for warm-cache `--all` and
hub-side Download.

`MOGRADER_HUB_SECRET` must be set as an environment variable (no default;
raise a clear error at startup if missing, except in `--dev` mode where a
random ephemeral secret is generated with a warning).

### 1.2 FastAPI application structure

Create `src/mograder/hub/` package with:

```
src/mograder/hub/
  __init__.py
  app.py          ← FastAPI app factory
  auth.py         ← X-Remote-User validation + session cookie logic
  spawner.py      ← per-student marimo process lifecycle
  proxy.py        ← HTTP + websocket reverse proxy
  storage.py      ← per-student directory management
  models.py       ← Session, StudentInfo dataclasses
```

The FastAPI app is created via `create_hub_app(config: HubConfig) -> FastAPI`
and mounted/run by the CLI command using uvicorn.

### 1.3 Authentication (`hub/auth.py`)

#### Middleware: `RemoteUserMiddleware`

Applied to all routes. Logic:

1. Check for valid session cookie (`mograder_hub_session`).
   - Cookie value: `base64(username:timestamp:hmac)` where
     `hmac = HMAC-SHA256(MOGRADER_HUB_SECRET, f"{username}:{timestamp}")`
   - Reject if timestamp is >24h old (configurable via `session_max_age`)
   - On valid cookie: set `request.state.username = username`

2. If no valid cookie: check `X-Remote-User` header.
   - In production (not `--dev`): only trust this header if it arrives
     on the loopback interface or from a configured upstream IP.
     Simplest implementation: check `request.client.host` against an
     allowlist (`trusted_proxy_ips` in config, default `["127.0.0.1"]`).
   - If valid: set `request.state.username`, issue a session cookie in
     the response.

3. If neither: return `403 Forbidden` with a clear message explaining
   that this service requires university SSO login.

4. In `--dev` mode: if `X-Remote-User` is present, trust it regardless
   of source. If absent, use `"dev-user"` as the username. Log a loud
   warning on startup.

#### Helper: `require_user(request: Request) -> str`

FastAPI dependency that reads `request.state.username` or raises `403`.
Used in all route handlers.

`require_user` must accept either of two authentication methods, checked
in order:

1. **Session cookie** (`mograder_hub_session`) — set by
   `RemoteUserMiddleware` after SSO. Used by hub-in-browser students
   accessing the hub via the sciml SSO proxy.

2. **Bearer token** (`Authorization: Bearer <token>`) — where token
   is `base64(username:hmac)` using the same HMAC-SHA256 format and
   `MOGRADER_HUB_SECRET` as the session cookie, but without a
   timestamp expiry. Used by the Tauri desktop app and local
   `mograder student` accessing the hub via HTTPS transport. These
   tokens are generated by `mograder https login` (student
   self-registration with enrollment code) and cached locally at
   `~/.config/mograder/`. Unlike Moodle tokens, they can be
   regenerated freely by re-registering with the enrollment code,
   so the "can only view once" problem does not apply.

Both paths ultimately set `request.state.username` to the verified
username. The HMAC validation logic is shared — extract into a
`verify_hmac_token(token: str) -> str` helper used by both
`RemoteUserMiddleware` (session cookies) and `require_user` (Bearer
tokens).

This dual-auth design means the hub's validate, release download, and
status endpoints are accessible to both SSO-authenticated browser
sessions and HTTPS-transport Tauri/local clients without any change
to the endpoint implementations themselves.

### 1.4 Process spawner (`hub/spawner.py`)

#### `SessionManager` class

```python
@dataclass
class MarimoSession:
    username: str
    assignment: str
    port: int
    process: asyncio.subprocess.Process
    notebook_path: Path
    last_seen: float  # time.monotonic()

class SessionManager:
    def __init__(self, config: HubConfig): ...

    async def get_or_spawn(
        self, username: str, assignment: str
    ) -> MarimoSession: ...

    async def touch(self, username: str, assignment: str) -> None: ...

    async def cull_idle(self) -> None: ...  # called by background task

    async def shutdown_all(self) -> None: ...
```

#### `get_or_spawn` logic

1. If a live session exists for `(username, assignment)`: touch it,
   return it.
2. Allocate a free port (scan from `base_port=18000` upward, check
   `socket.connect` to confirm free).
3. Check that the student's notebook file exists via
   `storage.assignment_path(username, assignment)`. If it does not exist,
   raise `FileNotFoundError` — the student must upload before editing.
   Do not attempt to copy from any release directory.
4. Spawn subprocess:
   ```python
   proc = await asyncio.create_subprocess_exec(
       "marimo", "edit", "--headless",
       "--port", str(port),
       "--base-url", f"/edit/{username}/{assignment}",
       "--no-token",
       str(notebook_path),
       cwd=notebook_path.parent,
       env={
           **os.environ,
           # Isolate marimo's config and state per student using XDG
           # dirs pointing into their own notebook directory.
           # Do NOT override HOME or XDG_CACHE_HOME — all students
           # share /home/mograder/.cache/uv so that uv sandbox
           # environments are cached once and reused across sessions.
           # Overriding HOME would give each student a separate uv
           # cache, causing slow first-session installs for every
           # student and multiplying disk usage by cohort size.
           "XDG_CONFIG_HOME": str(notebook_path.parent / ".config"),
           "XDG_DATA_HOME": str(notebook_path.parent / ".local/share"),
       },
   )
   ```
5. Wait for the port to be ready (poll `GET http://localhost:{port}/`
   with 100ms intervals, timeout 30s; raise `RuntimeError` if not ready).
6. Store session, return it.

#### Background idle culler

Start as an `asyncio` background task in the FastAPI lifespan:

```python
async def cull_loop(manager: SessionManager, interval: int = 60):
    while True:
        await asyncio.sleep(interval)
        await manager.cull_idle()
```

`cull_idle` iterates sessions, terminates (`SIGTERM` then `SIGKILL` after
5s) any whose `last_seen` is older than `session_ttl`. Log each culled
session. Do **not** delete the notebook files.

#### Port cleanup

When a process exits unexpectedly (poll `process.returncode`), remove it
from the session map so the next `get_or_spawn` respawns it cleanly.
Add a background task that polls all processes every 30s.

### 1.5 HTTP + WebSocket proxy (`hub/proxy.py`)

#### `ProxyMiddleware` (extend or reuse existing one from `mograder serve`)

Routes under `/edit/{username}/{assignment}/` are proxied to the
corresponding marimo session's port.

**HTTP proxy:**

```python
@app.api_route(
    "/edit/{username}/{assignment}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
)
async def proxy_http(
    username: str,
    assignment: str,
    path: str,
    request: Request,
    current_user: str = Depends(require_user),
):
    if current_user != username:
        raise HTTPException(403, "Cannot access another student's session")
    session = await session_manager.get_or_spawn(username, assignment)
    await session_manager.touch(username, assignment)
    target = f"http://localhost:{session.port}/edit/{username}/{assignment}/{path}"
    # Forward request, stream response
    ...
```

**WebSocket proxy:**

```python
@app.websocket("/edit/{username}/{assignment}/ws/{path:path}")
async def proxy_ws(
    username: str,
    assignment: str,
    path: str,
    client_ws: WebSocket,
    current_user: str = Depends(require_user),  # from cookie
):
    session = await session_manager.get_or_spawn(username, assignment)
    await session_manager.touch(username, assignment)
    target_url = f"ws://localhost:{session.port}/edit/{username}/{assignment}/ws/{path}"
    # Bidirectional websocket proxy
    ...
```

Use `httpx.AsyncClient` for HTTP proxying and `websockets` library for
WS proxying. Both are likely already in the dependency tree; add if not.

**Important:** forward the following headers to marimo, stripping
`X-Remote-User` (marimo doesn't need it):
- `Host`, `X-Forwarded-For`, `X-Forwarded-Proto`
- `Upgrade`, `Connection` (for websockets)

The LSP websocket (`/lsp/pylsp`) uses the same proxy path. There is a
known upstream marimo bug where LSP doesn't work correctly behind TLS
reverse proxies (wss:// scheme detection). Add a note in the code
referencing marimo issue #4584; apply the workaround (override scheme
detection) if the bug is still present in the installed marimo version.

### 1.6 File upload and export endpoints

These are simple FastAPI routes, not proxied to marimo.

#### Upload: `POST /upload/{username}/{assignment}`

```python
@app.post("/upload/{username}/{assignment}")
async def upload_notebook(
    username: str,
    assignment: str,
    file: UploadFile,
    current_user: str = Depends(require_user),
):
    if current_user != username:
        raise HTTPException(403)
    if not file.filename.endswith(".py"):
        raise HTTPException(400, "Only .py files accepted")

    dest = storage.assignment_path(username, assignment)
    # Archive existing file before overwriting
    if dest.exists():
        archive = dest.with_suffix(
            f".bak.{int(time.time())}.py"
        )
        dest.rename(archive)

    content = await file.read()
    dest.write_bytes(content)

    # If a marimo session is running for this assignment, kill it
    # so it reloads the new file on next Edit click
    await session_manager.terminate(username, assignment)

    return {"status": "ok", "path": str(dest)}
```

#### Export: `GET /export/{username}/{assignment}`

```python
@app.get("/export/{username}/{assignment}")
async def export_notebook(
    username: str,
    assignment: str,
    current_user: str = Depends(require_user),
):
    if current_user != username:
        raise HTTPException(403)
    path = storage.assignment_path(username, assignment)
    if not path.exists():
        raise HTTPException(404, "No notebook found — upload one first")
    return FileResponse(
        path,
        filename=path.name,
        media_type="text/x-python",
    )
```

#### Download release: `GET /release/{assignment}/{filename}`

Serves files from the release directory to authenticated students.
Only accessible when the release has been published.

```python
@app.get("/release/{assignment}/{filename}")
async def download_release_file(
    assignment: str,
    filename: str,
    current_user: str = Depends(require_user),
):
    """
    Serve a release file (notebook or auxiliary data file) to any
    authenticated student. No per-user authorisation check needed —
    all students are entitled to access their own release notebooks.
    The release directory is read-only; this endpoint cannot be used
    to write or modify release files.
    """
    if storage.release_dir is None:
        raise HTTPException(404, "No release directory configured")
    # Validate path to prevent traversal into other assignments
    path = (storage.release_dir / assignment / filename).resolve()
    if not str(path).startswith(str(storage.release_dir.resolve()) + "/"):
        raise HTTPException(400, "Invalid path")
    if not path.exists():
        raise HTTPException(404, f"Release file not found: {filename}")
    return FileResponse(path, filename=filename)
```

This endpoint serves both the `.py` notebook and any auxiliary files
(data files, etc.) that were uploaded alongside it via `mograder hub
publish`. The dashboard uses it for the hub-side Download action.

When a release version is available (`storage.has_release(assignment)`),
reset copies it over the student's working copy. When no release is
available, it archives only and instructs the student to re-upload.

```python
@app.post("/reset/{username}/{assignment}")
async def reset_notebook(
    username: str,
    assignment: str,
    current_user: str = Depends(require_user),
):
    if current_user != username:
        raise HTTPException(403)

    path = storage.assignment_path(username, assignment)
    await session_manager.terminate(username, assignment)

    if storage.has_release(assignment):
        # Full reset: restore from release, archive existing file
        archive = storage.reset_to_release(username, assignment)
        return {
            "status": "reset",
            "archived_as": archive.name if archive else None,
            "message": "Reset to release version complete.",
        }
    else:
        # Archive-only: no release available on this hub
        if not path.exists():
            raise HTTPException(404, "No notebook to reset")
        archive = path.with_suffix(f".bak.{int(time.time())}.py")
        path.rename(archive)
        return {
            "status": "archived",
            "archived_as": archive.name,
            "message": (
                "Your working copy has been archived. "
                "Download a fresh copy from Moodle and upload it to start again."
            ),
        }
```

### 1.7 Storage manager (`hub/storage.py`)

The hub maintains per-user notebook storage and an optional shared
release directory. All methods gracefully handle the case where
`release_dir` is `None` (not configured).

```python
class StorageManager:
    def __init__(
        self,
        notebooks_dir: Path,
        release_dir: Path | None = None,
    ): ...

    def assignment_path(self, username: str, assignment: str) -> Path:
        """Returns path to student's working .py file."""
        return self._safe_path(username, assignment, f"{assignment}.py")

    def release_path(self, assignment: str) -> Path | None:
        """
        Returns path to the release .py for this assignment,
        or None if release_dir is not configured or the file doesn't exist.
        """
        if self.release_dir is None:
            return None
        p = self.release_dir / assignment / f"{assignment}.py"
        return p if p.exists() else None

    def has_release(self, assignment: str) -> bool:
        return self.release_path(assignment) is not None

    def ensure_dir(self, username: str, assignment: str) -> Path:
        """
        Ensures the student's assignment directory exists.
        Does NOT populate any files — the student must upload.
        Returns the directory path.
        """
        d = self.assignment_path(username, assignment).parent
        d.mkdir(parents=True, exist_ok=True)
        return d

    def assignment_status(self, username: str, assignment: str) -> str:
        """
        Returns one of: "not_started", "uploaded", "modified", "exported"

        "modified" means the file has been changed since it was uploaded
        (mtime of .py > mtime of upload marker).
        "exported" means the file has been exported since the last
        modification.
        Both states are tracked via sidecar marker files.
        """
        path = self.assignment_path(username, assignment)
        if not path.exists():
            return "not_started"

        upload_marker = path.with_suffix(".uploaded")
        export_marker = path.with_suffix(".exported")

        if export_marker.exists():
            if export_marker.stat().st_mtime >= path.stat().st_mtime:
                return "exported"

        if upload_marker.exists():
            if path.stat().st_mtime > upload_marker.stat().st_mtime:
                return "modified"

        return "uploaded"

    def mark_uploaded(self, username: str, assignment: str) -> None:
        """Called after a successful upload. Touch the upload marker."""
        marker = self.assignment_path(username, assignment).with_suffix(".uploaded")
        marker.touch()

    def mark_exported(self, username: str, assignment: str) -> None:
        """Called after a successful export download."""
        marker = self.assignment_path(username, assignment).with_suffix(".exported")
        marker.touch()

    def reset_to_release(self, username: str, assignment: str) -> Path:
        """
        Copy the release version over the student's working copy,
        archiving the existing file first. Requires has_release() == True.
        Returns the archive path.
        Raises FileNotFoundError if no release exists.
        """
        release = self.release_path(assignment)
        if release is None:
            raise FileNotFoundError(
                f"No release version available for {assignment}"
            )
        dest = self.assignment_path(username, assignment)
        dest.parent.mkdir(parents=True, exist_ok=True)
        archive = None
        if dest.exists():
            archive = dest.with_suffix(f".bak.{int(time.time())}.py")
            dest.rename(archive)
        shutil.copy2(release, dest)
        self.mark_uploaded(username, assignment)
        return archive
```

---

## Task 2: Dashboard changes

The existing `mograder student` dashboard runs locally on the student's
machine. The hub version runs server-side as a shared Marimo app. The
changes below apply to the dashboard Marimo app source (find it in
`src/mograder/`).

### 2.1 Hub-mode detection

Add a `hub_mode: bool` flag to the dashboard configuration, set `True`
when launched by `mograder hub`. In hub mode:

- The username comes from `request.state.username` (injected via a
  Marimo request context variable — see how `mograder formgrader`
  accesses request state, and follow the same pattern)
- Moodle transport UI (token paste, Moodle fetch/submit buttons) is
  **hidden** — the underlying Moodle transport code is unchanged and
  fully functional when `mograder student` is run locally by students
  comfortable with that workflow
- Upload, Edit, Validate, Export, and Archive actions are shown
  **instead of** (not in addition to) the Moodle fetch/submit buttons

**Note on transport modes:** `mograder student` running locally retains
full Moodle API access as before — students comfortable with local setup
can continue to use it. Hub mode is an alternative deployment path, not
a replacement. The dashboard detects hub mode via the `hub_mode` config
flag and adjusts the UI accordingly. No Moodle transport code should be
removed or modified.

### 2.2 Assignment table in hub mode

The assignment table replaces the current columns with:

| Assignment | Due date | Status | Actions |
|---|---|---|---|
| HW1 | 14 Apr 17:00 | 🟡 Modified | Edit · Validate · Export · Reset |
| HW2 | 28 Apr 17:00 | ⬜ Not started | Upload |

The Reset button label adapts based on whether a release version is
available: **Reset to release** (when `has_release: true` in the status
response) or **Archive** (when `has_release: false`). See Task 2.7.

**Status indicators:**

| Status | Indicator | Meaning |
|---|---|---|
| `not_started` | ⬜ Not started | No file in workspace |
| `uploaded` | 🔵 Uploaded | File present, unmodified since download/upload |
| `modified` | 🟡 Modified | File changed since download/upload |
| `exported` | 🟢 Exported | File exported since last modification |

**Action buttons per status:**

- `not_started`: **Download** (if `has_release: true`) or **Upload** (if
  `has_release: false`) — show whichever is appropriate; if release is
  available show Download as the primary action with Upload as a
  secondary option (e.g. "or upload your own copy")
- `uploaded` / `modified` / `exported`: **Edit · Validate · Export · Reset/Archive**
  (Download/Upload still available at all states to start fresh)

### 2.3 Download / Upload action

#### When release is available (`has_release: true`)

The primary action for `not_started` assignments is **Download**. Clicking it:

1. Fetches the release `.py` from `/release/{assignment}/{assignment}.py`
   and any auxiliary files listed in a manifest
   (`/release/{assignment}/files.json` — the publish endpoint writes
   this; see below)
2. POSTs each file to `/upload/{username}/{assignment}` to copy it into
   the student's workspace
3. Updates status to `uploaded`
4. Shows confirmation: "Downloaded ✓ — ready to edit."

This is a single click for the student. No Moodle interaction required.

The manifest endpoint (`GET /release/{assignment}/files.json`) returns:
```json
{"files": ["hw1.py", "data.csv", "helper.py"]}
```
The publish endpoint writes this file automatically when uploading.

Students can still **Upload** their own copy (e.g. if they started on
their local machine) — show this as a secondary option:
> "Already started locally? [Upload your file instead]"

#### When no release is available (`has_release: false`)

The primary action is **Upload** with helper text:
> "Download the assignment .py file from Moodle, then drag it here or
> click to select."

A `mo.ui.file(accept=[".py"])` widget is revealed inline on click,
accepting drag-and-drop. On file selection:

1. POST the file to `/upload/{username}/{assignment}`
2. Show a spinner while uploading
3. On success: update status to `uploaded`, hide the widget
4. On error: show the error message inline

#### Common: upload endpoint behaviour

In both cases the upload endpoint writes the file and calls
`storage.mark_uploaded()` to set the upload marker used to track
subsequent modifications.

### 2.4 Edit action

Clicking **Edit**:

1. POST to `/edit/{username}/{assignment}/` (this triggers
   `get_or_spawn` on the hub)
2. Show a spinner with text "Starting your notebook session…" while
   waiting for the marimo process to be ready (poll the hub's
   `/status/{username}/{assignment}` endpoint — add this endpoint,
   returns `{"ready": bool}`)
3. Once ready: open the marimo edit URL in a new browser tab:
   `{hub_base_url}/edit/{username}/{assignment}/`

Do not navigate away from the dashboard — the student manages the
dashboard tab and the marimo tab separately.

### 2.5 Validate action

Clicking **Validate**:

1. POST to `/validate/{username}/{assignment}` on the hub (add this
   endpoint — see below)
2. Show a spinner with text "Running checks…"
3. Display results inline in the table row: summary line
   (e.g. "3/5 PASS") with a collapsible HTML preview of the full
   check output

**Hub-side validate endpoint** (`POST /validate/{username}/{assignment}`):

```python
@app.post("/validate/{username}/{assignment}")
async def validate(username, assignment, current_user=Depends(require_user)):
    """
    Run the student's notebook and return check results.

    Integrity checking works at two levels:

    1. HASH-BASED (always available): mograder generate embeds cell hashes
       in the PEP 723 metadata block of the release .py. These hashes
       travel with the file through Moodle download → hub upload, so the
       uploaded file is self-describing. mograder validate uses these
       embedded hashes to detect accidentally or deliberately modified
       non-solution cells. This works even when no release_dir is
       configured on the hub.

    2. SOURCE REINJECTION (when release_dir is available): if the hub has
       the release notebook (published via 'mograder hub publish'),
       tampered or deleted check cells can be reinjected from source
       before execution — matching exactly what mograder autograde
       --source does on moriarty. This is the stronger check: it catches
       cells that have been deleted entirely (which hash checking cannot
       detect) and restores them before running.

    Reuse the existing mograder validate logic (mograder validate
    hw1.py [--release release/hw1/hw1.py]) rather than reimplementing
    it. Pass source=release if release_dir is available, otherwise
    let the hash-based check in the uploaded file handle integrity.

    Do not add a hard requirement for the release to be present —
    degrade gracefully and indicate in the response which level of
    integrity checking was performed.
    """
    if current_user != username:
        raise HTTPException(403)
    path = storage.assignment_path(username, assignment)
    if not path.exists():
        raise HTTPException(404, "No notebook found — upload one first")

    release = storage.release_path(assignment)
    # source reinjection available if release_dir is configured and populated;
    # hash-based integrity check is always available via embedded PEP 723 metadata
    integrity_level = "source" if release is not None else "hash"

    # Use the same internal execution path as `mograder validate`.
    # IMPORTANT: check results come from the sidecar JSONL mechanism
    # (MOGRADER_SIDECAR_PATH), NOT from parsing the HTML output.
    # Each check() call during execution appends to a temp JSONL file;
    # read this after execution for results.
    # Find the actual internal function name in the validate/autograde
    # source — do NOT use the placeholder name run_sandboxed_export or
    # parse_check_results. Do NOT duplicate — import and call directly.
    result = await _run_validated_export(  # placeholder — find real name
        path,
        source=release,   # None = hash-based only; Path = full source reinjection
        timeout=120,
    )
    # result.checks comes from the sidecar JSONL (not HTML parsing)
    # result.integrity_warnings comes from embedded cell hash comparison
    checks = result.checks
    return {
        "summary": f"{checks.passed}/{checks.total} PASS",
        "integrity_level": integrity_level,  # "source" | "hash"
        "integrity_warnings": result.integrity_warnings,  # list of modified cells
        "html": result.html,
        "checks": checks.as_dict(),
    }
```

The dashboard should display `integrity_level` to the student:
- `"source"`: "✓ Full integrity check — check cells verified and restored
  from release if modified"
- `"hash"`: "✓ Hash integrity check — non-solution cells verified against
  release hashes" (add note: "Deleted check cells cannot be detected
  without the release version on the hub")

If `integrity_warnings` is non-empty, show them inline:
> "⚠ Modified cells detected: [list of cell names]"

### 2.6 Export action

Clicking **Export**:

1. Trigger a browser download of `/export/{username}/{assignment}`
   (use a temporary `<a href=... download>` element or `mo.download`)
2. On successful download response: call
   `/mark-exported/{username}/{assignment}` (POST, no body) to set the
   exported marker
3. Update the row status to `exported`
4. Show a dismissible info banner:
   > "Downloaded ✓ — remember to upload this file to the Moodle
   > assignment page to submit."

The banner should persist until dismissed, not auto-dismiss, so the
student doesn't miss the reminder.

### 2.7 Reset / Archive action

The button label and behaviour depend on whether a release version is
available on the hub (indicated by `has_release` in the status endpoint
response — add this field).

**When release is available** (button label: **Reset to release**):

Confirmation dialog:
> "This will replace your working copy with the release version.
> Your current file will be saved as hw1.bak.{timestamp}.py.
> Are you sure?"

On confirm:
1. POST to `/reset/{username}/{assignment}`
2. Update status to `uploaded`
3. Show success: "Reset complete. Your previous work is saved as
   hw1.bak.{timestamp}.py."

**When no release is available** (button label: **Archive and re-upload**):

Confirmation dialog:
> "This will archive your current working copy as hw1.bak.{timestamp}.py.
> You will need to download a fresh copy from Moodle and upload it again.
> Are you sure?"

On confirm:
1. POST to `/reset/{username}/{assignment}`
2. Update status to `not_started`
3. Show info: "Archived. Download a fresh copy from Moodle and upload
   it to start again." with Upload button immediately visible.

In both cases, any running marimo session is terminated by the endpoint.

### 2.8 Status endpoint

Add to the hub:

```python
@app.get("/status/{username}/{assignment}")
async def session_status(
    username: str, assignment: str, current_user=Depends(require_user)
):
    if current_user != username:
        raise HTTPException(403)
    session = session_manager.get(username, assignment)
    file_status = storage.assignment_status(username, assignment)
    return {
        "ready": session is not None and session.process.returncode is None,
        "file_status": file_status,
        "session_active": session is not None,
        "has_release": storage.has_release(assignment),
    }
```

The dashboard polls this endpoint (every 2s while a session is starting,
on-demand otherwise) to keep status indicators fresh.

---

## Task 3: Deployment support

### 3.1 `mograder hub check` subcommand

Before starting the hub, run preflight checks and report:

```
mograder hub check

Checking mograder hub configuration...
  ✓ MOGRADER_HUB_SECRET is set
  ✓ Course directory exists: /home/mograder/course
  ✓ Notebooks directory is writable: /home/mograder/course/hub-notebooks
  ✓ Release directory exists: /home/mograder/course/hub-release (2 assignments)
  ✓ marimo is available: marimo 0.19.x
  ✓ uv is available: uv 0.x.x
  ✓ uv cache directory exists: /home/mograder/.cache/uv
  ✓ Port 8080 is available
  ✓ bubblewrap available — edit sessions will be sandboxed
  ⚠ --dev mode is active: X-Remote-User trusted from all sources
  ℹ  Publish assignments with 'mograder hub publish release/<assignment>/'
  ℹ  Run 'mograder hub warm-cache --all' after publishing to pre-populate
     the uv cache for faster first-session startup
```

The release directory check is advisory (⚠, non-fatal) if `release_dir`
is configured but empty. It is skipped entirely if `release_dir` is not
set in `mograder.toml`.

Exit code 0 if all required checks pass (warnings are non-fatal).

### 3.2 Systemd unit template

Add `docs/hub-deployment.md` with the following systemd unit template
(do not generate it programmatically — just document it):

```ini
[Unit]
Description=mograder hub
After=network.target

[Service]
User=mograder
WorkingDirectory=/home/mograder/course
Environment="MOGRADER_HUB_SECRET=<generate with: python -c 'import secrets; print(secrets.token_hex(32))'>"
ExecStart=/home/mograder/.local/bin/mograder hub . --port 8080
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

Also document the Caddy reverse proxy config for TLS termination and
websocket forwarding:

```
your-domain.com {
    reverse_proxy localhost:8080 {
        header_up X-Forwarded-Proto {scheme}
        transport http {
            # Required for marimo websockets
            compression off
        }
    }
}
```

Note: `mograder hub` is designed to sit behind sciml's existing SSO
proxy, which handles TLS. Caddy is for standalone deployments or local
testing with a domain. In the Warwick deployment, sciml terminates TLS
and the RONIN instance only needs to accept HTTP from sciml's IP.

The hub requires only a writable `notebooks_dir` on the EBS volume.
The `release_dir` is also on the EBS volume and is populated by
`mograder hub publish` — no manual rsync or git clone required.

**Publish workflow:** after generating release notebooks locally with
`mograder generate`, upload them to the Moodle assignment manually
(as the Moodle API token does not support file upload). Then run
`mograder hub publish release/hw1/ --moodle-assignment "HW1"` to
mirror them to the hub. The command fetches the files from Moodle
and verifies the content matches your local release exactly before
uploading to the hub, ensuring Moodle is always the authoritative
source. Use `--force` only in exceptional circumstances. The publish
step also warms the uv cache for that assignment automatically.

**uv cache:** all student marimo sessions share the uv package cache at
`~/.cache/uv` (or `uv_cache_dir` if configured). `mograder hub publish`
warms the cache automatically for each published assignment. Run
`mograder hub warm-cache --all` after deployment to pre-warm all
published assignments in bulk.

---

## Task 4: Security hardening

The hub runs all student marimo processes as the same OS user, so
application-level defences are the primary isolation mechanism. The
following hardening measures are required. They address three distinct
attack surfaces: malicious uploads, malicious code added during editing,
and path traversal bugs in the application itself.

### 4.1 Path traversal hardening in `StorageManager`

All methods that construct file paths must validate the resolved path is
within `notebooks_dir` before performing any file operation. Add a
private helper:

```python
def _safe_path(self, *parts: str) -> Path:
    """
    Construct a path from parts and verify it resolves within
    notebooks_dir. Raises ValueError on path traversal attempt.
    """
    path = (self.notebooks_dir.joinpath(*parts)).resolve()
    if not str(path).startswith(str(self.notebooks_dir.resolve()) + "/"):
        raise ValueError(f"Path traversal detected: {path}")
    return path
```

Use `_safe_path(username, assignment, f"{assignment}.py")` everywhere
`assignment_path` constructs a path. Apply the same check to archive
paths and marker files. This defends against usernames or assignment
names containing `../` sequences, whether accidental or deliberate.

### 4.2 AST safety check at upload time

At upload time, before writing the file to disk, run the existing
`--safety-check` AST scanner (from `mograder autograde`) on the uploaded
content. Reject uploads that contain denied patterns with a `400` response
and a clear message:

```python
# In the upload endpoint, after reading file content:
# Call the internal AST safety scanner used by mograder autograde --safety-check
# (find the actual function name in the autograde source — do not reimplement)
violations = _run_ast_safety_check(content.decode("utf-8", errors="replace"))
if violations:
    raise HTTPException(
        400,
        f"Upload rejected: notebook contains disallowed patterns "
        f"({', '.join(violations)}). Remove these before uploading."
    )
```

Denied patterns (reuse the same list as `mograder autograde --safety-check`):
`import os`, `import subprocess`, `import socket`, `import shutil`,
`eval()`, `exec()`, `compile()`, `__import__()`.

This catches obviously malicious content in uploaded files. It does not
defend against code added during editing — see Task 4.3.

### 4.3 Bubblewrap sandbox for marimo edit processes

The upload-time AST check is bypassed the moment a student types
`import socket` in their marimo session. The correct defence against
malicious code added during editing is not a heuristic scanner but a
kernel-enforced sandbox that restricts what executed code can actually
do, regardless of what it attempts.

Apply bubblewrap to marimo edit subprocesses when `use_bubblewrap = true`
in `[security]` config, using the same mechanism already specified for
`mograder autograde`. Extend `get_or_spawn` to wrap the `marimo edit`
command with `bwrap` when enabled:

```python
def _wrap_with_bwrap(
    cmd: list[str],
    cwd: Path,
    uv_cache_dir: Path,
    venv_path: Path | None = None,
) -> list[str]:
    """
    Wrap a command with bubblewrap for filesystem and network isolation.
    The working directory is bind-mounted read-write. The shared uv cache
    is bind-mounted read-only so sandbox environments are reused across
    students without each session paying the install cost. Everything
    else is read-only or hidden.
    """
    bwrap_cmd = [
        "bwrap",
        "--ro-bind", "/", "/",              # read-only root
        "--tmpfs", "/tmp",                  # isolated tmp
        "--tmpfs", "/home",                 # hide all home dirs
        "--ro-bind", str(uv_cache_dir),     # shared uv cache, read-only
                     str(uv_cache_dir),     # (students cannot poison it)
        "--bind", str(cwd), str(cwd),       # student's own dir, writable
        "--unshare-net",                    # no network access
        "--die-with-parent",                # clean exit if hub dies
        "--",
    ]
    if venv_path:
        # Allow read access to the Python environment
        bwrap_cmd[2:2] = ["--ro-bind", str(venv_path), str(venv_path)]
    return bwrap_cmd + cmd
```

`uv_cache_dir` defaults to `Path.home() / ".cache" / "uv"` and can be
overridden via `[hub] uv_cache_dir` in `mograder.toml` if the service
account's home differs from the default.

When bubblewrap is active:

- Student code cannot access the network (no exfiltration, no lateral
  movement to other ports on the instance)
- Student code cannot read files outside their own assignment directory
  (no cross-student file access, no access to hub secrets or the
  gradebook)
- Student code cannot write outside their assignment directory
- If the hub process dies, the sandboxed marimo process is killed
  automatically (`--die-with-parent`)

**This is the primary defence against malicious code added during
editing.** The upload-time AST check (Task 4.2) remains as a first-pass
filter for obviously malicious uploads, but bubblewrap is the control
that actually enforces the boundary.

**Configuration:** bubblewrap for edit processes uses the same
`[security]` config as autograde:

```toml
[security]
use_bubblewrap = true   # applies to both autograde and hub edit processes
```

When `use_bubblewrap = false` (default), the hub falls back to the
upload-time AST check alone. Document this residual risk clearly in
`docs/hub-deployment.md`:

> Without bubblewrap, the upload-time safety check is the only defence
> against malicious code added during editing. A student can bypass it
> by typing dangerous imports directly in their marimo session. Enable
> `use_bubblewrap = true` on Linux to enforce kernel-level isolation.
> On Ubuntu 24.04, user namespaces are enabled by default and no
> additional configuration is required.

Update `mograder hub check` to report bubblewrap status for edit
processes specifically:

```
  ✓ bubblewrap available — edit sessions will be sandboxed
```
or:
```
  ⚠ bubblewrap not available — edit sessions run unsandboxed
      (set use_bubblewrap = true and install bwrap for full isolation)
```

### 4.4 Tests for security hardening

Add to the test suite:

- `test_path_traversal`: verify that `username="../other"` and
  `assignment="../../etc/passwd"` raise `ValueError` in `_safe_path`,
  and that the upload/export/edit endpoints return 400/404 rather than
  accessing unintended paths
- `test_upload_safety_check`: verify that a file containing `import
  socket` is rejected at upload with HTTP 400 and a clear message;
  verify that a clean file is accepted
- `test_bwrap_edit_command`: when `use_bubblewrap = true` and `bwrap`
  is on PATH, verify that the command passed to `asyncio.create_subprocess_exec`
  starts with `bwrap` and includes `--unshare-net`, `--die-with-parent`,
  and a `--ro-bind` for the uv cache directory;
  when `use_bubblewrap = false`, verify bwrap is not used
- `test_bwrap_fallback`: when `use_bubblewrap = true` but `bwrap` is
  not on PATH, verify a warning is logged and the session spawns without
  bwrap rather than failing entirely
- `test_uv_cache_not_overridden`: verify that the subprocess environment
  in `get_or_spawn` sets `XDG_CONFIG_HOME` and `XDG_DATA_HOME` but does
  NOT set `HOME` or `XDG_CACHE_HOME`, so the shared uv cache is inherited
- `test_warm_cache_parses_deps`: verify that `warm-cache` correctly
  parses PEP 723 inline script metadata from a notebook and calls uv
  with the right dependencies; verify `--dry-run` prints but does not
  invoke uv

---

## General implementation notes

**Critical: use correct existing function names — do not invent new ones.**
Before implementing any hub feature, locate the actual internal function
in the codebase rather than using the illustrative names in this spec.
Specific mappings confirmed from the codebase:

- **Safety check:** the `--safety-check` flag in `mograder autograde`
  calls an internal AST scanner. Find and import this function directly;
  do not reimplement it. The spec uses `run_safety_check()` as a
  placeholder name.

- **Sandboxed execution + sidecar parsing:** `mograder validate` and
  `mograder autograde` share subprocess execution logic that sets
  `MOGRADER_SIDECAR_PATH` to a temp JSONL file, runs `marimo export
  html`, then reads check results from the sidecar. The hub validate
  endpoint must follow this exact pattern — **not** parse the HTML
  output. The spec uses `run_sandboxed_export()` and
  `parse_check_results()` as placeholder names; find the real internal
  functions. Reading the sidecar JSONL (not HTML) is how check results
  are obtained.

- **Moodle transport:** use `build_transport(config)` from
  `mograder.transport` to get the Moodle transport instance for the
  fetch step in `mograder hub publish`. Do not reimplement Moodle
  fetching.

- **HTTPS token caching:** `load_cached_https_token(url)` exists in
  `mograder.auth` and handles the full cache lookup. The `require_user`
  Bearer token path should use this rather than its own cache logic.
  The full resolution chain is: config → env var (`MOGRADER_HTTPS_TOKEN`)
  → cached token file.

- **Cell hash format:** read `_inject_cell_hashes()` in
  `mograder.markers` before implementing validate hash checking. The
  exact metadata key and hash format are defined there.

- **Submit cell generation:** `build_submit_cell(server_url,
  assignment_name)` exists in `mograder.markers`. Use it for any
  in-notebook submit cell needs. The
formgrader already implements per-notebook marimo edit session
management for instructors — spawning `marimo edit` subprocesses,
proxying HTTP and websockets to them, and managing process lifecycle.
Before implementing `hub/spawner.py` and `hub/proxy.py`, read the
equivalent code in the formgrader carefully. The hub's per-student
session management is the same problem with the addition of auth and
per-user directory isolation. Extract the shared session/proxy logic
into a common module (e.g. `src/mograder/sessions.py`) that both the
formgrader and the hub import, rather than copying it. The formgrader
version can be treated as the reference implementation; the hub version
adds the `username` scoping and directory management on top. Any bug
fixes or improvements to session handling should benefit both.

**Process isolation:** each marimo edit process runs as the same OS user
(`mograder`). File-level isolation between students is provided by
separate directories, not OS permissions. This is acceptable for a
trusted student cohort. Do not attempt OS-level user switching. See
Task 4 for application-level compensating controls.

**Concurrency:** `SessionManager` must use `asyncio.Lock` per
`(username, assignment)` pair for `get_or_spawn` to prevent double-spawning
if two requests arrive simultaneously (e.g. Edit button double-click).

**Graceful shutdown:** on `SIGTERM`, the hub should:
1. Stop accepting new connections
2. Send `SIGTERM` to all marimo subprocesses
3. Wait up to 10s for them to exit
4. `SIGKILL` any survivors
5. Exit

Use the FastAPI lifespan context manager for this.

**Logging:** log all spawns, cull events, upload/export/reset actions,
and auth failures. Use Python's `logging` module at INFO level for normal
operations, WARNING for auth failures and unexpected process exits.

**Tests to add:**

- `test_hub_auth`: verify that requests without valid session cookie or
  `X-Remote-User` get 403; verify cookie issuance; verify cookie expiry;
  verify that a valid `Authorization: Bearer <token>` is accepted and
  sets the correct username; verify that a tampered or expired Bearer
  token is rejected with 403
- `test_hub_spawner`: verify `get_or_spawn` creates a process, returns
  the same session on second call, culls after TTL; verify that
  `get_or_spawn` raises `FileNotFoundError` if no file has been uploaded
- `test_hub_isolation`: verify that user A cannot access user B's
  `/edit/`, `/upload/`, `/export/` endpoints
- `test_storage_status`: verify status transitions —
  `not_started` → `uploaded` (after upload + mark_uploaded) →
  `modified` (after mtime bump) → `exported` (after mark_exported) →
  `modified` (after another mtime bump)
- `test_upload_archives`: verify existing file is archived before
  overwrite, upload marker is updated, marimo session is terminated
- `test_validate_hash_integrity`: verify that when a student uploads a
  release .py with embedded cell hashes (as generated by mograder
  generate), validate detects modified non-solution cells and returns
  them in `integrity_warnings`; verify `integrity_level` is `"hash"`;
  verify a clean unmodified file returns no warnings
- `test_validate_source_reinjection`: when release_dir is configured
  and populated, verify `integrity_level` is `"source"` and that deleted
  check cells are reinjected from source before execution; verify the
  response reflects the reinjected checks, not the tampered file
- `test_validate_hash_cannot_detect_deleted_cells`: verify that with
  hash-only mode (no release_dir), a file with an entirely deleted check
  cell runs without detecting the deletion (expected limitation —
  document in test comment)
- `test_reset_to_release`: when release is present, verify working copy
  is replaced, existing file is archived, upload marker is set
- `test_reset_archive_only`: when no release present, verify working
  copy is archived, status returns `not_started`
- `test_publish_endpoint`: verify instructor token is required (student
  cookie rejected); verify files are written to release_dir; verify
  files.json manifest is written (excluding files.json itself); verify
  warm-cache is triggered
- `test_publish_moodle_verification`: mock `mograder moodle fetch` to
  return matching files — verify publish proceeds; mock it to return
  differing content — verify publish is refused with a clear diff
  message; mock it to return files missing from local release — verify
  publish is refused
- `test_publish_moodle_missing_file`: local release has `data.csv`,
  Moodle does not — verify publish is refused with correct error message
- `test_publish_force_skips_verification`: with `--force`, verify
  publish proceeds even when Moodle fetch returns differing content,
  and a warning is logged
- `test_publish_dry_run`: verify `--dry-run` fetches from Moodle,
  runs verification, prints result, but does not POST to hub endpoint
- `test_has_release`: verify `has_release` returns correct value before
  and after publish; verify status endpoint includes `has_release` field
- `test_release_download`: verify authenticated student can fetch
  `/release/{assignment}/{filename}`; verify unauthenticated request
  is rejected; verify path traversal in filename is rejected
- `test_hub_download_action`: verify that downloading via the hub
  copies the release file and auxiliary files into the student's
  workspace and sets the upload marker
- Security hardening tests from Task 4.4 (path traversal, upload safety
  check, bwrap command construction, bwrap fallback)

**Do not break existing commands.** `mograder student`, `mograder serve`,
`mograder formgrader`, and all other commands must continue to work
unchanged. `mograder hub` is a new command only.

**Run `uv run pytest` and `uv run ruff check src/` before marking any
task complete.**
