"""Search everything on the deck from one box: libraries, notes and books.

- Libraries: kiwix-serve already has a full-text search across every ZIM (/search?format=xml,
  checked against kiwix-serve 3.8.2), so we ask it and tidy up the answer.
- Notes: plain markdown files under /data/notes, scanned here. A deck holds hundreds of notes,
  not millions, so no index is needed.
- Books: matched on title and author (the text inside books is not searched).
"""
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import books

KIWIX_URL = os.environ.get("KIWIX_URL", "http://kiwix:8080")
NOTES_DIR = os.environ.get("NOTES_DIR", os.path.join(os.environ.get("NOMAD_DATA", "/data"), "notes"))
MAX_QUERY = 200
MAX_NOTE_BYTES = 1024 ** 2       # read at most this much of one note
MAX_NOTES = 5000
SNIPPET = 220


def _words(q):
    return [w.lower() for w in q.split()]


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _clip(text, around=0):
    """A short, single-line piece of text centred near position `around`."""
    text = " ".join(text.split())
    if len(text) <= SNIPPET:
        return text
    start = max(0, min(around - SNIPPET // 3, len(text) - SNIPPET))
    cut = text[start:start + SNIPPET]
    return ("…" if start else "") + cut.strip() + ("…" if start + SNIPPET < len(text) else "")


# ---------- libraries (kiwix-serve) ----------

def _kiwix(params):
    url = KIWIX_URL + "/search?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "pi-nomad"}), timeout=20) as r:
        return r.read()


def parse_kiwix(data):
    """Turn kiwix-serve's search feed (RSS with OpenSearch fields) into plain dicts."""
    total, results = 0, []
    for el in ET.fromstring(data).iter():
        name = _local(el.tag)
        if name == "totalResults":
            try:
                total = int((el.text or "0").replace(",", ""))
            except ValueError:
                total = 0
        elif name == "item":
            item = {"title": "", "path": "", "snippet": "", "library": ""}
            for c in el:
                tag = _local(c.tag)
                if tag == "title":
                    item["title"] = (c.text or "").strip()
                elif tag == "link":
                    item["path"] = (c.text or "").strip()
                elif tag == "description":
                    item["snippet"] = _clip("".join(c.itertext()).strip(". "))   # drops the <b> marks
                elif tag == "book":
                    item["library"] = " ".join("".join(c.itertext()).split())
            # Only ever hand the page a path on the Library app, never a link to somewhere else.
            if item["path"].startswith("/") and not item["path"].startswith("//"):
                results.append(item)
    return {"total": max(total, len(results)), "results": results}


def libraries(q, count=20):
    params = {"pattern": q, "format": "xml", "pageLength": count}
    try:
        try:
            return parse_kiwix(_kiwix(params))
        except urllib.error.HTTPError as e:
            if e.code != 400:
                raise
            # kiwix refuses one search across libraries in different languages; keep to English then.
            return parse_kiwix(_kiwix({**params, "books.filter.lang": "eng"}))
    except urllib.error.HTTPError as e:
        # With nothing installed (or nothing searchable) kiwix answers with an error page.
        return {"total": 0, "results": [], "error": "" if e.code in (400, 404) else f"The Library answered with error {e.code}"}
    except (urllib.error.URLError, OSError, ET.ParseError):
        return {"total": 0, "results": [], "error": "The Library app is not answering"}


# ---------- notes ----------

def notes(q, count=20):
    words, out, seen = _words(q), [], 0
    for folder, dirs, files in os.walk(NOTES_DIR):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "attachments")
        for f in sorted(files):
            if not f.lower().endswith(".md") or f.startswith("."):
                continue
            seen += 1
            if seen > MAX_NOTES:
                return out
            try:
                with open(os.path.join(folder, f), "rb") as fh:
                    text = fh.read(MAX_NOTE_BYTES).decode("utf-8", "replace")
            except OSError:
                continue
            title = f[:-3]
            low_title, low_text = title.lower(), text.lower()
            if not all(w in low_title or w in low_text for w in words):
                continue
            at = min([i for i in (low_text.find(w) for w in words) if i >= 0] or [0])
            out.append({"title": title, "snippet": _clip(re.sub(r"[#*_`>\[\]]", "", text), at),
                        "in_title": all(w in low_title for w in words)})
    out.sort(key=lambda n: (not n["in_title"], n["title"].lower()))     # title matches first
    return out[:count]


# ---------- books ----------

def shelf(q, count=20):
    words = _words(q)
    hits = [b for b in books.list_books()
            if all(w in (b["title"] + " " + b["author"] + " " + b["file"]).lower() for w in words)]
    return [{"title": b["title"], "author": b["author"], "file": b["file"], "type": b["type"]} for b in hits[:count]]


# ---------- everything ----------

def everything(q):
    q = " ".join((q or "").split())
    if not q:
        raise ValueError("Type something to search for")
    if len(q) > MAX_QUERY:
        raise ValueError("That search is too long")
    return {"q": q, "notes": notes(q), "books": shelf(q), "libraries": libraries(q)}
