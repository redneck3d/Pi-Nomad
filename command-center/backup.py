"""Backup: copy the things that cannot be downloaded again (notes, books) off the SD card.

Two ways out:
- to a USB drive plugged into the Pi. The Pi's desktop mounts it under /media, and that
  folder is shared into this container (see compose.yaml), so new drives show up here.
- as a zip of the notes, downloaded by whatever phone or PC is looking at the page.

Libraries and maps are not copied: they are large and can be downloaded again. Every
backup carries a text list of them instead.
"""
import os
import re
import shutil
import time
import zipfile

import jobs
import maps
import zim

DATA = os.environ.get("NOMAD_DATA", "/data")
MEDIA_DIR = os.environ.get("MEDIA_DIR", "/media")
MOUNTS_FILE = os.environ.get("MOUNTS_FILE", "/proc/mounts")
FOLDER = "pi-nomad-backup"
SOURCES = ("notes", "books")
HEADROOM = 16 * 1024 ** 2          # leave a little room on the drive
# Characters a FAT or exFAT drive refuses in file names. Notes are named after their titles,
# so "What now?.md" must not make the whole backup fail.
_FAT_BAD = re.compile(r'[<>:"|?*\\\x00-\x1f]')


def _unescape(field):
    """/proc/mounts writes a space as \\040 (and tab, newline, backslash the same way)."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), field)


def list_drives():
    """Drives mounted under MEDIA_DIR, newest mount last."""
    root = os.path.realpath(MEDIA_DIR)
    out = []
    try:
        with open(MOUNTS_FILE) as f:
            lines = f.read().splitlines()
    except OSError:
        return out
    for line in lines:
        parts = line.split()
        if len(parts) < 4:
            continue
        point = _unescape(parts[1])
        if point == root or os.path.commonpath([root, point]) != root:
            continue
        try:
            du = shutil.disk_usage(point)
        except OSError:
            continue                      # unplugged without being ejected
        try:
            backups = sorted(d for d in os.listdir(os.path.join(point, FOLDER))
                             if os.path.isdir(os.path.join(point, FOLDER, d)))
        except OSError:
            backups = []
        out.append({"id": os.path.relpath(point, root), "name": os.path.basename(point), "format": parts[2],
                    "total": du.total, "free": du.free, "read_only": "ro" in parts[3].split(","),
                    "backups": backups})
    return out


def _drive_path(drive_id):
    for d in list_drives():
        if d["id"] == drive_id:
            if d["read_only"]:
                raise ValueError("That drive is read-only, so nothing can be saved to it")
            return os.path.join(os.path.realpath(MEDIA_DIR), d["id"])
    raise ValueError("That drive is not plugged in any more")


def _files(names):
    """(source path, [folder, ..., file]) for every file to back up. Hidden files and links are skipped."""
    for top in names:
        base = os.path.join(DATA, top)
        for folder, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for f in sorted(files):
                src = os.path.join(folder, f)
                if f.startswith(".") or os.path.islink(src) or not os.path.isfile(src):
                    continue
                yield src, [top] + os.path.relpath(src, base).split(os.sep)


def sizes():
    out = {}
    for top in SOURCES:
        files = list(_files([top]))
        out[top] = {"files": len(files), "bytes": sum(_size(src) for src, _ in files)}
    return out


def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _human(n):
    return f"{n / 1024 ** 3:.2f} GB" if n >= 1024 ** 3 else f"{max(1, round(n / 1024 ** 2))} MB"


def manifest():
    """Plain-text list of what is installed, so it can be downloaded again after a card failure."""
    lines = ["Pi-Nomad backup, made " + time.strftime("%Y-%m-%d %H:%M"), "",
             "Libraries and maps are not in this backup because they can be downloaded again.",
             "This is what was installed:", "", "Libraries (Content Manager):"]
    lines += [f"  {z['name']}  ({_human(z['size'])})" for z in zim.list_zims()] or ["  none"]
    lines += ["", "Maps (Map regions):"]
    lines += [f"  {m['name']}  ({_human(m['size'])})" for m in maps.list_maps()] or ["  none"]
    lines += ["", "To restore: open Files on the deck and copy the notes and books folders back in."]
    return "\r\n".join(lines) + "\r\n"       # Windows line ends: Notepad on any PC shows it properly


def _safe(name):
    return _FAT_BAD.sub("_", name).rstrip(". ") or "_"


def _copy(job, dest, names):
    files = list(_files(names))
    job.total = sum(_size(src) for src, _ in files)
    if shutil.disk_usage(os.path.dirname(dest)).free < job.total + HEADROOM:
        raise OSError("Not enough room on that drive")
    os.makedirs(dest)
    try:
        for src, rel in files:
            target = os.path.join(dest, *[_safe(p) for p in rel])
            os.makedirs(os.path.dirname(target), exist_ok=True)
            job.message = "/".join(rel)[:120]
            try:
                fin = open(src, "rb")
            except OSError:
                continue                       # deleted since we listed it
            with fin, open(target, "wb") as fout:
                while True:
                    if job.cancel.is_set():
                        raise InterruptedError
                    chunk = fin.read(1 << 20)
                    if not chunk:
                        break
                    fout.write(chunk)
                    job.done += len(chunk)
        with open(os.path.join(dest, "installed-content.txt"), "w", newline="") as f:
            f.write(manifest())
        job.message = "Finishing"
        os.sync()                              # everything is on the drive before we say "done"
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)    # never leave half a backup that looks whole
        if job.cancel.is_set():
            return
        raise
    job.message = ""


def start_usb(drive_id, books=True):
    root = os.path.join(_drive_path(drive_id), FOLDER)
    stamp = time.strftime("%Y-%m-%d_%H%M")
    dest, n = os.path.join(root, stamp), 1
    while os.path.exists(dest):                # two backups in the same minute
        n += 1
        dest = os.path.join(root, f"{stamp}_{n}")
    os.makedirs(root, exist_ok=True)           # fails here, clearly, if the drive cannot be written
    names = ["notes", "books"] if books else ["notes"]
    return jobs.start("backup", "Backup to " + os.path.basename(drive_id), lambda j: _copy(j, dest, names))


def write_zip(out):
    """Write the notes (and the installed-content list) as a zip to a stream that cannot seek."""
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for src, rel in _files(["notes"]):
            try:
                z.write(src, "/".join(rel))
            except OSError:
                pass
        z.writestr("installed-content.txt", manifest())
