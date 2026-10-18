#!/usr/bin/env sh
set -eu

# Resolve the project directory so this script works from any current directory.
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON=${PYTHON:-python3}
VENV_DIR="$PROJECT_DIR/.venv"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "Python 3.9 or newer is required (python3 was not found)." >&2
    exit 1
fi

if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
    echo "Python 3.9 or newer is required." >&2
    exit 1
fi

# Create an isolated environment once, then make sure dependencies are present.
if [ ! -x "$VENV_DIR/bin/python" ]; then
    "$PYTHON" -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --disable-pip-version-check \
    -r "$PROJECT_DIR/requirements.txt"

# Run from the project directory so SQLite stores app.db alongside the source.
cd "$PROJECT_DIR"
exec "$VENV_DIR/bin/python" -m uvicorn main:app \
    --host "${HOST:-127.0.0.1}" \
    --port "${PORT:-8000}"
