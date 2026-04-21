#!/usr/bin/env bash
# Deploy the mograder demo to mograder-demo.jrkermode.uk.
# Run from anywhere: bash demo/deploy.sh
set -e

HOST=mograder-demo
REMOTE_DIR=/home/ubuntu/mograder

echo "=== Fetching and resetting to origin/main ==="
ssh $HOST "cd $REMOTE_DIR && git fetch origin && git reset --hard origin/main"

echo "=== Installing dependencies ==="
ssh $HOST "cd $REMOTE_DIR && \$HOME/.local/bin/uv sync --extra hub"

echo "=== Rebuilding demo data ==="
ssh $HOST "cd $REMOTE_DIR && PYTHON=.venv/bin/python MOGRADER=.venv/bin/mograder bash demo/setup_grader_demo.sh"

echo "=== Exporting workshop ==="
WORKSHOP_DIR=$REMOTE_DIR/demo/workshop-export
ssh $HOST "cd $REMOTE_DIR && .venv/bin/mograder workshop export demo/course/demo-workshop/files/demo-workshop.py -o $WORKSHOP_DIR --salt mograder"

echo "=== Updating systemd service ==="
WORKSHOP_SECRET=mograder-demo-secret
COURSE_DIR=$REMOTE_DIR/demo/grader-course
ssh $HOST "sudo sed -i '/MOGRADER_WORKSHOP\|MOGRADER_HUB\|MOGRADER_COURSE_DIR/d' /etc/systemd/system/mograder-demo.service && \
  sudo sed -i '/ExecStart/i Environment=MOGRADER_COURSE_DIR=$COURSE_DIR' /etc/systemd/system/mograder-demo.service && \
  sudo sed -i '/ExecStart/i Environment=MOGRADER_WORKSHOP_DIR=$WORKSHOP_DIR' /etc/systemd/system/mograder-demo.service && \
  sudo sed -i '/ExecStart/i Environment=MOGRADER_WORKSHOP_SECRET=$WORKSHOP_SECRET' /etc/systemd/system/mograder-demo.service && \
  sudo sed -i '/ExecStart/i Environment=MOGRADER_HUB_DEV=1' /etc/systemd/system/mograder-demo.service && \
  sudo sed -i '/ExecStart/i Environment=MOGRADER_HUB_SECRET=$WORKSHOP_SECRET' /etc/systemd/system/mograder-demo.service && \
  sudo systemctl daemon-reload"

echo "=== Restarting service ==="
ssh $HOST "sudo systemctl restart mograder-demo"

echo "=== Checking service ==="
sleep 2
ssh $HOST "sudo systemctl status mograder-demo --no-pager -l | head -15"

echo ""
echo "=== Verifying ==="
# Formgrader root should return 200 (no auth)
ROOT_STATUS=$(curl -s -o /dev/null -w "%{http_code}" https://mograder-demo.jrkermode.uk/)
if [ "$ROOT_STATUS" = "200" ]; then
    echo "Root check: OK (200)"
else
    echo "WARNING: Expected 200, got $ROOT_STATUS"
fi
# Assignments endpoint should return 200 (no auth)
AUTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" https://mograder-demo.jrkermode.uk/assignments)
if [ "$AUTH_STATUS" = "200" ]; then
    echo "Assignments check: OK (200)"
else
    echo "WARNING: Expected 200, got $AUTH_STATUS"
fi
# Workshop keys.json should be public
WS_STATUS=$(curl -s -o /dev/null -w "%{http_code}" https://mograder-demo.jrkermode.uk/keys.json)
if [ "$WS_STATUS" = "200" ]; then
    echo "Workshop keys.json: OK (200)"
else
    echo "WARNING: Expected 200, got $WS_STATUS"
fi
# Dashboard should be accessible
DASH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" https://mograder-demo.jrkermode.uk/dashboard.html)
if [ "$DASH_STATUS" = "200" ]; then
    echo "Workshop dashboard: OK (200)"
else
    echo "WARNING: Expected 200, got $DASH_STATUS"
fi
# Config TOML should be accessible
TOML_STATUS=$(curl -s -o /dev/null -w "%{http_code}" https://mograder-demo.jrkermode.uk/mograder.toml)
if [ "$TOML_STATUS" = "200" ]; then
    echo "Config TOML: OK (200)"
else
    echo "WARNING: Expected 200, got $TOML_STATUS"
fi
echo ""
echo "Deploy complete: https://mograder-demo.jrkermode.uk"
echo "Workshop dashboard: https://mograder-demo.jrkermode.uk/dashboard.html#token=$WORKSHOP_SECRET"
