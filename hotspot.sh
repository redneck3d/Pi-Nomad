#!/usr/bin/env bash
# Turn the Pi into its own Wi-Fi network so phones and laptops can reach Pi-NOMAD with no internet.
# Uses NetworkManager (default on Raspberry Pi OS Bookworm and newer). The Pi becomes 10.42.0.1.
#
#   sudo ./hotspot.sh [NAME]     turn the hotspot on (asks for the Wi-Fi password; NAME defaults to Pi-NOMAD)
#   sudo ./hotspot.sh off        turn it off and go back to the Wi-Fi the Pi used before
#   ./hotspot.sh status          show whether it is on
#
# The hotspot takes over the Pi's Wi-Fi. If you are connected to the Pi over Wi-Fi when you
# turn it on, you will be cut off: use Ethernet, or a screen and keyboard.
set -euo pipefail
CON=pi-nomad-ap
DEV=wlan0

status() {
  if nmcli -t -f NAME con show --active | grep -qx "$CON"; then
    echo "Hotspot is ON: network '$(nmcli -g 802-11-wireless.ssid con show "$CON")', dashboard at http://10.42.0.1/"
  elif nmcli -t -f NAME con show | grep -qx "$CON"; then
    echo "Hotspot is set up but not running."
  else
    echo "Hotspot is OFF."
  fi
}

case "${1:-}" in
  status) status; exit 0 ;;
  -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
esac

if [[ $EUID -ne 0 ]]; then echo "Run with sudo." >&2; exit 1; fi

if [[ "${1:-}" == "off" ]]; then
  nmcli con down "$CON" >/dev/null 2>&1 || true
  nmcli con delete "$CON" >/dev/null 2>&1 || true
  nmcli dev connect "$DEV" >/dev/null 2>&1 || true     # rejoin the normal Wi-Fi if one is saved
  echo "Hotspot is off."
  exit 0
fi

SSID="${1:-Pi-NOMAD}"
PASS="${2:-}"          # a second argument still works for scripts; otherwise we ask, so it never sits in a file
if [[ -z "$PASS" ]]; then
  read -rsp "Choose a password for the '$SSID' Wi-Fi (8 to 63 characters): " PASS; echo
  read -rsp "Type it again: " AGAIN; echo
  if [[ "$PASS" != "$AGAIN" ]]; then echo "The two passwords do not match. Nothing was changed." >&2; exit 1; fi
fi
if (( ${#PASS} < 8 || ${#PASS} > 63 )); then
  echo "The password must be 8 to 63 characters. Nothing was changed." >&2; exit 1
fi
if (( ${#SSID} < 1 || ${#SSID} > 32 )); then
  echo "The network name must be 1 to 32 characters. Nothing was changed." >&2; exit 1
fi

nmcli con delete "$CON" >/dev/null 2>&1 || true
# WPA2 with AES only: phones warn about, or refuse, the older modes NetworkManager would also offer.
# The priority makes the hotspot win over a saved home Wi-Fi at boot, so the deck always comes up as a hotspot.
nmcli con add type wifi ifname "$DEV" con-name "$CON" ssid "$SSID" \
  connection.autoconnect yes connection.autoconnect-priority 10 \
  802-11-wireless.mode ap 802-11-wireless.band bg \
  ipv4.method shared ipv6.method disabled \
  wifi-sec.key-mgmt wpa-psk wifi-sec.proto rsn wifi-sec.pairwise ccmp wifi-sec.group ccmp \
  wifi-sec.psk "$PASS" >/dev/null
if ! nmcli con up "$CON" >/dev/null; then
  echo "The hotspot could not start. Removing it and going back to the normal Wi-Fi." >&2
  nmcli con delete "$CON" >/dev/null 2>&1 || true
  nmcli dev connect "$DEV" >/dev/null 2>&1 || true
  exit 1
fi
echo "Hotspot '$SSID' is on. Join it and open http://10.42.0.1/"
echo "It will come back by itself after a restart. Turn it off with: sudo ./hotspot.sh off"
