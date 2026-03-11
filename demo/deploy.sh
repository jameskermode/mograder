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
# Formgrader root should redirect to login (303) when unauthenticated
ROOT_STATUS=$(curl -s -o /dev/null -w "%{http_code}" https://mograder-demo.jrkermode.uk/)
if [ "$ROOT_STATUS" = "303" ]; then
    echo "Root check: OK (303 redirect to /login)"
else
    echo "WARNING: Expected 303, got $ROOT_STATUS"
fi
# Login page should return 200
LOGIN_STATUS=$(curl -s -o /dev/null -w "%{http_code}" https://mograder-demo.jrkermode.uk/login)
if [ "$LOGIN_STATUS" = "200" ]; then
    echo "Login page: OK (200)"
else
    echo "WARNING: Expected 200, got $LOGIN_STATUS"
fi
# Assignments endpoint should require Bearer auth (401)
AUTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" https://mograder-demo.jrkermode.uk/assignments)
if [ "$AUTH_STATUS" = "401" ]; then
    echo "Auth check: OK (401 for unauthenticated)"
else
    echo "WARNING: Expected 401, got $AUTH_STATUS"
fi
echo ""
echo "Deploy complete: https://mograder-demo.jrkermode.uk"
