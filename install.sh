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
mkdir -p "$NOMAD_DATA"/{zim,notes,maps,books,kolibri}
if [[ ! -f "$NOMAD_DATA/zim/library.xml" ]]; then
  cat > "$NOMAD_DATA/zim/library.xml" <<'XML'
<?xml version="1.0" encoding="UTF-8"?>
<library version="20110515"></library>
XML
fi

echo "==> Installing the power helper (lets the dashboard shut down or restart the Pi)"
POWER_DIR=/var/lib/pi-nomad/power
mkdir -p "$POWER_DIR"
rm -f "$POWER_DIR/request"          # never act on a request left over from before
cat > /usr/local/sbin/pi-nomad-power <<'SH'
#!/bin/sh
# Runs as root when the Pi-NOMAD dashboard leaves a request. Two words are understood;
# anything else is thrown away.
f=/var/lib/pi-nomad/power/request
[ -f "$f" ] || exit 0
want=$(head -c 16 "$f" | tr -cd 'a-z')
rm -f "$f"
sleep 2                              # let the dashboard get its answer first
case "$want" in
  poweroff) systemctl poweroff ;;
  reboot)   systemctl reboot ;;
esac
SH
chmod 755 /usr/local/sbin/pi-nomad-power
cat > /etc/systemd/system/pi-nomad-power.path <<'UNIT'
[Unit]
Description=Pi-NOMAD: watch for a shut down or restart request from the dashboard

[Path]
PathChanged=/var/lib/pi-nomad/power/request
Unit=pi-nomad-power.service

[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/pi-nomad-power.service <<'UNIT'
[Unit]
Description=Pi-NOMAD: shut down or restart when the dashboard asks

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/pi-nomad-power
UNIT
systemctl daemon-reload
systemctl enable --now pi-nomad-power.path
touch "$POWER_DIR/helper-installed"

echo "==> Installing stack to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
if [[ "$SRC_DIR" != "$INSTALL_DIR" ]]; then
  rm -rf "$INSTALL_DIR/command-center" "$INSTALL_DIR/kolibri"    # no stale files from older versions
  cp -r "$SRC_DIR/compose.yaml" "$SRC_DIR/command-center" "$SRC_DIR/kolibri" "$INSTALL_DIR/"
fi
echo "NOMAD_DATA=$NOMAD_DATA" > "$INSTALL_DIR/.env"

echo "==> Starting services"
docker compose -f "$INSTALL_DIR/compose.yaml" --env-file "$INSTALL_DIR/.env" up -d --build

echo
echo "Done. Open http://$(hostname).local/ (or this Pi's IP address)."
echo "Add content from the dashboard: Content Manager (libraries) and Map regions (maps)."
echo "ZIM files copied into $NOMAD_DATA/zim by hand are picked up with 'Rescan folder'."
