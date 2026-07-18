#!/usr/bin/env bash
set -euo pipefail

# Build wheel/sdist into dist/.

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv-build}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install -U pip
"$VENV_DIR/bin/pip" install -U build

"$VENV_DIR/bin/python" -m build
echo "Built artifacts in dist/"
