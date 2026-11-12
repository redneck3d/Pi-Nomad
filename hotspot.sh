#!/usr/bin/env bash
# Turn the Pi into its own Wi-Fi access point so phones/laptops can reach Pi-NOMAD with no internet.
# Uses NetworkManager (default on Raspberry Pi OS Bookworm+). The Pi gets 10.42.0.1.
# Usage: sudo ./hotspot.sh [SSID] [PASSWORD]   (password must be 8+ chars)
set -euo pipefail
SSID="${1:-Pi-NOMAD}"
PASS="${2:-changeme-now}"
nmcli con delete pi-nomad-ap >/dev/null 2>&1 || true
nmcli con add type wifi ifname wlan0 con-name pi-nomad-ap autoconnect yes ssid "$SSID" \
  802-11-wireless.mode ap 802-11-wireless.band bg \
  ipv4.method shared \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PASS"
nmcli con up pi-nomad-ap
echo "Hotspot '$SSID' up. Connect and browse to http://10.42.0.1/"
