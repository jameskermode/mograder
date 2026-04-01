# Hub Deployment Guide

Operational guide for deploying the mograder hub on a server.

## Quick Deploy (AWS)

For an AWS Ubuntu instance with an attached EBS data volume:

```bash
bash scripts/deploy-hub-aws.sh --host YOUR_HOST --key ~/.ssh/YOUR_KEY.pem
```

This installs all dependencies, creates a service user, configures the hub,
and starts a systemd service. See the script for options (`--volume`,
`--mograder-version`). After running, edit `mograder.toml` on the server to
add your transport config (Moodle, HTTPS, etc.), then publish assignments and
warm the uv cache.

## Prerequisites

- Python 3.11+
- `uv` package manager
- `marimo` installed
- `bubblewrap` (`bwrap`) — recommended for sandboxing

## Secret Generation

```bash
# Generate a secret
python -c "import secrets; print(secrets.token_hex(32))" > /etc/mograder/hub-secret

# Set permissions
chmod 600 /etc/mograder/hub-secret
```

## Systemd Unit

Create `/etc/systemd/system/mograder-hub.service`:

```ini
[Unit]
Description=mograder hub server
After=network.target

[Service]
Type=simple
User=mograder
Group=mograder
WorkingDirectory=/srv/mograder/course
Environment=MOGRADER_HUB_SECRET=<your-secret-here>
Environment=MOGRADER_COURSE_DIR=/srv/mograder/course
Environment=PATH=/home/mograder/.local/bin:/usr/local/bin:/usr/bin
ExecStart=/home/mograder/.local/bin/uv run mograder hub \
    --port 8080 \
    --host 127.0.0.1 \
    --session-ttl 3600
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now mograder-hub
```

## Reverse Proxy (Caddy)

```
hub.example.com {
    reverse_proxy localhost:8080

    # WebSocket support
    @websockets {
        header Connection *Upgrade*
        header Upgrade websocket
    }
    reverse_proxy @websockets localhost:8080
}
```

## Reverse Proxy (nginx)

```nginx
server {
    listen 443 ssl;
    server_name hub.example.com;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Remote-User $remote_user;

        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }
}
```

## EBS Volume Setup

For persistent student data on AWS:

```bash
# Create and mount EBS volume
mkfs.ext4 /dev/xvdf
mkdir -p /srv/mograder/hub-notebooks
mount /dev/xvdf /srv/mograder/hub-notebooks

# Add to fstab
echo '/dev/xvdf /srv/mograder/hub-notebooks ext4 defaults 0 2' >> /etc/fstab
```

## Bubblewrap

When `[security] use_bubblewrap = true` is set in `mograder.toml`, each marimo
edit session runs inside a bubblewrap sandbox:

- Read-only root filesystem
- Writable student directory only
- Network isolation (`--unshare-net`)
- Shared uv cache (read-only)

**Residual risk**: Without bubblewrap, students can read/write arbitrary files
on the host as the service user. Bubblewrap mitigates this but is not a
complete container solution.

## Access Control (User Allowlist)

By default the hub allows any authenticated user. To restrict access to
enrolled students, sync a user allowlist from Moodle or upload one manually.

### Moodle courses

Fetch enrolled participants and push them to the hub:

```bash
mograder moodle sync-users --hub-url HUB_URL --hub-token TOKEN
```

This calls `list_participants()` on the first Moodle assignment in the config,
POSTs the username list to the hub's `/sync-users` endpoint, and updates
the local gradebook with student full names (for grader display). Run
`mograder moodle sync` first to populate assignment metadata.

Use `--dry-run` to preview the user list without syncing.

If `--hub-url` is omitted, writes `allowed_users.txt` to the local course
directory instead (useful when the hub runs on the same machine).

### HTTPS transport (manual)

Create a text file with one username per line (`#` comments allowed), then
upload it:

```bash
mograder hub sync-users users.txt --url HUB_URL --token TOKEN
```

### How it works

The hub reads `allowed_users.txt` in the course directory on every request.
If the file exists, only listed usernames (and instructors) may access the
hub. Non-enrolled users see a friendly HTML error page asking them to contact
their instructor.

- **No file** → all authenticated users are allowed (backwards compatible)
- **Empty file** → only instructors can access
- **Instructors** always bypass the allowlist
- The file is hot-reloaded — no restart needed after syncing

To remove the restriction entirely, delete `allowed_users.txt` from the
course directory.

## Monitoring

```bash
# Check hub status
systemctl status mograder-hub

# View logs
journalctl -u mograder-hub -f

# Preflight check
mograder hub check /srv/mograder/course
```

## Publishing Lectures

Lectures can be published alongside assignments. Unlike assignments, lectures are served in read-only `marimo run --include-code` mode — students can see code but cannot modify the shared source.

### Generate and publish

```bash
# Generate lecture release (strips slide layout, injects type metadata)
mograder generate --lecture source/L01-Intro/L01-Intro.py

# Publish to hub (auto-detects lecture type from PEP 723 metadata)
mograder hub publish L01-Intro --url $HUB_URL --token $TOKEN
```

Publishing automatically:
- Uploads the notebook and auxiliary files (images, data, helper modules)
- Creates a shared `.venv` from PEP 723 dependencies
- Stores `"type": "lecture"` in the release manifest

### How lecture sessions work

- Each student gets a **per-user** `marimo run` process (isolated widget/execution state)
- Sessions are proxied through the hub at `/run/user/{username}/{lecture}/`
- The deep link `/run/{lecture}/` shows a spinner page, auto-starts the session, and redirects to the per-user URL
- Inter-lecture links (generated by `mograder generate --lecture`) use `/run/{lecture}/` format and work automatically
- If a session is already running, deep links reconnect to it
- Sessions are subject to the same idle timeout (`session_ttl`) as assignment edit sessions

### Deep links

Both assignments and lectures support shareable deep links:

```
https://hub.example.com/edit/A1-Intro-to-SciML   # assignment
https://hub.example.com/run/L01-Introduction       # lecture
```

**Assignment deep links** (`/edit/{assignment}`):

1. Show a spinner page while starting
2. Auto-download the release to the student's workspace (if they don't have a copy yet — existing edits are never overwritten)
3. Start a `marimo edit` session
4. Redirect to the per-user editor at `/edit/user/{username}/{assignment}/`

**Lecture deep links** (`/run/{lecture}`):

1. Show a spinner page while starting
2. Start a `marimo run --include-code` session from the release directory
3. Redirect to the per-user viewer at `/run/user/{username}/{lecture}/`

These links can be embedded in Moodle assignment pages, lecture notebooks, or shared directly. The `user` path segment in per-user URLs is reserved — assignment and lecture names cannot be `"user"`.

### Resource considerations

Since each student gets their own marimo process per lecture, plan for:
- **Memory**: ~50–100 MB per session (varies with notebook complexity)
- **Ports**: One port per active session (allocated from base port upward)
- **CPU**: Idle sessions consume minimal CPU; active computation is per-user

The `session_ttl` setting (default 3600s) automatically culls idle sessions.

## Instructor Token

Generate an instructor token for API access:

```bash
export MOGRADER_HUB_SECRET=$(cat /etc/mograder/hub-secret)
mograder hub generate-token --role instructor admin
```
