#!/usr/bin/env bash
# Move the whole deck (Pi OS, Docker, apps and content) from the SD card to an NVMe SSD.
#
#   ./tools/move-to-ssd.sh --check     show what would happen; changes nothing, no sudo needed
#   sudo ./tools/move-to-ssd.sh        ERASE the SSD and copy everything onto it
#
# The SD card is only read, never changed, so it stays a working fallback: if the Pi will not
# start from the SSD, put the card back in and it boots exactly as before.
#
# What it does:
#   1. Stops the apps for the length of the copy, so nothing changes half way through.
#   2. Erases the SSD and gives it the same two partitions a Pi OS card has (boot + system).
#   3. Copies every file across with rsync.
#   4. Points the copy at itself: the Pi finds its system by a disk ID, and the SSD has a new one.
#   5. Starts the apps again (still running from the SD card until you remove it).
# Afterwards: shut down, take the SD card out, power on. A Pi 5 starts from NVMe when no card is in.
set -euo pipefail

TARGET="${TARGET:-/dev/nvme0n1}"
MNT=/mnt/pi-nomad-ssd
CHECK=0
[[ "${1:-}" == "--check" ]] && CHECK=1

say() { printf '\n==> %s\n' "$*"; }
die() { echo "STOPPED: $*" >&2; exit 1; }

# ---------- look before touching anything ----------
[[ -b "$TARGET" ]] || die "$TARGET was not found. Is the SSD fitted?"
[[ "$(lsblk -dn -o TRAN "$TARGET")" == "nvme" ]] || die "$TARGET is not an NVMe drive."
ROOT_PART="$(findmnt -n -o SOURCE /)"
BOOT_PART="$(findmnt -n -o SOURCE /boot/firmware)"
ROOT_DISK="/dev/$(lsblk -n -o PKNAME "$ROOT_PART" | head -1)"
[[ "$ROOT_DISK" != "$TARGET" ]] || die "The Pi is already running from $TARGET. Nothing to do."
if findmnt -n -o SOURCE | grep -q "^${TARGET}"; then die "Part of $TARGET is in use (mounted). Unmount it first."; fi

OLD_ID="$(sed -n 's/.*root=PARTUUID=\([0-9a-fA-F]*\)-02.*/\1/p' /boot/firmware/cmdline.txt)"
[[ -n "$OLD_ID" ]] || die "Could not read the SD card's disk ID from /boot/firmware/cmdline.txt."
grep -q "PARTUUID=${OLD_ID}-02" /etc/fstab || die "/etc/fstab does not use the disk ID $OLD_ID; this layout is not one I know."

USED=$(( $(df -B1 --output=used / | tail -1) + $(df -B1 --output=used /boot/firmware | tail -1) ))
SIZE=$(lsblk -b -dn -o SIZE "$TARGET")
(( SIZE > USED + 4 * 1024 ** 3 )) || die "The SSD is too small: $((USED / 1024 ** 3)) GB to copy, $((SIZE / 1024 ** 3)) GB on the SSD."

say "Plan"
echo "  Copy from : $ROOT_DISK  (system $ROOT_PART, boot $BOOT_PART), $((USED / 1024 ** 3)) GB in use"
echo "  Copy to   : $TARGET  ($(lsblk -dn -o MODEL "$TARGET" | xargs), $((SIZE / 1024 ** 3)) GB)"
echo "  On the SSD now, ALL OF WHICH WILL BE ERASED:"
lsblk -n -o NAME,SIZE,FSTYPE,LABEL "$TARGET" | sed 's/^/      /'
if (( CHECK )); then
  say "Check only: nothing was changed. Run with sudo and without --check to do it."
  exit 0
fi

[[ $EUID -eq 0 ]] || die "Run with sudo."
for tool in rsync sfdisk wipefs mkfs.vfat mkfs.ext4 blkid partprobe; do
  command -v "$tool" >/dev/null || die "The tool '$tool' is missing."
done
echo
read -rp "Type ERASE to wipe $TARGET and copy the deck onto it: " answer
[[ "${answer^^}" == "ERASE" ]] || die "Not confirmed. Nothing was changed."     # capitals or not, either is fine

DOCKER_WAS_UP=0
cleanup() {
  code=$?
  mountpoint -q "$MNT/boot/firmware" && umount "$MNT/boot/firmware" || true
  mountpoint -q "$MNT" && umount "$MNT" || true
  rmdir "$MNT" 2>/dev/null || true
  if (( DOCKER_WAS_UP )); then
    say "Starting the apps again"
    systemctl start docker.socket docker || true
  fi
  if (( code != 0 )); then echo; echo "The move did NOT finish. The SD card is unchanged and the deck still runs from it." >&2; fi
}
trap cleanup EXIT

# ---------- 1. freeze ----------
say "Stopping the apps for the copy"
if systemctl is-active --quiet docker; then DOCKER_WAS_UP=1; systemctl stop docker.socket docker; fi
sync

# ---------- 2. erase and lay out the SSD like a Pi OS card ----------
say "Erasing $TARGET"
wipefs -a -q "${TARGET}"p* 2>/dev/null || true
wipefs -a -q "$TARGET"
sfdisk -q "$TARGET" <<'LAYOUT'
label: dos
,512M,c
,,83
LAYOUT
partprobe "$TARGET"; sleep 2
mkfs.vfat -F 32 -n bootfs "${TARGET}p1" >/dev/null
mkfs.ext4 -q -F -L rootfs "${TARGET}p2"

# ---------- 3. copy ----------
mkdir -p "$MNT"
mount "${TARGET}p2" "$MNT"
mkdir -p "$MNT/boot/firmware"
mount "${TARGET}p1" "$MNT/boot/firmware"
say "Copying the system (this is the long part)"
# -x stays on the SD card's own filesystem, so /proc, /sys, /dev, /run and the SSD itself are skipped.
rsync -aAXHx --numeric-ids --info=progress2 --exclude="$MNT" / "$MNT/"
say "Copying the boot files"
rsync -rtx --info=progress2 /boot/firmware/ "$MNT/boot/firmware/"

# ---------- 4. point the copy at itself ----------
NEW_ID="$(blkid -s PARTUUID -o value "${TARGET}p2" | sed 's/-02$//')"
[[ -n "$NEW_ID" && "$NEW_ID" != "$OLD_ID" ]] || die "Could not read a new disk ID from the SSD."
sed -i "s/PARTUUID=${OLD_ID}-/PARTUUID=${NEW_ID}-/g" "$MNT/boot/firmware/cmdline.txt" "$MNT/etc/fstab"
grep -q "root=PARTUUID=${NEW_ID}-02" "$MNT/boot/firmware/cmdline.txt" || die "The SSD's cmdline.txt was not updated."
grep -q "PARTUUID=${NEW_ID}-02" "$MNT/etc/fstab" || die "The SSD's fstab was not updated."
sync

say "Done. The SSD holds a complete copy (disk ID $NEW_ID); the SD card is unchanged."
echo "Next: shut the deck down, take the SD card out, and power it back on."
