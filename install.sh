#!/usr/bin/env bash
# Pi-NOMAD installer for Raspberry Pi OS (64-bit, Bookworm or newer).
# Usage: sudo ./install.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then echo "Run with sudo." >&2; exit 1; fi
if [[ "$(uname -m)" != "aarch64" ]]; then
  echo "Warning: expected 64-bit ARM (aarch64), found $(uname -m)." >&2
fi

NOMAD_DATA="${NOMAD_DATA:-/srv/nomad}"
INSTALL_DIR="${INSTALL_DIR:-/opt/pi-nomad}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Installing Docker if missing"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

echo "==> Creating data directories in $NOMAD_DATA"
mkdir -p "$NOMAD_DATA"/{zim,notes,maps,books}
if [[ ! -f "$NOMAD_DATA/zim/library.xml" ]]; then
  cat > "$NOMAD_DATA/zim/library.xml" <<'XML'
<?xml version="1.0" encoding="UTF-8"?>
<library version="20110515"></library>
XML
fi

echo "==> Installing stack to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cp -r "$SRC_DIR/compose.yaml" "$SRC_DIR/command-center" "$INSTALL_DIR/"
echo "NOMAD_DATA=$NOMAD_DATA" > "$INSTALL_DIR/.env"

echo "==> Starting services"
docker compose -f "$INSTALL_DIR/compose.yaml" --env-file "$INSTALL_DIR/.env" up -d --build

echo
echo "Done. Open http://$(hostname).local/ (or this Pi's IP address)."
echo "Add content from the dashboard: Content Manager (libraries) and Map regions (maps)."
echo "ZIM files copied into $NOMAD_DATA/zim by hand are picked up with 'Rescan folder'."
