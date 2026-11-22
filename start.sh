#!/bin/bash
# SortSmart V2 — All-In-One Unified Server (Frontend + Backend + Database)
cd "$(dirname "$0")"

echo "🌿 Starting SortSmart V2 (Frontend + Backend + Database)..."

# Pick Python interpreter
if [ -f "/Users/jatingarg/Desktop/SortSmart/.venv/bin/python" ]; then
    PYTHON="/Users/jatingarg/Desktop/SortSmart/.venv/bin/python"
elif [ -d ".venv" ]; then
    PYTHON=".venv/bin/python"
else
    PYTHON="python3"
fi

echo "Using Python: $PYTHON"
echo "Serving on: http://localhost:8000 and LAN http://0.0.0.0:8000"
exec $PYTHON server.py --host 0.0.0.0 --port 8000
