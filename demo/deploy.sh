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
curl -sf https://mograder-demo.jrkermode.uk/assignments | python3 -m json.tool
echo ""
echo "Deploy complete: https://mograder-demo.jrkermode.uk"
