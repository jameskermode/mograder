#!/usr/bin/env bash
# Deploy the mograder demo to mograder-demo.jrkermode.uk.
# Run from anywhere: bash demo/deploy.sh
set -e

HOST=mograder-demo
REMOTE_DIR=/home/ubuntu/mograder

echo "=== Pulling latest code ==="
ssh $HOST "cd $REMOTE_DIR && git pull"

echo "=== Installing dependencies ==="
ssh $HOST "cd $REMOTE_DIR && \$HOME/.local/bin/uv sync --extra grader --extra asgi"

echo "=== Rebuilding demo data ==="
ssh $HOST "cd $REMOTE_DIR && PYTHON=.venv/bin/python MOGRADER=.venv/bin/mograder bash demo/setup_formgrader_demo.sh"

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
echo ""
echo "Deploy complete: https://mograder-demo.jrkermode.uk"
