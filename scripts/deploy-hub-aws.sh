#!/usr/bin/env bash
# Deploy the mograder hub to an AWS Ubuntu instance.
#
# Usage:
#   bash scripts/deploy-hub-aws.sh --host HOSTNAME --key SSH_KEY [OPTIONS]
#
# Options:
#   --host HOSTNAME         SSH hostname (required)
#   --key SSH_KEY           Path to SSH private key (required)
#   --user USER             SSH user (default: ubuntu)
#   --volume DEVICE         Data volume device (default: /dev/nvme1n1)
#   --mograder-version VER  Minimum mograder version (default: >=0.2.6)
#
# Prerequisites:
#   - Ubuntu 24.04 instance with SSH access
#   - An attached EBS data volume (default: /dev/nvme1n1)
#
# What this script does:
#   1. Mounts the data volume at /srv/mograder
#   2. Installs bubblewrap for sandboxing
#   3. Creates a mograder service user
#   4. Installs uv and mograder[hub] from PyPI
#   5. Writes a default mograder.toml (hub + security config)
#   6. Generates a hub secret
#   7. Creates and starts a systemd service
#
# After running, you should:
#   - Edit /srv/mograder/course/mograder.toml to add transport config
#   - Publish assignments: mograder hub publish ...
#   - Warm the uv cache: mograder hub warm-cache --all
#   - Set up a reverse proxy with TLS for external access
#
# Tip: If the instance doesn't have an Elastic IP, its public IP changes
# on every stop/start cycle. Assign an Elastic IP in the AWS console
# (EC2 > Elastic IPs) to get a stable address for DNS and reverse proxies.
set -euo pipefail

# --- Parse arguments ---
HOST=""
KEY=""
SSH_USER="ubuntu"
VOLUME="/dev/nvme1n1"
MOGRADER_VERSION=">=0.2.6"

while [[ $# -gt 0 ]]; do
    case $1 in
        --host) HOST="$2"; shift 2 ;;
        --key) KEY="$2"; shift 2 ;;
        --user) SSH_USER="$2"; shift 2 ;;
        --volume) VOLUME="$2"; shift 2 ;;
        --mograder-version) MOGRADER_VERSION="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -z "$HOST" || -z "$KEY" ]]; then
    echo "Usage: $0 --host HOSTNAME --key SSH_KEY [--user USER] [--volume DEVICE] [--mograder-version VER]"
    exit 1
fi

SSH="ssh -i $KEY -o StrictHostKeyChecking=accept-new $SSH_USER@$HOST"
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== mograder hub deployment ===${NC}"
echo "Host: $SSH_USER@$HOST"
echo "Volume: $VOLUME"

# --- Phase 1: System setup ---
echo -e "\n${YELLOW}Phase 1: System setup${NC}"

$SSH "bash -s" << SETUP
set -euo pipefail

# Mount data volume
if mountpoint -q /srv/mograder; then
    echo "  /srv/mograder already mounted"
else
    echo "  Mounting $VOLUME at /srv/mograder..."
    # Unmount from default location if needed
    sudo umount $VOLUME 2>/dev/null || true
    sudo mkdir -p /srv/mograder
    # Format only if not already formatted
    if ! sudo blkid $VOLUME | grep -q ext4; then
        sudo mkfs.ext4 $VOLUME
    fi
    sudo mount $VOLUME /srv/mograder
    # Add to fstab if not already present
    if ! grep -q /srv/mograder /etc/fstab; then
        echo '$VOLUME /srv/mograder ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab
    fi
fi

# Install bubblewrap
if command -v bwrap &>/dev/null; then
    echo "  bubblewrap already installed"
else
    echo "  Installing bubblewrap..."
    sudo apt-get update -qq && sudo apt-get install -y -qq bubblewrap
fi

# Create service user
if id mograder &>/dev/null; then
    echo "  mograder user already exists"
else
    echo "  Creating mograder user..."
    sudo useradd -r -m -s /bin/bash mograder
fi
sudo chown -R mograder:mograder /srv/mograder

# Install uv
if sudo -u mograder bash -c 'test -x ~/.local/bin/uv'; then
    echo "  uv already installed"
else
    echo "  Installing uv..."
    sudo -u mograder bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
fi
SETUP

# --- Phase 2: Application setup ---
echo -e "\n${YELLOW}Phase 2: Application setup${NC}"

$SSH "sudo -u mograder bash -s" << 'APP'
set -euo pipefail
cd /srv/mograder
mkdir -p course
cd course

# Init uv project if needed
if [ ! -f pyproject.toml ]; then
    echo "  Initialising uv project..."
    ~/.local/bin/uv init --bare
fi

# Install/update mograder
echo "  Installing mograder[hub]..."
APP

# Pass the version variable (not single-quoted heredoc)
$SSH "sudo -u mograder bash -c 'cd /srv/mograder/course && ~/.local/bin/uv add \"mograder[hub]$MOGRADER_VERSION\" --refresh-package mograder 2>&1 | tail -3'"

# Write mograder.toml (only if it doesn't exist — don't overwrite user config)
$SSH "sudo -u mograder bash -s" << 'TOML'
set -euo pipefail
CONF=/srv/mograder/course/mograder.toml
if [ -f "$CONF" ]; then
    echo "  mograder.toml already exists — skipping"
else
    echo "  Writing default mograder.toml..."
    cat > "$CONF" << 'EOF'
[defaults]
headless_edit = true
timeout = 300

[rlimits]
cpu = 300
nproc = 256
nofile = 256
as = 8589934592  # 8 GB

[security]
use_bubblewrap = true

[hub]
port = 8080
notebooks_dir = "hub-notebooks"
release_dir = "hub-release"
session_ttl = 3600
trusted_header = "X-Remote-User"
uv_cache_dir = "/srv/mograder/.uv-cache"
EOF
fi
TOML

# --- Phase 3: Secrets and service ---
echo -e "\n${YELLOW}Phase 3: Secrets and systemd service${NC}"

$SSH "bash -s" << 'SERVICE'
set -euo pipefail

# Generate hub secret (preserve existing)
sudo mkdir -p /etc/mograder
if [ -f /etc/mograder/hub-secret ]; then
    echo "  Hub secret already exists — keeping"
else
    echo "  Generating hub secret..."
    python3 -c "import secrets; print(secrets.token_hex(32))" | sudo tee /etc/mograder/hub-secret > /dev/null
    sudo chmod 600 /etc/mograder/hub-secret
fi

# Write env file
echo "  Writing /etc/mograder/env..."
SECRET=$(sudo cat /etc/mograder/hub-secret)
sudo bash -c "cat > /etc/mograder/env << EOF
MOGRADER_HUB_SECRET=$SECRET
MOGRADER_COURSE_DIR=/srv/mograder/course
EOF"
sudo chmod 600 /etc/mograder/env

# Write systemd unit
echo "  Writing mograder-hub.service..."
sudo bash -c 'cat > /etc/systemd/system/mograder-hub.service << EOF
[Unit]
Description=mograder hub (student-facing)
After=network.target

[Service]
Type=simple
User=mograder
Group=mograder
WorkingDirectory=/srv/mograder/course
EnvironmentFile=/etc/mograder/env
Environment=PATH=/home/mograder/.local/bin:/usr/local/bin:/usr/bin
ExecStart=/home/mograder/.local/bin/uv run mograder hub \
    --port 8080 --host 0.0.0.0 --session-ttl 3600 --headless
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF'

sudo systemctl daemon-reload
sudo systemctl enable --now mograder-hub
sudo systemctl restart mograder-hub
SERVICE

# --- Phase 4: Verification ---
echo -e "\n${YELLOW}Phase 4: Verification${NC}"
sleep 3

STATUS=$($SSH "sudo systemctl is-active mograder-hub")
if [ "$STATUS" = "active" ]; then
    echo -e "  Service: ${GREEN}active${NC}"
else
    echo "  Service: FAILED ($STATUS)"
    $SSH "sudo journalctl -u mograder-hub --no-pager -n 10"
    exit 1
fi

HTTP_CODE=$($SSH "curl -s -o /dev/null -w '%{http_code}' -H 'X-Remote-User: test' http://localhost:8080/")
if [ "$HTTP_CODE" = "200" ]; then
    echo -e "  Hub HTTP check: ${GREEN}200 OK${NC}"
else
    echo "  Hub HTTP check: FAILED ($HTTP_CODE)"
fi

echo -e "\n${YELLOW}Generating instructor token...${NC}"
$SSH "SECRET=\$(sudo cat /etc/mograder/hub-secret) && sudo -u mograder bash -c \"cd /srv/mograder/course && MOGRADER_HUB_SECRET=\$SECRET /home/mograder/.local/bin/uv run mograder hub generate-token --role instructor admin\""

echo -e "\n${GREEN}=== Deployment complete ===${NC}"
echo "Hub is running at http://$HOST:8080 (port 8080 must be reachable)"
echo ""
echo "Next steps:"
echo "  1. Edit /srv/mograder/course/mograder.toml to add transport config"
echo "  2. Set up a reverse proxy with TLS and authentication"
echo "  3. Publish assignments:  mograder hub publish ASSIGNMENT --url HUB_URL --token TOKEN"
echo "  4. Warm the uv cache:   mograder hub warm-cache --url HUB_URL --token TOKEN"
