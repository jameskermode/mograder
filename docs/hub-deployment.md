# Hub Deployment Guide

Operational guide for deploying the mograder hub on a server.

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

## Monitoring

```bash
# Check hub status
systemctl status mograder-hub

# View logs
journalctl -u mograder-hub -f

# Preflight check
mograder hub check /srv/mograder/course
```

## Instructor Token

Generate an instructor token for API access:

```bash
export MOGRADER_HUB_SECRET=$(cat /etc/mograder/hub-secret)
mograder hub generate-token --role instructor admin
```
