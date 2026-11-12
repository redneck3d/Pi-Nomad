"""Bookshelf: lists EPUB and PDF files under /data/books and reads EPUBs in the browser.

No reader library is needed. An EPUB is a zip of XHTML chapters, so the server
unpacks chapters on request and the browser renders them. PDFs open in the
browser's own PDF viewer.
"""
import mimetypes
import os
import posixpath
import re
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile

BOOKS_DIR = os.environ.get("BOOKS_DIR", "/data/books")
BOOK_TYPES = (".epub", ".pdf")
IMAGE_TYPES = (".jpg", ".jpeg", ".png", ".webp", ".gif")
XHTML = "application/xhtml+xml"

_meta_cache = {}   # path -> (mtime, size, meta)


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _norm(name):
    """Loose key for matching a book to a cover image with a slightly different name."""
    # File name only, so a cover kept in a "Covers" subfolder still matches its book.
    return re.sub(r"[^a-z0-9]", "", os.path.splitext(posixpath.basename(name))[0].lower())


def resolve(rel):
    """Turn a relative path from a URL into a real path inside BOOKS_DIR, or raise."""
    root = os.path.realpath(BOOKS_DIR)
    path = os.path.realpath(os.path.join(root, rel))
    if not rel or os.path.commonpath([root, path]) != root or path == root:
        raise ValueError("bad path")
    if not os.path.isfile(path):
        raise FileNotFoundError(rel)
    return path


def _walk():
    for base, dirs, files in os.walk(BOOKS_DIR):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for f in sorted(files):
            if not f.startswith("."):
                yield os.path.relpath(os.path.join(base, f), BOOKS_DIR).replace(os.sep, "/")


# ---------- EPUB internals ----------

def _opf(z):
    """Return (opf_path, parsed_root) for an open EPUB zip."""
    try:
        container = ET.fromstring(z.read("META-INF/container.xml"))
    except (KeyError, ET.ParseError):
        raise ValueError("this file is not a valid EPUB")
    for el in container.iter():
        if _local(el.tag) == "rootfile" and el.get("full-path"):
            path = el.get("full-path")
            return path, ET.fromstring(z.read(path))
    raise ValueError("no package file in EPUB")


def _join(opf_path, href):
    href = urllib.parse.unquote(href.split("#")[0])
    return posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), href))


def _manifest(opf_path, root):
    items = {}
    for el in root.iter():
        if _local(el.tag) == "item" and el.get("id") and el.get("href"):
            items[el.get("id")] = {"path": _join(opf_path, el.get("href")),
                                   "type": el.get("media-type", ""),
                                   "props": el.get("properties", "")}
    return items


def _dc(root, name):
    for el in root.iter():
        if _local(el.tag) == name and (el.text or "").strip():
            return el.text.strip()
    return ""


def _cover_path(z, opf_path, root, items):
    for it in items.values():                       # EPUB 3
        if "cover-image" in it["props"].split():
            return it["path"]
    for el in root.iter():                          # EPUB 2: <meta name="cover" content="id">
        if _local(el.tag) == "meta" and el.get("name") == "cover":
            it = items.get(el.get("content", ""))
            if it and it["type"].startswith("image/"):
                return it["path"]
    for it in items.values():                       # last resort: an image called "cover"
        if it["type"].startswith("image/") and "cover" in it["path"].lower():
            return it["path"]
    return None


def _toc_titles(z, opf_path, root, items):
    """Map chapter file path -> title, from the EPUB 3 nav or the EPUB 2 NCX. Best effort."""
    titles = {}
    try:
        nav = next((i for i in items.values() if "nav" in i["props"].split()), None)
        if nav:
            doc = ET.fromstring(z.read(nav["path"]))
            for a in doc.iter():
                if _local(a.tag) == "a" and a.get("href"):
                    text = " ".join("".join(a.itertext()).split())
                    if text:
                        titles.setdefault(_join(nav["path"], a.get("href")), text)
        ncx = next((i for i in items.values() if i["type"] == "application/x-dtbncx+xml"), None)
        if ncx and not titles:
            doc = ET.fromstring(z.read(ncx["path"]))
            for point in doc.iter():
                if _local(point.tag) != "navPoint":
                    continue
                text = src = ""
                for el in point:
                    if _local(el.tag) == "navLabel":
                        text = " ".join("".join(el.itertext()).split())
                    elif _local(el.tag) == "content":
                        src = el.get("src", "")
                if text and src:
                    titles.setdefault(_join(ncx["path"], src), text)
    except (ET.ParseError, KeyError):
        pass
    return titles


def epub_info(rel):
    """Title, author and the reading order (spine) of an EPUB."""
    with zipfile.ZipFile(resolve(rel)) as z:
        opf_path, root = _opf(z)
        items = _manifest(opf_path, root)
        titles = _toc_titles(z, opf_path, root, items)
        names = set(z.namelist())
        spine = []
        for el in root.iter():
            if _local(el.tag) == "itemref":
                it = items.get(el.get("idref", ""))
                if it and it["path"] in names:
                    spine.append({"href": it["path"], "title": titles.get(it["path"], "")})
        if not spine:
            raise ValueError("this EPUB has no readable chapters")
        return {"file": rel, "title": _dc(root, "title") or _title_from_name(rel),
                "author": _dc(root, "creator"), "spine": spine}


def epub_member(rel, member):
    """Bytes and content type of one file inside an EPUB."""
    member = posixpath.normpath(urllib.parse.unquote(member))
    with zipfile.ZipFile(resolve(rel)) as z:
        if member not in z.namelist():       # exact match only, so no path tricks
            raise FileNotFoundError(member)
        data = z.read(member)
    ctype = mimetypes.guess_type(member)[0] or "application/octet-stream"
    if member.lower().endswith((".xhtml", ".html", ".htm", ".xml")):
        try:
            ET.fromstring(data)
            ctype = XHTML                    # well-formed: render as real XHTML
        except ET.ParseError:
            ctype = "text/html"              # sloppy markup: let the browser be forgiving
    return data, ctype


# ---------- shelf ----------

def _title_from_name(rel):
    return os.path.splitext(os.path.basename(rel))[0].replace("_", " ").strip()


def _meta(rel):
    path = os.path.join(BOOKS_DIR, rel)
    st = os.stat(path)
    hit = _meta_cache.get(path)
    if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2]
    meta = {"title": _title_from_name(rel), "author": "", "cover": False}
    if rel.lower().endswith(".epub"):
        try:
            with zipfile.ZipFile(path) as z:
                opf_path, root = _opf(z)
                meta["title"] = _dc(root, "title") or meta["title"]
                meta["author"] = _dc(root, "creator")
                meta["cover"] = bool(_cover_path(z, opf_path, root, _manifest(opf_path, root)))
        except (zipfile.BadZipFile, KeyError, ValueError, ET.ParseError):
            meta["broken"] = True
    _meta_cache[path] = (st.st_mtime, st.st_size, meta)
    return meta


def list_books():
    try:
        files = list(_walk())
    except OSError:
        return []
    images = {_norm(f): f for f in files if f.lower().endswith(IMAGE_TYPES)}
    out = []
    for rel in files:
        if not rel.lower().endswith(BOOK_TYPES):
            continue
        m = _meta(rel)
        out.append({"file": rel, "type": rel.rsplit(".", 1)[-1].lower(), "title": m["title"],
                    "author": m["author"], "size": os.path.getsize(os.path.join(BOOKS_DIR, rel)),
                    "cover": m["cover"] or _norm(rel) in images, "broken": m.get("broken", False)})
    out.sort(key=lambda b: b["title"].lower())
    return out


def cover(rel):
    """(bytes, content type) of a book's cover: from inside the EPUB, else a same-named image."""
    path = resolve(rel)
    if rel.lower().endswith(".epub"):
        try:
            with zipfile.ZipFile(path) as z:
                opf_path, root = _opf(z)
                member = _cover_path(z, opf_path, root, _manifest(opf_path, root))
                if member and member in z.namelist():
                    return z.read(member), mimetypes.guess_type(member)[0] or "image/jpeg"
        except (zipfile.BadZipFile, KeyError, ValueError, ET.ParseError):
            pass
    key = _norm(rel)
    for f in _walk():
        if f.lower().endswith(IMAGE_TYPES) and _norm(f) == key:
            with open(os.path.join(BOOKS_DIR, f), "rb") as fh:
                return fh.read(), mimetypes.guess_type(f)[0] or "image/jpeg"
    raise FileNotFoundError(rel)
