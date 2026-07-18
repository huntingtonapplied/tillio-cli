#!/usr/bin/env bash
set -euo pipefail

# Build a standalone 'tillio' binary with PyInstaller.
# Intended for both local use and SEGA/GitHub CI runners.

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv-build}"
NAME="${NAME:-tillio}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install -U pip
"$VENV_DIR/bin/pip" install -e .
"$VENV_DIR/bin/pip" install -U pyinstaller

"$VENV_DIR/bin/pyinstaller" --onefile --name "$NAME" tillio_cli/main.py

if [[ ! -f "dist/$NAME" ]]; then
  echo "Expected dist/$NAME to exist" >&2
  exit 1
fi

"dist/$NAME" --help >/dev/null
echo "Built dist/$NAME"
