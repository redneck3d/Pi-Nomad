"""Offline maps: regional extracts from the Protomaps planet build, served as .pmtiles.

`pmtiles extract` reads only the byte ranges it needs from the remote planet file,
so a Michigan extract is a small fraction of the full planet download.
"""
import datetime
import os
import re
import shutil
import subprocess
import urllib.request

import jobs
import places

MAPS_DIR = os.environ.get("MAPS_DIR", "/data/maps")
PMTILES_BIN = os.environ.get("PMTILES_BIN", "pmtiles")
BUILD_URL = os.environ.get("PROTOMAPS_BUILD_URL", "https://build.protomaps.com/{date}.pmtiles")
MIN_FREE = 2 * 1024 ** 3

# bbox is west,south,east,north
REGIONS = [
    {"id": "detroit", "name": "Detroit metro", "bbox": [-83.75, 42.00, -82.75, 42.65]},
    {"id": "michigan", "name": "Michigan", "bbox": [-90.45, 41.69, -82.10, 48.32]},
    {"id": "ohio", "name": "Ohio", "bbox": [-84.83, 38.40, -80.51, 41.99]},
    {"id": "indiana", "name": "Indiana", "bbox": [-88.10, 37.77, -84.78, 41.77]},
    {"id": "illinois", "name": "Illinois", "bbox": [-91.52, 36.97, -87.01, 42.51]},
    {"id": "wisconsin", "name": "Wisconsin", "bbox": [-92.89, 42.49, -86.25, 47.31]},
]
DETAIL = {"overview": 10, "standard": 13, "detailed": 15}   # max zoom levels


def _head_ok(url):
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "pi-nomad"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except Exception:
        return False


def planet_url(days_back=10):
    """Newest daily build that exists (probed newest-first, so no index format is assumed)."""
    today = datetime.date.today()
    for i in range(days_back):
        url = BUILD_URL.format(date=(today - datetime.timedelta(days=i)).strftime("%Y%m%d"))
        if _head_ok(url):
            return url
    raise RuntimeError("Could not find a recent Protomaps build (is the Pi online?)")


def parse_target(region_id, bbox, detail):
    """Validate a request and return (file_stem, bbox, maxzoom)."""
    if detail not in DETAIL:
        raise ValueError("unknown detail level")
    if region_id == "custom":
        try:
            w, s, e, n = (float(x) for x in bbox)
        except (TypeError, ValueError):
            raise ValueError("Enter west, south, east and north as numbers") from None
        stem = f"custom-{w:.2f}_{s:.2f}_{e:.2f}_{n:.2f}"
    else:
        r = next((r for r in REGIONS if r["id"] == region_id), None)
        if not r:
            raise ValueError("unknown region")
        (w, s, e, n), stem = r["bbox"], r["id"]
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise ValueError("bounding box is out of range")
    return f"{stem}-{detail}", (w, s, e, n), DETAIL[detail]


def _cmd(src, out, bbox, maxzoom, dry=False):
    cmd = [PMTILES_BIN, "extract", src, out, "--bbox=" + ",".join(str(x) for x in bbox),
           f"--maxzoom={maxzoom}"]
    return cmd + ["--dry-run"] if dry else cmd


def estimate(region_id, bbox, detail):
    stem, box, z = parse_target(region_id, bbox, detail)
    res = subprocess.run(_cmd(planet_url(), os.devnull, box, z, dry=True),
                         capture_output=True, text=True, timeout=180)
    text = (res.stdout + res.stderr).strip()
    return {"output": "\n".join(text.splitlines()[-6:]), "ok": res.returncode == 0}


def _extract(job, stem, bbox, maxzoom):
    final = os.path.join(MAPS_DIR, stem + ".pmtiles")
    part = final + ".part"
    if os.path.exists(final):
        raise ValueError(f"{stem}.pmtiles already exists")
    if shutil.disk_usage(MAPS_DIR).free < MIN_FREE:
        raise OSError("Not enough free space")
    job.message = "Finding latest map build"
    src = planet_url()
    job.message = "Extracting"
    job.proc = subprocess.Popen(_cmd(src, part, bbox, maxzoom), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
    tail = []
    for line in job.proc.stdout:               # progress bars use \r; keep the newest chunk
        chunk = line.replace("\r", "\n").strip().splitlines()
        if chunk:
            tail = (tail + chunk)[-5:]
            m = re.search(r"(\d+)%", chunk[-1])
            if m:
                job.done, job.total = int(m.group(1)), 100
            job.message = chunk[-1][:120]
    code = job.proc.wait()
    if (job.cancel.is_set() or code != 0) and os.path.exists(part):
        os.remove(part)
    if job.cancel.is_set():
        return
    if code != 0:
        raise RuntimeError("pmtiles failed: " + " | ".join(tail[-2:]))
    os.replace(part, final)
    index_places(job, final)
    job.message = ""


def index_places(job, path):
    """Read the place names out of a map so it can be searched. A failure here never loses the map."""
    job.message = "Reading place names"
    job.done = job.total = 0
    try:
        places.build_index(path, job)
    except InterruptedError:
        pass
    except Exception as e:                      # the map itself is fine; search just stays off for it
        job.message = f"Could not read place names: {e}"
        return
    job.message = ""


def index_missing():
    """Queue an index job for every map that has none yet (maps saved before search existed, or copied in)."""
    started = []
    for m in list_maps():
        path = os.path.join(MAPS_DIR, m["name"])
        if not places.is_current(path):
            started.append(jobs.start("map", "Place names for " + m["name"][:-len(".pmtiles")],
                                      lambda j, p=path: index_places(j, p)))
    return started


def start_extract(region_id, bbox, detail):
    stem, box, z = parse_target(region_id, bbox, detail)
    return jobs.start("map", stem, lambda j: _extract(j, stem, box, z))


def list_maps():
    out = []
    try:
        names = sorted(f for f in os.listdir(MAPS_DIR) if f.endswith(".pmtiles"))
    except OSError:
        return out
    for f in names:
        try:
            out.append({"name": f, "size": os.path.getsize(os.path.join(MAPS_DIR, f))})
        except OSError:              # deleted while we were listing
            pass
    return out


def delete(filename):
    if os.path.basename(filename) != filename or not filename.endswith(".pmtiles"):
        raise ValueError("bad file name")
    path = os.path.join(MAPS_DIR, filename)
    os.remove(path)
    places.remove_index(path)
