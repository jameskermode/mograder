#!/usr/bin/env bash
# bootstrap_new_host.sh — first-time setup for a fresh Oracle Ubuntu host
# that will run the mograder demo at https://mograder-demo.jrkermode.uk/.
#
# Designed to run exactly once on a freshly-launched VM, but is idempotent:
# rerunning is safe and only patches what's missing.
#
# Run as the `ubuntu` user (Oracle's Ubuntu image default). Needs passwordless
# sudo (also default).
#
#   ssh ubuntu@<NEW_IP>
#   curl -fsSL https://raw.githubusercontent.com/jameskermode/mograder/main/demo/bootstrap_new_host.sh -o /tmp/bootstrap.sh
#   bash /tmp/bootstrap.sh
#
# Or, if the repo is already cloned at /home/ubuntu/mograder:
#   bash /home/ubuntu/mograder/demo/bootstrap_new_host.sh
#
# Env overrides (defaults shown):
#   SWAP_GB=4
#   REPO_URL=https://github.com/jameskermode/mograder.git
#   BRANCH=main
#   REPO_DIR=/home/ubuntu/mograder
#   HOSTNAME_FQDN=mograder-demo.jrkermode.uk

set -euo pipefail

SWAP_GB="${SWAP_GB:-4}"
REPO_URL="${REPO_URL:-https://github.com/jameskermode/mograder.git}"
BRANCH="${BRANCH:-main}"
REPO_DIR="${REPO_DIR:-/home/ubuntu/mograder}"
HOSTNAME_FQDN="${HOSTNAME_FQDN:-mograder-demo.jrkermode.uk}"

if [ "$(id -un)" != "ubuntu" ]; then
    echo "This script must run as the 'ubuntu' user." >&2
    exit 1
fi

log() { printf '\n=== %s ===\n' "$*"; }

# ---------------------------------------------------------------------------
log "1. Swap (${SWAP_GB} GB)"
# ---------------------------------------------------------------------------
if [ ! -f /swapfile ]; then
    sudo fallocate -l "${SWAP_GB}G" /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    if ! grep -q '^/swapfile' /etc/fstab; then
        echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
    fi
    echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-mograder.conf >/dev/null
    sudo sysctl --system >/dev/null
    echo "Swap created."
else
    echo "Swapfile already present, skipping."
fi
swapon --show
free -h

# ---------------------------------------------------------------------------
log "2. Apt packages"
# ---------------------------------------------------------------------------
sudo DEBIAN_FRONTEND=noninteractive apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    git curl ca-certificates rsync \
    debian-keyring debian-archive-keyring apt-transport-https

# ---------------------------------------------------------------------------
log "3. Caddy (official Cloudsmith repo)"
# ---------------------------------------------------------------------------
if ! command -v caddy >/dev/null 2>&1; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
    sudo apt-get update -y
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y caddy
else
    echo "Caddy $(caddy version | head -1) already installed."
fi

# ---------------------------------------------------------------------------
log "4. uv"
# ---------------------------------------------------------------------------
if [ ! -x "$HOME/.local/bin/uv" ]; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
uv --version

# ---------------------------------------------------------------------------
log "5. Repo clone + uv sync"
# ---------------------------------------------------------------------------
if [ ! -d "$REPO_DIR/.git" ]; then
    git clone --branch "$BRANCH" "$REPO_URL" "$REPO_DIR"
else
    git -C "$REPO_DIR" fetch origin
    git -C "$REPO_DIR" checkout "$BRANCH"
    git -C "$REPO_DIR" reset --hard "origin/$BRANCH"
fi
cd "$REPO_DIR"
"$HOME/.local/bin/uv" sync --extra hub

# ---------------------------------------------------------------------------
log "6. systemd unit"
# ---------------------------------------------------------------------------
sudo tee /etc/systemd/system/mograder-demo.service >/dev/null <<EOF
[Unit]
Description=mograder demo (formgrader + assignment server)
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=$REPO_DIR
Environment=MOGRADER_ENROLLMENT_CODE=demo
Environment=MOGRADER_COURSE_DIR=$REPO_DIR/demo/grader-course
Environment=MOGRADER_WORKSHOP_DIR=$REPO_DIR/demo/workshop-export
Environment=MOGRADER_WORKSHOP_SECRET=mograder-demo-secret
Environment=MOGRADER_HUB_DEV=1
Environment=MOGRADER_HUB_SECRET=mograder-demo-secret
ExecStart=$REPO_DIR/.venv/bin/python -m uvicorn demo.demo_app:app --host 0.0.0.0 --port 8080
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload

# ---------------------------------------------------------------------------
log "7. Caddyfile"
# ---------------------------------------------------------------------------
sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
$HOSTNAME_FQDN {
    reverse_proxy localhost:8080
}
EOF

# ---------------------------------------------------------------------------
log "8. Initial demo data (setup_grader_demo.sh)"
# ---------------------------------------------------------------------------
PYTHON="$REPO_DIR/.venv/bin/python" \
MOGRADER="$REPO_DIR/.venv/bin/mograder" \
    bash "$REPO_DIR/demo/setup_grader_demo.sh"

# ---------------------------------------------------------------------------
log "9. Workshop export"
# ---------------------------------------------------------------------------
"$REPO_DIR/.venv/bin/mograder" workshop export \
    "$REPO_DIR/demo/course/demo-workshop/files/demo-workshop.py" \
    -o "$REPO_DIR/demo/workshop-export" --salt mograder

# ---------------------------------------------------------------------------
log "10. Enable services"
# ---------------------------------------------------------------------------
sudo systemctl enable --now caddy
sudo systemctl enable --now mograder-demo
sudo systemctl restart mograder-demo

# ---------------------------------------------------------------------------
log "11. Health check (localhost:8080)"
# ---------------------------------------------------------------------------
ok=0
for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null http://localhost:8080/; then
        ok=1
        break
    fi
    sleep 2
done
if [ "$ok" -ne 1 ]; then
    echo "Hub did not come up on localhost:8080 within 60 s." >&2
    sudo journalctl -u mograder-demo --no-pager -n 40 >&2 || true
    exit 1
fi

ip4=$(curl -fsS https://api.ipify.org 2>/dev/null || echo "unknown")
cat <<MSG

==========================================
Bootstrap complete.

Public IP:    $ip4
Hostname:     $HOSTNAME_FQDN (DNS NOT yet flipped)
Hub backend:  localhost:8080  (200 OK)
Caddy:        listening on 80/443 (Let's Encrypt cert pending DNS)
Swap:         $(swapon --show=NAME,SIZE --noheadings | head -1 || echo 'none')

Next steps (do these from your local machine):

1. Final rsync of student data from old host:
     rsync -av --delete \\
       ubuntu@145.241.236.160:$REPO_DIR/demo/grader-course/hub-notebooks/ \\
       ubuntu@$ip4:$REPO_DIR/demo/grader-course/hub-notebooks/

2. Smoke-test via SSH tunnel:
     ssh -L 8080:localhost:8080 ubuntu@$ip4
     # in another terminal:
     curl -i http://localhost:8080/
     curl -i http://localhost:8080/grader -L
     curl -i http://localhost:8080/assignments
     curl -i http://localhost:8080/keys.json
     curl -i http://localhost:8080/dashboard.html
     curl -i http://localhost:8080/mograder.toml

3. Flip DNS A record for $HOSTNAME_FQDN -> $ip4

4. Update GitHub repo secret DEMO_SSH_KNOWN_HOSTS:
     ssh-keyscan $ip4 2>/dev/null

5. Update local ~/.ssh/config 'mograder-demo' alias to point at $ip4
==========================================
MSG
