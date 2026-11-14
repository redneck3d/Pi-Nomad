"""Pi-NOMAD Command Center: stdlib-only web app (no pip installs).

Serves the dashboard, the ZIM and map managers, offline map files (with HTTP Range
support, which PMTiles needs), and a small JSON API.
"""
import http.cookies
import json
import os
import shutil
import time
import urllib.parse
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import auth
import backup
import books
import jobs
import maps
import places
import power
import search
import services
import system
import zim

DATA = os.environ.get("NOMAD_DATA", "/data")
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
FOLDERS = ["zim", "maps", "notes", "books", "kolibri"]
MAX_BODY = 64 * 1024     # our JSON requests are tiny; refuse anything that is not

_cache = {"t": 0.0, "sizes": {}}


def service_states():
    """Map compose service name -> container state, or {} if Docker is unreachable."""
    return services.states()


def folder_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def storage():
    try:
        du = shutil.disk_usage(DATA)
    except OSError:
        return None
    if time.time() - _cache["t"] > 30:  # walking big trees is slow; cache it
        _cache["sizes"] = {n: folder_size(os.path.join(DATA, n)) for n in FOLDERS}
        _cache["t"] = time.time()
    return {"total": du.total, "used": du.used, "free": du.free, "folders": _cache["sizes"]}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=STATIC, **kw)

    # ----- helpers -----
    def _json(self, obj, code=200, headers=()):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    # ----- admin PIN -----
    def _token(self):
        try:
            c = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
            return c["nomad_admin"].value if "nomad_admin" in c else ""
        except http.cookies.CookieError:
            return ""

    def _session_cookie(self, token, max_age):
        return [("Set-Cookie", f"nomad_admin={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Strict")]

    def _auth_post(self, p, b):
        """Handle /api/auth/* POSTs."""
        if p == "/api/auth/unlock":
            try:
                ok = auth.verify(b.get("pin"))
            except auth.TooManyAttempts as e:
                return self._json({"error": str(e)}, 429)
            if not ok:
                return self._json({"error": "Wrong PIN" if auth.pin_set() else "No PIN is set"}, 403)
            return self._json({"ok": True}, headers=self._session_cookie(auth.new_session(), auth.SESSION_HOURS * 3600))
        if p == "/api/auth/lock":
            auth.end_session(self._token())
            return self._json({"ok": True}, headers=self._session_cookie("", 0))
        if not auth.allowed(self._token()):          # set/clear need an unlocked session once a PIN exists
            return self._json({"error": "locked", "locked": True}, 401)
        if p == "/api/auth/set":
            try:
                auth.set_pin(b.get("pin"))
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            return self._json({"ok": True}, headers=self._session_cookie(auth.new_session(), auth.SESSION_HOURS * 3600))
        if p == "/api/auth/clear":
            auth.clear_pin()
            return self._json({"ok": True}, headers=self._session_cookie("", 0))
        return self._json({"error": "not found"}, 404)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not 0 <= n <= MAX_BODY:
            raise ValueError("request too large")
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def _from_our_pages(self):
        """False for a POST that some other website could make a browser send to the deck.

        Our pages always post JSON. A web page on another site cannot send that content type
        across sites without asking first (a CORS preflight, which we never grant), and when a
        browser does say where a request came from, it has to be this deck.
        """
        if self.headers.get_content_type() != "application/json":
            return False
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        return urllib.parse.urlparse(origin).netloc == self.headers.get("Host")

    def list_directory(self, path):
        """No folder listings: only real files are served."""
        self.send_error(404)
        return None

    def log_request(self, code="-", size="-"):
        # Open dashboards poll every few seconds. Logging each successful read would
        # write to the SD card all day, so only changes and failures are logged.
        if self.command in ("GET", "HEAD") and str(code)[:1] in ("2", "3"):
            return
        super().log_request(code, size)

    def _guard(self, fn):
        """Run a handler; turn expected failures into JSON errors."""
        try:
            self._json(fn())
        except (ValueError, KeyError, TypeError) as e:
            self._json({"error": str(e)}, 400)
        except FileNotFoundError:
            self._json({"error": "not found"}, 404)
        except zipfile.BadZipFile:
            self._json({"error": "this file is damaged or not a real EPUB"}, 400)
        except Exception as e:
            self._json({"error": f"{type(e).__name__}: {e}"}, 502)

    def _serve_map(self, head_only=False):
        """Serve /maps-data/<file>.pmtiles with Range support."""
        name = urllib.parse.unquote(self.path.split("?")[0][len("/maps-data/"):])
        path = os.path.join(maps.MAPS_DIR, name)
        if os.path.basename(name) != name or not name.endswith(".pmtiles") or not os.path.isfile(path):
            return self._json({"error": "not found"}, 404)
        self._serve_file(path, "application/octet-stream", head_only)

    def _serve_book(self, head_only=False):
        """Serve /books-data/<relative path> (PDF or EPUB) with Range support."""
        rel = urllib.parse.unquote(self.path.split("?")[0][len("/books-data/"):])
        try:
            if not rel.lower().endswith(books.BOOK_TYPES):
                raise ValueError(rel)
            path = books.resolve(rel)
        except (ValueError, FileNotFoundError):
            return self._json({"error": "not found"}, 404)
        ctype = "application/pdf" if rel.lower().endswith(".pdf") else "application/epub+zip"
        self._serve_file(path, ctype, head_only)

    def _bytes(self, data, ctype, extra=()):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _read_book(self):
        """Serve /books-read/<book>.epub/<file inside the EPUB>."""
        raw = urllib.parse.unquote(self.path.split("?")[0][len("/books-read/"):])
        cut = raw.lower().find(".epub/")
        try:
            if cut < 0:
                raise ValueError(raw)
            data, ctype = books.epub_member(raw[:cut + 5], raw[cut + 6:])
        except (ValueError, FileNotFoundError, KeyError, OSError, zipfile.BadZipFile):
            return self._json({"error": "not found"}, 404)
        # Book files are untrusted: never run their scripts or let them call out.
        self._bytes(data, ctype, [("Content-Security-Policy",
                                   "default-src 'self' data:; script-src 'none'; style-src 'self' 'unsafe-inline'; object-src 'none'"),
                                  ("X-Content-Type-Options", "nosniff")])

    def _backup_zip(self):
        """Stream the notes as a zip. No length is known up front, so the connection closing ends it."""
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", f'attachment; filename="pi-nomad-notes-{time.strftime("%Y-%m-%d")}.zip"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            backup.write_zip(self.wfile)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _cover(self, rel):
        try:
            data, ctype = books.cover(rel)
        except (ValueError, FileNotFoundError, OSError):
            return self._json({"error": "not found"}, 404)
        self._bytes(data, ctype, [("Cache-Control", "max-age=3600")])

    def _serve_file(self, path, ctype, head_only=False):
        size = os.path.getsize(path)
        start, end, code = 0, size - 1, 200
        rng = self.headers.get("Range", "")
        if rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            try:
                if a == "":                       # suffix range: last N bytes
                    start = max(0, size - int(b))
                else:
                    start = int(a)
                    end = min(int(b), size - 1) if b else size - 1
            except ValueError:
                start, end = 0, size - 1
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            code = 206
        length = end - start + 1
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head_only:
            return
        with open(path, "rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)

    # ----- routing -----
    def do_HEAD(self):
        if self.path.startswith("/maps-data/"):
            return self._serve_map(head_only=True)
        if self.path.startswith("/books-data/"):
            return self._serve_book(head_only=True)
        super().do_HEAD()

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        p = url.path
        if p.startswith("/maps-data/"):
            return self._serve_map()
        if p.startswith("/books-data/"):
            return self._serve_book()
        if p.startswith("/books-read/"):
            return self._read_book()
        if p == "/api/books":
            return self._json(books.list_books())
        if p == "/api/books/info":
            return self._guard(lambda: books.epub_info(q.get("file", "")))
        if p == "/api/books/cover":
            return self._cover(q.get("file", ""))
        if p == "/api/backup":
            return self._json({"drives": backup.list_drives(), "sizes": backup.sizes()})
        if p == "/api/backup/download":
            return self._backup_zip()
        if p == "/api/power":
            return self._json(power.status())
        if p == "/api/search":
            return self._guard(lambda: search.everything(q.get("q", "")))
        if p == "/api/status":
            return self._json({"services": service_states(), "storage": storage(), "zims": zim.list_zims()})
        if p == "/api/auth":
            return self._json({"pin_set": auth.pin_set(), "unlocked": auth.valid(self._token())})
        if p == "/api/system":
            return self._guard(system.snapshot)
        if p == "/api/jobs":
            return self._json(jobs.snapshot())
        if p == "/api/zim/search":
            return self._guard(lambda: zim.search(q.get("q", ""), q.get("lang", "eng")))
        if p == "/api/zim/presets":
            return self._json([{k: v for k, v in x.items() if k != "items"} for x in zim.PRESETS])
        if p == "/api/zim/preset":
            return self._guard(lambda: zim.resolve_preset(q.get("id", "")))
        if p == "/api/maps/regions":
            return self._json({"regions": maps.REGIONS, "detail": list(maps.DETAIL)})
        if p == "/api/maps/search":
            def find():
                try:
                    here = (float(q["lon"]), float(q["lat"]))
                except (KeyError, ValueError):
                    here = (None, None)
                return places.search(q.get("file", ""), q.get("q", ""), *here)
            return self._guard(find)
        if p == "/api/maps/list":
            return self._json(maps.list_maps())
        super().do_GET()

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        if not self._from_our_pages():
            return self._json({"error": "This request did not come from the Pi-Nomad pages"}, 403)
        try:
            b = self._body()
        except ValueError:                      # includes bad JSON
            return self._json({"error": "bad request"}, 400)
        if not isinstance(b, dict):
            return self._json({"error": "bad JSON"}, 400)
        if p.startswith("/api/auth/"):
            return self._auth_post(p, b)
        # Every other POST changes something on the deck, so it needs the admin PIN (if one is set).
        if not auth.allowed(self._token()):
            return self._json({"error": "locked", "locked": True}, 401)
        if p == "/api/zim/download":
            return self._guard(lambda: zim.start_download(b["url"], b.get("meta", {})).public())
        if p == "/api/zim/delete":
            return self._guard(lambda: zim.delete(b["file"]) or {"ok": True})
        if p == "/api/zim/rescan":
            return self._guard(lambda: {"added": zim.rescan()})
        if p == "/api/power":
            return self._guard(lambda: power.request(b.get("action")))
        if p == "/api/services":
            return self._guard(lambda: services.act(b.get("service"), b.get("action")))
        if p == "/api/backup/usb":
            return self._guard(lambda: backup.start_usb(b["drive"], b.get("books", True)).public())
        if p == "/api/jobs/cancel":
            return self._guard(lambda: {"ok": jobs.cancel(b["id"])})
        if p == "/api/maps/extract":
            return self._guard(lambda: maps.start_extract(b["region"], b.get("bbox"), b["detail"]).public())
        if p == "/api/maps/estimate":
            return self._guard(lambda: maps.estimate(b["region"], b.get("bbox"), b["detail"]))
        if p == "/api/maps/delete":
            return self._guard(lambda: maps.delete(b["file"]) or {"ok": True})
        self._json({"error": "not found"}, 404)


if __name__ == "__main__":
    try:
        zim.rescan()   # pick up ZIMs that were copied in while we were stopped
    except OSError:
        pass
    try:
        maps.index_missing()   # maps saved before place search existed get their names read now, in the background
    except OSError:
        pass
    port = int(os.environ.get("PORT", "80"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
