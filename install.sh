#!/usr/bin/env bash
set -euo pipefail

# Install the Tillio CLI binary.
#
# This script is used by internal tooling (SEGA downloads publishing) and can also
# be used manually. It downloads the right binary for the current OS/arch and
# places it on PATH.

BIN_NAME="tillio"
INSTALL_DIR_DEFAULT="/usr/local/bin"

# Default download base. Internal SEGA publishing typically serves:
#   ${BASE_URL}/cli/releases/<version>/tillio-<os>-<arch>
BASE_URL_DEFAULT="${TILLIO_DOWNLOADS_BASE_URL:-https://downloads.tillio.ai}"

usage() {
  cat <<'EOF'
Usage:
  install.sh [--version <version>] [--base-url <url>] [--install-dir <dir>]

Options:
  --version      Release version to install (required)
  --base-url     Base URL hosting /cli (default: $TILLIO_DOWNLOADS_BASE_URL or https://downloads.tillio.ai)
  --install-dir  Install directory (default: /usr/local/bin)

Environment:
  TILLIO_DOWNLOADS_BASE_URL  Overrides default base URL
EOF
}

VERSION=""
BASE_URL="$BASE_URL_DEFAULT"
INSTALL_DIR="$INSTALL_DIR_DEFAULT"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      VERSION="${2:-}"; shift 2 ;;
    --base-url)
      BASE_URL="${2:-}"; shift 2 ;;
    --install-dir)
      INSTALL_DIR="${2:-}"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "$VERSION" ]]; then
  echo "--version is required" >&2
  usage
  exit 2
fi

uname_s="$(uname -s | tr '[:upper:]' '[:lower:]')"
uname_m="$(uname -m)"

case "$uname_s" in
  darwin) os="darwin" ;;
  linux) os="linux" ;;
  *)
    echo "Unsupported OS: $uname_s" >&2
    exit 1
    ;;
esac

case "$uname_m" in
  x86_64|amd64) arch="x86_64" ;;
  arm64|aarch64) arch="arm64" ;;
  *)
    echo "Unsupported arch: $uname_m" >&2
    exit 1
    ;;
esac

asset="tillio-${os}-${arch}"
url="${BASE_URL%/}/cli/releases/${VERSION}/${asset}"

tmp="$(mktemp -t tillio-cli.XXXXXX)"
cleanup() { rm -f "$tmp" "$tmp.sums"; }
trap cleanup EXIT

echo "Downloading: $url"
curl -fsSL "$url" -o "$tmp"
chmod 755 "$tmp"

# Integrity: verify against SHA256SUMS in the release dir when present.
sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else echo ""; fi
}
sums_url="${url%/*}/SHA256SUMS"
if curl -fsSL "$sums_url" -o "$tmp.sums" 2>/dev/null; then
  expected="$(awk -v f="$asset" '$2==f || $2=="*"f {print $1; exit}' "$tmp.sums")"
  actual="$(sha256_of "$tmp")"
  rm -f "$tmp.sums"
  if [[ -n "$actual" && -n "$expected" ]]; then
    if [[ "$actual" != "$expected" ]]; then
      echo "ERROR: checksum mismatch for $asset (expected $expected, got $actual)" >&2
      exit 4
    fi
    echo "Verified: sha256 OK"
  fi
fi

dest="$INSTALL_DIR/$BIN_NAME"
if [[ ! -d "$INSTALL_DIR" ]]; then
  echo "Creating install dir: $INSTALL_DIR"
  mkdir -p "$INSTALL_DIR"
fi

if [[ -w "$INSTALL_DIR" ]]; then
  mv "$tmp" "$dest"
else
  echo "Installing to $dest (requires sudo)"
  sudo mv "$tmp" "$dest"
fi

echo "Installed: $dest"
"$dest" --help >/dev/null

# Offer to add install dir to PATH if not already there
if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
  shell_rc="$HOME/.bashrc"
  if [[ -n "${ZSH_VERSION:-}" ]] || [[ "$SHELL" == */zsh ]]; then
    shell_rc="$HOME/.zshrc"
  fi

  if [[ -t 0 ]]; then
    echo "$INSTALL_DIR is not in your PATH."
    read -r -p "Add it to $shell_rc? [Y/n] " add_path
    if [[ "${add_path:-Y}" =~ ^[Yy] ]]; then
      echo "" >> "$shell_rc"
      echo "export PATH=\"$INSTALL_DIR:\$PATH\"" >> "$shell_rc"
      echo "Added to $shell_rc. Run: source $shell_rc"
    else
      echo "Skipped. Add manually:"
      echo "  echo 'export PATH=\"$INSTALL_DIR:\$PATH\"' >> $shell_rc"
    fi
  else
    # Non-interactive: auto-add
    echo "" >> "$shell_rc"
    echo "export PATH=\"$INSTALL_DIR:\$PATH\"" >> "$shell_rc"
    echo "Added $INSTALL_DIR to PATH in $shell_rc"
  fi
fi

echo "OK"
