"""ZIM content manager: search the Kiwix catalog, download with resume, register in library.xml.

Registration is done in pure Python (no kiwix-manage needed) so the paths written
into library.xml are exactly the ones the kiwix container sees: /data/zim/<file>.
"""
import os
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

import jobs

ZIM_DIR = os.environ.get("ZIM_DIR", "/data/zim")
LIBRARY = os.path.join(ZIM_DIR, "library.xml")
CATALOG = os.environ.get("KIWIX_CATALOG", "https://opds.library.kiwix.org/catalog/v2/entries")
DOWNLOAD_DOMAIN = "download.kiwix.org"   # real links use lb.download.kiwix.org (a load balancer)
MIN_FREE = 2 * 1024 ** 3     # always leave 2 GiB free
_lib_lock = threading.Lock()

# Presets look up the newest version at click time, so no dated URLs live here.
# Entries are (catalog name, flavour or None). Kiwix publishes one *name* in several flavours
# (e.g. wikipedia_en_all as nopic / mini / maxi), so the flavour picks the variant.
# Names verified against the live catalog on 2026-11-08; sizes are approximate.
PRESETS = [
    {"id": "starter", "title": "Starter kit",
     "desc": "About 1.2 GB: a 100-article Wikipedia sampler plus medical, water, food and disaster guides.",
     "items": [("wikipedia_en_100", None), ("zimgit-medicine_en", None), ("zimgit-water_en", None),
               ("zimgit-food-preparation_en", None), ("zimgit-post-disaster_en", None)]},
    {"id": "wikipedia_compact", "title": "Wikipedia, compact",
     "desc": "About 14 GB: the opening section of every English article, no images.",
     "items": [("wikipedia_en_all", "mini")]},
    {"id": "wikipedia_full", "title": "Wikipedia, full text",
     "desc": "About 53 GB: every English article in full, no images.",
     "items": [("wikipedia_en_all", "nopic")]},
    {"id": "repair", "title": "Repair & DIY",
     "desc": "About 3.6 GB: iFixit repair guides.",
     "items": [("ifixit_en_all", None)]},
    {"id": "medical", "title": "Medical reference",
     "desc": "About 3.4 GB: Wikipedia medicine, MDWiki, NHS medicines and a field medical library.",
     "items": [("wikipedia_en_medicine", "nopic"), ("mdwiki_en_all", "maxi"),
               ("nhs.uk_en_medicines", None), ("zimgit-medicine_en", None)]},
    {"id": "preparedness", "title": "Preparedness",
     "desc": "About 6 GB: Ready.gov and a self-reliance library.",
     "items": [("ready.gov_en_all", None), ("lrnselfreliance_en_all", None)]},
    {"id": "reference", "title": "Reference shelf",
     "desc": "About 13 GB: Wikibooks and Wiktionary, no images.",
     "items": [("wikibooks_en_all", "nopic"), ("wiktionary_en_all", "nopic")]},
]


# ---------- catalog ----------

def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _child_text(el, name):
    for c in el:
        if _local(c.tag) == name:
            return (c.text or "").strip()
    return ""


def parse_opds(data):
    """Parse a Kiwix OPDS (Atom) feed into plain dicts. Tolerant of missing fields."""
    out = []
    for entry in ET.fromstring(data):
        if _local(entry.tag) != "entry":
            continue
        url, size = "", 0
        for c in entry:
            if _local(c.tag) == "link" and c.get("type") == "application/x-zim":
                url = c.get("href", "")
                if url.endswith(".meta4"):
                    url = url[:-len(".meta4")]
                size = int(c.get("length") or 0)
        if not url:
            continue
        flavour = _child_text(entry, "flavour")
        title = _child_text(entry, "title")
        nested = {}   # <author><name>..</name></author>, <publisher><name>..</name></publisher>
        for c in entry:
            if _local(c.tag) in ("author", "publisher"):
                nested[_local(c.tag)] = _child_text(c, "name")
        out.append({
            "title": f"{title} ({flavour})" if flavour else title,   # variants share one title
            "name": _child_text(entry, "name"),
            "flavour": flavour,
            "tags": _child_text(entry, "tags"),
            "category": _child_text(entry, "category"),
            "creator": nested.get("author", ""),
            "publisher": nested.get("publisher", ""),
            "description": _child_text(entry, "summary"),
            "language": _child_text(entry, "language"),
            "date": _child_text(entry, "updated")[:10],
            "articleCount": _child_text(entry, "articleCount"),
            "mediaCount": _child_text(entry, "mediaCount"),
            "size": size,
            "url": url,
        })
    return out


def _catalog_get(**params):
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    req = urllib.request.Request(f"{CATALOG}?{qs}", headers={"User-Agent": "pi-nomad"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return parse_opds(r.read())


def search(q="", lang="eng", count=20):
    return _catalog_get(q=q, lang=lang, count=count)


def resolve_preset(preset_id):
    p = next((p for p in PRESETS if p["id"] == preset_id), None)
    if not p:
        raise KeyError(preset_id)
    found, missing = [], []
    for name, flavour in p["items"]:
        try:
            hits = _catalog_get(name=name, count=10)
        except Exception:
            hits = []
        hits = [h for h in hits if h["name"] == name and (flavour is None or h["flavour"] == flavour)]
        if hits:
            found.append(hits[0])
        else:
            missing.append(f"{name} ({flavour})" if flavour else name)
    return {"preset": p["title"], "entries": found, "missing": missing}


# ---------- library.xml ----------

def _read_library():
    try:
        root = ET.parse(LIBRARY).getroot()
    except (FileNotFoundError, ET.ParseError):
        root = ET.Element("library", version="20110515")
    return root


def _write_library(root):
    tmp = LIBRARY + ".tmp"
    ET.ElementTree(root).write(tmp, encoding="UTF-8", xml_declaration=True)
    os.replace(tmp, LIBRARY)   # atomic, so kiwix-serve never reads a half-written file


def zim_uuid(path):
    """A ZIM header is: magic(4) version(4) uuid(16) ..."""
    with open(path, "rb") as f:
        head = f.read(24)
    if len(head) < 24 or head[:4] != b"ZIM\x04":
        raise ValueError(f"{os.path.basename(path)} is not a valid ZIM file")
    return str(uuid.UUID(bytes=head[8:24]))


def register(path, meta=None):
    meta = meta or {}
    attrs = {
        "id": zim_uuid(path),
        "path": path,
        "title": meta.get("title") or os.path.basename(path)[:-4],
        "description": meta.get("description", ""),
        "language": meta.get("language", ""),
        "name": meta.get("name", ""),
        "flavour": meta.get("flavour", ""),
        "tags": meta.get("tags", ""),
        "category": meta.get("category", ""),
        "creator": meta.get("creator", ""),
        "publisher": meta.get("publisher", ""),
        "date": meta.get("date", ""),
        # Attribute names verified against libkiwix 14.2.1 Book::updateFromXml; size is KiB.
        "size": str(os.path.getsize(path) // 1024),
        "articleCount": str(meta.get("articleCount", "")),
        "mediaCount": str(meta.get("mediaCount", "")),
    }
    with _lib_lock:
        root = _read_library()
        for b in list(root):
            if b.get("path") == path or b.get("id") == attrs["id"]:
                root.remove(b)
        ET.SubElement(root, "book", {k: v for k, v in attrs.items() if v})
        _write_library(root)


def unregister(path):
    with _lib_lock:
        root = _read_library()
        for b in list(root):
            if b.get("path") == path:
                root.remove(b)
        _write_library(root)


def rescan():
    """Add ZIMs copied in by hand and drop library entries whose file is gone."""
    added = 0
    with _lib_lock:
        root = _read_library()
        for b in list(root):
            if not os.path.exists(b.get("path", "")):
                root.remove(b)
        _write_library(root)
        known = {b.get("path") for b in root}
    for f in os.listdir(ZIM_DIR):
        p = os.path.join(ZIM_DIR, f)
        if f.endswith(".zim") and p not in known:
            try:
                register(p)
                added += 1
            except ValueError:
                pass
    return added


def list_zims():
    try:
        files = sorted(f for f in os.listdir(ZIM_DIR) if f.endswith(".zim"))
    except OSError:
        return []
    return [{"name": f, "size": os.path.getsize(os.path.join(ZIM_DIR, f))} for f in files]


def delete(filename):
    if os.path.basename(filename) != filename or not filename.endswith(".zim"):
        raise ValueError("bad file name")
    path = os.path.join(ZIM_DIR, filename)
    unregister(path)
    os.remove(path)


# ---------- downloading ----------

def _safe_filename(url):
    u = urllib.parse.urlparse(url)
    host = u.hostname or ""
    if u.scheme != "https" or not (host == DOWNLOAD_DOMAIN or host.endswith("." + DOWNLOAD_DOMAIN)):
        raise ValueError("Only https://download.kiwix.org links are allowed")
    name = os.path.basename(u.path)
    if not name.endswith(".zim") or name != urllib.parse.unquote(name) or name.startswith("."):
        raise ValueError("URL does not point at a .zim file")
    return name


def _download(job, url, meta, retries=6):
    name = _safe_filename(url)
    dest = os.path.join(ZIM_DIR, name)
    part = dest + ".part"
    if os.path.exists(dest):
        raise ValueError(f"{name} is already installed")
    expect = int(meta.get("size") or 0)
    if expect and shutil.disk_usage(ZIM_DIR).free < expect + MIN_FREE:
        raise OSError("Not enough free space for this download")
    attempt = 0
    while True:
        have = os.path.getsize(part) if os.path.exists(part) else 0
        req = urllib.request.Request(url, headers={"User-Agent": "pi-nomad"})
        if have:
            req.add_header("Range", f"bytes={have}-")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.status == 206:
                    job.total = have + int(r.headers.get("Content-Length") or 0)
                else:                      # server ignored Range: start over
                    have = 0
                    job.total = int(r.headers.get("Content-Length") or expect)
                job.done = have
                with open(part, "ab" if have else "wb") as f:
                    while True:
                        if job.cancel.is_set():
                            return
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        job.done += len(chunk)
            if job.total and job.done < job.total:
                raise OSError("connection closed early")
            break
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            attempt += 1
            if attempt > retries or job.cancel.is_set():
                raise
            job.message = f"Connection lost, retrying ({attempt}/{retries})"
            time.sleep(min(30, 2 ** attempt))   # off-grid links drop; resume from the .part file
    job.message = "Registering"
    os.replace(part, dest)
    register(dest, meta)
    job.message = ""


def start_download(url, meta):
    name = _safe_filename(url)            # validate before queueing
    return jobs.start("zim", meta.get("title") or name, lambda j: _download(j, url, meta))
