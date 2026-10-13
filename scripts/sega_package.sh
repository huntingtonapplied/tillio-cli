#!/usr/bin/env bash
set -euo pipefail

# SEGA entrypoint for packaging Tillio CLI.
#
# Usage (examples):
#   TARGET=darwin ./scripts/sega_package.sh
#   TARGET=linux  ./scripts/sega_package.sh
#   TARGET=pypi   ./scripts/sega_package.sh

TARGET="${TARGET:-darwin}"

case "$TARGET" in
  darwin|linux)
    exec "$(dirname "$0")/build_binary.sh"
    ;;
  pypi)
    exec "$(dirname "$0")/build_wheel.sh"
    ;;
  *)
    echo "Unknown TARGET=$TARGET (expected: darwin|linux|pypi)" >&2
    exit 2
    ;;
esac
