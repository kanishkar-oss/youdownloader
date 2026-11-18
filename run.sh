#!/bin/sh
# Run YouDownloader from source on macOS / Linux (prefers the project .venv).
#   python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then exec .venv/bin/python main.py "$@"; fi
exec python3 main.py "$@"
