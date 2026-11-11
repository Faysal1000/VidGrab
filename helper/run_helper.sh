#!/bin/sh
# Launched by Chrome/Brave/Edge via native messaging. Runs the helper inside its venv.
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/.venv/bin/python" -E -s "$DIR/helper.py" "$@"
