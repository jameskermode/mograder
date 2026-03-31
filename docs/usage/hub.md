# Hub — Multi-User Server

The **hub** provides a cloud-hosted alternative to the local `mograder student` workflow. Each student gets a persistent notebook directory and on-demand `marimo edit` sessions, all accessible through a web browser.

## Quick Start

```bash
# Set the secret (required, unless --dev)
export MOGRADER_HUB_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")

# Start the hub
mograder hub -C /path/to/course --port 8080 --headless

# Or in development mode (no auth required)
mograder hub -C /path/to/course --dev --headless
```

## Student Workflow

Students access the hub via a browser (no local install required):

### Assignments

1. Navigate to the hub URL provided by your instructor
2. Log in via university SSO (automatic via reverse proxy)
3. Click **Download** to fetch an assignment
4. Click **Edit** to open the marimo editor in a new tab
5. Work on the assignment — changes are saved automatically
6. Click **Validate** to run checks and see results
7. Click **Export** to download the completed `.py` file
8. Upload the exported file to Moodle for submission
9. Click **Reset** to restore the original release version (your work is archived)

Active edit sessions appear in an **Active editors** panel with links to reopen and a **Stop** button.

!!! note
    The hub does not submit to Moodle directly. Students must export their
    notebook and upload to Moodle for grading.

### Lectures

If the instructor has published lectures to the hub, they appear in a **Lectures** table below the assignments:

1. Click **Run** to open the lecture in a new tab
2. The lecture runs in read-only mode with code visible (`marimo run --include-code`)
3. Each student gets their own isolated session (widget state is not shared)
4. Cross-notebook links within lectures navigate directly to other published lectures

Lecture sessions are per-user and subject to the same idle timeout as assignment edit sessions.

## Commands

### `mograder hub`

Start the hub server. Options:

| Option | Default | Description |
|--------|---------|-------------|
| `-C`, `--course-dir` | `.` | Course directory |
| `--port` | `8080` | Server port |
| `--host` | `0.0.0.0` | Bind address |
| `--notebooks-dir` | from config | Student notebooks directory |
| `--session-ttl` | `3600` | Session idle timeout (seconds) |
| `--trusted-header` | `X-Remote-User` | Trusted proxy header name |
| `--dev` | off | Dev mode (no auth required) |
| `--headless` | off | Don't open browser on startup |

### `mograder hub check`

Preflight check to verify hub requirements:

```bash
mograder hub check /path/to/course
```

Checks:
- `MOGRADER_HUB_SECRET` is set
- `marimo` is available
- `bwrap` (bubblewrap) is available (optional)
- Hub port is free
- Directories are configured

### `mograder hub publish`

Publish a release assignment or lecture to the hub:

```bash
# Publish assignment (verifies files match Moodle first)
mograder hub publish A1 --url $HUB_URL --token $TOKEN

# Skip Moodle verification
mograder hub publish A1 --url $HUB_URL --token $TOKEN --force

# Preview what will be published
mograder hub publish A1 --force --dry-run

# Explicit Moodle assignment name (if different from directory name)
mograder hub publish A1 --moodle-assignment "A1. Introduction" --url $HUB_URL --token $TOKEN

# Publish a lecture (auto-detected from mograder-type metadata, or use --lecture)
mograder hub publish L01-Intro --url $HUB_URL --token $TOKEN
mograder hub publish L01-Intro --lecture --url $HUB_URL --token $TOKEN
```

The `ASSIGNMENT` argument is a name (e.g. `A1-Intro-to-SciML` or prefix `A1`) resolved from the `release/` directory, or an explicit directory path.

For **assignments**, files are verified against Moodle before publishing by default — Moodle is the authoritative source for assignment content.

For **lectures**, Moodle verification is skipped automatically (lectures aren't posted to Moodle). The lecture type is auto-detected from `mograder-type = "lecture"` in the notebook's PEP 723 block (injected by `mograder generate --lecture`), or can be forced with `--lecture`.

Publishing a lecture:
1. Uploads the notebook and auxiliary files to the hub
2. Stores `"type": "lecture"` in the `files.json` manifest
3. Warms the uv cache / creates a shared `.venv` from PEP 723 dependencies

| Option | Env var | Description |
|--------|---------|-------------|
| `--url` | `MOGRADER_HUB_URL` | Hub base URL |
| `--token` | `MOGRADER_HUB_INSTRUCTOR_TOKEN` | Instructor token |
| `--moodle-assignment` | | Moodle assignment name (default: same as ASSIGNMENT) |
| `--force` | | Skip Moodle verification |
| `--lecture` | | Publish as lecture (implies `--force`) |
| `--dry-run` | | Preview only, don't publish |

### `mograder hub warm-cache`

Pre-populate the uv cache with notebook dependencies:

```bash
# Warm cache for specific notebooks
mograder hub warm-cache release/hw1/hw1.py release/hw2/hw2.py

# Warm cache for all release notebooks
mograder hub warm-cache --all

# Dry run (show deps without installing)
mograder hub warm-cache --dry-run release/hw1/hw1.py

# Remote mode: warm cache on the hub server
mograder hub warm-cache --url $HUB_URL --token $TOKEN
```

This parses PEP 723 inline script metadata (`# /// script` blocks) to find
dependencies and runs `uv run --with <deps> python -c pass` to populate the cache.

With `--url`, sends a POST to the hub's `/warm-cache` endpoint instead of running locally.

### `mograder hub generate-token`

Generate HMAC authentication tokens:

```bash
# Generate a student token
mograder hub generate-token alice

# Generate an instructor token
mograder hub generate-token --role instructor admin
```

Requires `MOGRADER_HUB_SECRET` to be set.

## Configuration

Add a `[hub]` section to `mograder.toml`:

```toml
[hub]
port = 8080
notebooks_dir = "hub-notebooks"
release_dir = "hub-release"
session_ttl = 3600
trusted_header = "X-Remote-User"
uv_cache_dir = ""  # empty = default ~/.cache/uv
```

## Instructor Workflow

### Assignments

1. Generate release notebooks: `mograder generate A1`
2. Upload to Moodle: `mograder moodle upload A1`
3. Publish to hub: `mograder hub publish A1 --url $HUB_URL --token $TOKEN`

### Lectures

1. Generate lecture release: `mograder generate --lecture source/L01-Intro/L01-Intro.py`
2. Publish to hub: `mograder hub publish L01-Intro --url $HUB_URL --token $TOKEN`

The lecture type is auto-detected from PEP 723 metadata — no `--lecture` flag needed on publish if `generate --lecture` was used. Cache warming happens automatically during publish.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `MOGRADER_HUB_SECRET` | HMAC secret for session/token signing (required unless `--dev`) |
| `MOGRADER_HUB_URL` | Hub base URL (for `publish` and `warm-cache` commands) |
| `MOGRADER_HUB_INSTRUCTOR_TOKEN` | Instructor token (for `publish` and `warm-cache` commands) |

## API Endpoints

### Assignments

| Method | Path | Description |
|--------|------|-------------|
| POST | `/upload/{user}/{assignment}` | Upload a notebook |
| GET | `/export/{user}/{assignment}` | Download a notebook |
| POST | `/validate/{user}/{assignment}` | Run validation checks |
| POST | `/reset/{user}/{assignment}` | Reset to release version |
| GET | `/status/{user}/{assignment}` | Get assignment status |
| POST | `/mark-exported/{user}/{assignment}` | Mark as exported |
| POST | `/start-edit/{user}/{assignment}` | Start marimo edit session |
| POST | `/stop-edit/{user}/{assignment}` | Stop marimo edit session |
| `*` | `/edit/{user}/{assignment}/...` | Proxy to marimo editor |

### Lectures

| Method | Path | Description |
|--------|------|-------------|
| POST | `/start-run/{lecture}` | Start per-user marimo run session |
| GET | `/run/{lecture}/` | Redirect to per-user session (auto-starts if needed) |
| `*` | `/run/~{user}/{lecture}/...` | Proxy to marimo run session |

### Shared

| Method | Path | Description |
|--------|------|-------------|
| GET | `/assignments` | List assignments and lectures (with `type` field) |
| GET | `/sessions` | List active sessions (with `type` field) |
| GET | `/release/{name}/{filename}` | Download release file |
| POST | `/publish/{name}` | Publish release (instructor); `?type=lecture` for lectures |
| POST | `/warm-cache` | Warm uv cache (instructor) |

## Authentication

The hub supports multiple authentication methods (checked in order):

1. **Session cookies** — Set after first successful authentication
2. **Trusted proxy header** — `X-Remote-User` from trusted proxy IPs (e.g., university SSO)
3. **Bearer tokens** — HMAC-SHA256 tokens for API access
4. **Dev mode** — No authentication (for local development)

## Security

- **Path traversal hardening** — All file paths are validated against base directories
- **AST safety scanner** — Uploaded code is checked for dangerous patterns (denied imports, builtins)
- **Bubblewrap** (optional) — Filesystem isolation for marimo edit sessions
- **Session isolation** — Each student can only access their own sessions
- **Instructor bypass** — Instructors can access any student's resources
