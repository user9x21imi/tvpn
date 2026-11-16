#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [[ ! -x .venv/bin/python3 ]]; then
    python3 -m venv .venv
    .venv/bin/python3 -m pip install -r requirements-macos.txt
fi
exec .venv/bin/python3 launch.py "$@"
