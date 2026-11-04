#!/usr/bin/env bash
set -e
echo "--> Initializing Cloud Session Cookies..."
python3 import_session.py || true

echo "--> Launching Meraki Career Command Center on Port ${PORT:-5055}..."
python3 app.py
