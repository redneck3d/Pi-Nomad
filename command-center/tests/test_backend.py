import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import uuid
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TMP = tempfile.mkdtemp()
os.environ.update(NOMAD_DATA=TMP, ZIM_DIR=os.path.join(TMP, "zim"), MAPS_DIR=os.path.join(TMP, "maps"),
                  BOOKS_DIR=os.path.join(TMP, "books"), CONFIG_DIR=os.path.join(TMP, "config"))
os.makedirs(os.environ["ZIM_DIR"]); os.makedirs(os.environ["MAPS_DIR"]); os.makedirs(os.environ["BOOKS_DIR"])

import zipfile  # noqa: E402

import app, auth, backup, books, jobs, maps, places, power, search, system, zim  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
CH = '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{0}</title></head><body><h1>{0}</h1><p>Text of {0}.</p>{1}</body></html>'


def make_epub3(path):
    """EPUB 3: files in an OEBPS folder, a nav document, a cover-image, one sloppy chapter."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf", '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
                   '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Water &amp; Fire</dc:title><dc:creator>A. Tester</dc:creator></metadata>'
                   '<manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
                   '<item id="c1" href="text/ch%201.xhtml" media-type="application/xhtml+xml"/>'
                   '<item id="c2" href="text/ch2.xhtml" media-type="application/xhtml+xml"/>'
                   '<item id="gone" href="text/missing.xhtml" media-type="application/xhtml+xml"/>'
                   '<item id="img" href="img/front.png" media-type="image/png" properties="cover-image"/></manifest>'
                   '<spine><itemref idref="c1"/><itemref idref="gone"/><itemref idref="c2"/></spine></package>')
        z.writestr("OEBPS/nav.xhtml", '<html xmlns="http://www.w3.org/1999/xhtml"><body><nav><ol>'
                   '<li><a href="text/ch%201.xhtml">Finding  <b>Water</b></a></li><li><a href="text/ch2.xhtml#top">Making Fire</a></li></ol></nav></body></html>')
        z.writestr("OEBPS/text/ch 1.xhtml", CH.format("Finding Water", '<script>document.title="HACKED"</script><a href="ch2.xhtml">next</a>'))
        z.writestr("OEBPS/text/ch2.xhtml", "<html><body><h1>Making Fire<p>unclosed &nbsp; markup<br></body></html>")
        z.writestr("OEBPS/img/front.png", PNG)


def make_epub2(path):
    """EPUB 2: package at the zip root, NCX table of contents, <meta name="cover">."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/container.xml", '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="book.opf"/></rootfiles></container>')
        z.writestr("book.opf", '<package xmlns="http://www.idpf.org/2007/opf" version="2.0">'
                   '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><meta name="cover" content="cv"/></metadata>'
                   '<manifest><item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
                   '<item id="a" href="a.html" media-type="application/xhtml+xml"/><item id="cv" href="c.png" media-type="image/png"/></manifest>'
                   '<spine toc="ncx"><itemref idref="a"/></spine></package>')
        z.writestr("toc.ncx", '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap><navPoint id="n1">'
                   '<navLabel><text>Knots</text></navLabel><content src="a.html"/></navPoint></navMap></ncx>')
        z.writestr("a.html", CH.format("Knots", ""))
        z.writestr("c.png", PNG)

# The first entry is copied verbatim from the live Kiwix catalog (opds.library.kiwix.org, 2026-11-08).
# The second is the same shape with the "nopic" flavour values seen for wikipedia_en_all.
FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:dc="http://purl.org/dc/terms/"
      xmlns:opds="https://specs.opds.io/opds-1.2"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <id>653c56e4-7a33-8b27-d5c0-9daa5dea1894</id>
  <title>Filtered Entries</title>
  <entry>
    <id>urn:uuid:80d8dddf-1ecc-e528-0f08-3193044c6413</id>
    <title>Medical Library</title>
    <updated>2024-08-29T00:00:00Z</updated>
    <summary>A collection of books pertaining to field and emergency medicine.</summary>
    <language>eng</language>
    <name>zimgit-medicine_en</name>
    <flavour></flavour>
    <category></category>
    <tags>preppers;medical;_ftindex:no;_pictures:yes;_videos:yes;_details:yes</tags>
    <articleCount>1</articleCount>
    <mediaCount>369</mediaCount>
    <link rel="http://opds-spec.org/image/thumbnail"
          href="/catalog/v2/illustration/80d8dddf-1ecc-e528-0f08-3193044c6413/?size=48"
          type="image/png;width=48;height=48;scale=1"/>
    <link type="text/html" href="https://browse.library.kiwix.org/content/zimgit-medicine_en_2024-08" />
    <author>
      <name>Various</name>
    </author>
    <publisher>
      <name>openZIM</name>
    </publisher>
    <dc:issued>2024-08-29T00:00:00Z</dc:issued>
    <link rel="http://opds-spec.org/acquisition/open-access" type="application/x-zim" href="https://lb.download.kiwix.org/zim/other/zimgit-medicine_en_2024-08.zim.meta4" length="70179840" />
  </entry>
  <entry>
    <id>urn:uuid:11111111-1111-1111-1111-111111111111</id>
    <title>Wikipedia</title>
    <updated>2026-06-17T00:00:00Z</updated>
    <summary>All articles</summary>
    <language>eng</language>
    <name>wikipedia_en_all</name>
    <flavour>nopic</flavour>
    <category>wikipedia</category>
    <articleCount>19191219</articleCount>
    <mediaCount>1</mediaCount>
    <link rel="http://opds-spec.org/acquisition/open-access" type="application/x-zim" href="https://lb.download.kiwix.org/zim/wikipedia/wikipedia_en_all_nopic_2026-06.zim.meta4" length="52691000000" />
  </entry>
  <entry><title>No link entry</title><name>x</name></entry>
</feed>"""


JSON = {"Content-Type": "application/json"}      # what our pages send with every POST


def fake_zim(size=3_000_000):
    return b"ZIM\x04" + b"\x05\x00\x00\x00" + uuid.UUID(int=42).bytes + os.urandom(size)


def wait(job, secs=15):
    t = time.time()
    while job.state in ("queued", "running") and time.time() - t < secs:
        time.sleep(0.05)


class ZimTests(unittest.TestCase):
    def test_parse_opds(self):
        r = zim.parse_opds(FEED)
        self.assertEqual(len(r), 2)  # entry without a ZIM link is skipped
        med, wiki = r
        self.assertEqual(med["name"], "zimgit-medicine_en")
        self.assertEqual(med["title"], "Medical Library")          # no flavour, title unchanged
        self.assertEqual(med["description"], "A collection of books pertaining to field and emergency medicine.")
        self.assertEqual(med["url"], "https://lb.download.kiwix.org/zim/other/zimgit-medicine_en_2024-08.zim")
        self.assertEqual(med["size"], 70179840)
        self.assertEqual(med["date"], "2024-08-29")
        self.assertEqual(wiki["title"], "Wikipedia (nopic)")        # flavour disambiguates variants
        self.assertEqual(wiki["flavour"], "nopic")
        self.assertEqual((med["creator"], med["publisher"]), ("Various", "openZIM"))  # nested <name> elements
        self.assertIn("preppers", med["tags"])

    def test_register_writes_attributes_libkiwix_reads(self):
        # Attribute set taken from libkiwix 14.2.1 Book::updateFromXml
        known = {"id", "path", "title", "description", "language", "creator", "publisher", "date", "url",
                 "name", "flavour", "tags", "origId", "articleCount", "mediaCount", "size",
                 "favicon", "faviconMimeType", "faviconUrl", "downloadId", "category"}
        p = os.path.join(zim.ZIM_DIR, "meta_2026-01.zim")
        open(p, "wb").write(fake_zim(2048))
        zim.register(p, zim.parse_opds(FEED)[0])
        book = ET.parse(zim.LIBRARY).getroot()
        self.assertEqual(book.tag, "library")
        self.assertEqual(book.get("version"), "20110515")
        attrs = book[0].attrib
        self.assertTrue(set(attrs) <= known, set(attrs) - known)
        self.assertEqual(attrs["creator"], "Various")
        self.assertEqual(attrs["size"], str(os.path.getsize(p) // 1024))
        zim.delete("meta_2026-01.zim")

    def test_filename_validation(self):
        # real catalog links point at lb.download.kiwix.org
        ok = "https://lb.download.kiwix.org/zim/other/zimgit-medicine_en_2024-08.zim"
        self.assertEqual(zim._safe_filename(ok), "zimgit-medicine_en_2024-08.zim")
        self.assertEqual(zim._safe_filename("https://download.kiwix.org/zim/x/a_2026-01.zim"), "a_2026-01.zim")
        for bad in ["http://download.kiwix.org/a.zim", "https://evil.example/a.zim",
                    "https://evildownload.kiwix.org/a.zim", "https://download.kiwix.org.evil.example/a.zim",
                    "https://download.kiwix.org/a.txt", "https://download.kiwix.org/%2e%2e%2fa.zim"]:
            with self.assertRaises(ValueError, msg=bad):
                zim._safe_filename(bad)

    def test_preset_resolution_picks_flavour_and_reports_missing(self):
        entries = zim.parse_opds(FEED)
        orig = zim._catalog_get
        zim._catalog_get = lambda **kw: [e for e in entries if e["name"] == kw["name"]]
        try:
            zim.PRESETS.append({"id": "t", "title": "T", "desc": "",
                                "items": [("wikipedia_en_all", "nopic"), ("wikipedia_en_all", "mini"),
                                          ("zimgit-medicine_en", None), ("nope", None)]})
            r = zim.resolve_preset("t")
        finally:
            zim._catalog_get = orig
            zim.PRESETS.pop()
        self.assertEqual([e["name"] for e in r["entries"]], ["wikipedia_en_all", "zimgit-medicine_en"])
        self.assertEqual(r["missing"], ["wikipedia_en_all (mini)", "nope"])

    def test_every_library_write_advances_whole_second_mtime(self):
        root = ET.Element("library", version="20110515")
        seen = []
        for _ in range(4):                     # all inside one second, like a multi-file rescan
            zim._write_library(root)
            seen.append(int(os.path.getmtime(zim.LIBRARY)))
        self.assertEqual(seen, sorted(set(seen)), seen)

    def test_search_never_offers_full_gutenberg(self):
        rows = [{"name": "gutenberg_en_all"}, {"name": "gutenberg_en_lcc-k"}]
        orig = zim._catalog_get
        zim._catalog_get = lambda **kw: rows
        try:
            self.assertEqual([e["name"] for e in zim.search("gutenberg")], ["gutenberg_en_lcc-k"])
        finally:
            zim._catalog_get = orig

    def test_catalog_entries_say_when_they_are_already_installed(self):
        have = os.path.join(zim.ZIM_DIR, "have_2026-01.zim")
        with open(have, "wb") as fh:
            fh.write(fake_zim(100))
        try:
            got = zim._mark_installed([{"url": "https://download.kiwix.org/zim/x/have_2026-01.zim"},
                                       {"url": "https://download.kiwix.org/zim/x/missing_2026-01.zim"},
                                       {"url": ""}])
        finally:
            os.remove(have)
        self.assertEqual([e["installed"] for e in got], [True, False, False])

    def test_listing_survives_a_file_vanishing(self):
        orig = os.path.getsize
        os.path.getsize = lambda p: (_ for _ in ()).throw(FileNotFoundError(p))
        try:
            ghost = os.path.join(zim.ZIM_DIR, "ghost_2026-01.zim")
            open(ghost, "wb").close()
            self.assertNotIn("ghost_2026-01.zim", [z["name"] for z in zim.list_zims()])
        finally:
            os.path.getsize = orig
            os.remove(ghost)

    def test_every_preset_is_well_formed(self):
        for p in zim.PRESETS:
            self.assertTrue(p["items"], p["id"])
            for name, flavour in p["items"]:
                self.assertTrue(name and (flavour is None or flavour in ("nopic", "mini", "maxi")), (p["id"], name))

    def test_register_rescan_delete(self):
        p = os.path.join(zim.ZIM_DIR, "hand_copied.zim")
        open(p, "wb").write(fake_zim(1000))
        self.assertEqual(zim.rescan(), 1)
        book = ET.parse(zim.LIBRARY).getroot()[0]
        self.assertEqual(book.get("path"), p)
        self.assertEqual(book.get("id"), str(uuid.UUID(int=42)))
        self.assertEqual(zim.rescan(), 0)             # idempotent
        zim.delete("hand_copied.zim")
        self.assertEqual(len(ET.parse(zim.LIBRARY).getroot()), 0)
        self.assertFalse(os.path.exists(p))
        with self.assertRaises(ValueError):
            zim.delete("../etc/passwd")

    def test_invalid_zim_rejected(self):
        p = os.path.join(zim.ZIM_DIR, "junk.zim")
        open(p, "wb").write(b"not a zim file at all, just text")
        with self.assertRaises(ValueError):
            zim.register(p)
        os.remove(p)


class FlakyServer(http.server.BaseHTTPRequestHandler):
    """Serves a ZIM, but kills the first response halfway; supports Range for the retry."""
    data = fake_zim()
    hits = 0

    def log_message(self, *a): pass

    def do_GET(self):
        if self.path.endswith(".sha256"):
            return self.send_error(404)
        FlakyServer.hits += 1
        start = 0
        rng = self.headers.get("Range")
        if rng:
            start = int(rng.split("=")[1].split("-")[0])
        body = self.data[start:]
        self.send_response(206 if rng else 200)
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{len(self.data)-1}/{len(self.data)}")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if FlakyServer.hits == 1:
            self.wfile.write(body[: len(body) // 2])   # then drop the connection
            self.wfile.flush()
            self.connection.close()
        else:
            self.wfile.write(body)


class EndlessServer(http.server.BaseHTTPRequestHandler):
    """Keeps streaming until the client hangs up, so a download is reliably mid-flight."""
    def log_message(self, *a): pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(1 << 40))
        self.end_headers()
        try:
            while True:
                self.wfile.write(b"x" * (1 << 20))
                time.sleep(0.01)
        except OSError:
            pass


class ChecksumServer(http.server.BaseHTTPRequestHandler):
    """Serves a ZIM plus the .sha256 file Kiwix publishes beside it (right or wrong on demand)."""
    data = fake_zim(200_000)
    published = ""

    def log_message(self, *a): pass

    def do_GET(self):
        body = (self.published + "  x.zim\n").encode() if self.path.endswith(".sha256") else self.data
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class DownloadTests(unittest.TestCase):
    def _fetch(self, name, published):
        ChecksumServer.published = published
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ChecksumServer)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        orig_safe = zim._safe_filename
        zim._safe_filename = lambda u: name
        try:
            job = zim.start_download(f"http://127.0.0.1:{srv.server_port}/zim/{name}", {"title": name})
            wait(job)
        finally:
            zim._safe_filename = orig_safe
            srv.shutdown()
        return job

    def test_download_with_matching_checksum_is_installed(self):
        import hashlib
        job = self._fetch("good_2026-01.zim", hashlib.sha256(ChecksumServer.data).hexdigest().upper())
        self.assertEqual(job.state, "done", job.message)
        self.assertIn("good_2026-01.zim", [z["name"] for z in zim.list_zims()])
        zim.delete("good_2026-01.zim")

    def test_damaged_download_is_thrown_away(self):
        job = self._fetch("bad_2026-01.zim", "0" * 64)
        self.assertEqual(job.state, "error")
        self.assertIn("checksum", job.message)
        left = [n for n in os.listdir(zim.ZIM_DIR) if n.startswith("bad_2026-01")]
        self.assertEqual(left, [])                       # neither the file nor its .part stays behind
        self.assertNotIn("bad_2026-01", open(zim.LIBRARY).read() if os.path.exists(zim.LIBRARY) else "")

    def test_unusable_checksum_file_does_not_block_a_download(self):
        job = self._fetch("nosum_2026-01.zim", "<html>not found</html>")
        self.assertEqual(job.state, "done", job.message)
        zim.delete("nosum_2026-01.zim")

    def test_cancel_removes_partial_file(self):
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), EndlessServer)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        orig_safe = zim._safe_filename
        zim._safe_filename = lambda u: "cancelme_2026-01.zim"
        part = os.path.join(zim.ZIM_DIR, "cancelme_2026-01.zim.part")
        try:
            job = zim.start_download(f"http://127.0.0.1:{srv.server_port}/x.zim", {"title": "Cancel me"})
            t = time.time()
            while job.done < (1 << 20) and time.time() - t < 10:
                time.sleep(0.02)
            self.assertTrue(os.path.exists(part))
            jobs.cancel(job.id)
            wait(job)
        finally:
            zim._safe_filename = orig_safe
            srv.shutdown()
        self.assertEqual(job.state, "cancelled", job.message)
        self.assertFalse(os.path.exists(part))

    def test_resume_after_dropped_connection(self):
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FlakyServer)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_port}/zim/flaky_2026-01.zim"
        orig_safe, orig_sleep = zim._safe_filename, time.sleep
        zim._safe_filename = lambda u: "flaky_2026-01.zim"
        zim.time.sleep = lambda s: None   # don't actually back off in the test
        try:
            job = zim.start_download(url, {"title": "Flaky", "size": len(FlakyServer.data)})
            wait(job)
        finally:
            zim._safe_filename = orig_safe
            zim.time.sleep = orig_sleep
            srv.shutdown()
        self.assertEqual(job.state, "done", job.message)
        self.assertEqual(open(os.path.join(zim.ZIM_DIR, "flaky_2026-01.zim"), "rb").read(), FlakyServer.data)
        self.assertEqual(FlakyServer.hits, 2)   # one failed + one resumed
        self.assertFalse(os.path.exists(os.path.join(zim.ZIM_DIR, "flaky_2026-01.zim.part")))
        self.assertEqual(ET.parse(zim.LIBRARY).getroot()[0].get("title"), "Flaky")
        zim.delete("flaky_2026-01.zim")

    def test_cancel_queued_job(self):
        started = threading.Event()
        blocker = jobs.start("zim", "blocker", lambda j: started.wait(5))
        time.sleep(0.1)
        waiting = jobs.start("zim", "waiting", lambda j: self.fail("should not run"))
        self.assertEqual(waiting.state, "queued")
        jobs.cancel(waiting.id)
        started.set()
        wait(blocker); wait(waiting)
        self.assertEqual(waiting.state, "cancelled")


class MapsTests(unittest.TestCase):
    def test_parse_target(self):
        stem, bbox, z = maps.parse_target("michigan", None, "standard")
        self.assertEqual((stem, z), ("michigan-standard", 13))
        stem, bbox, z = maps.parse_target("custom", ["-83", "42", "-82", "43"], "overview")
        self.assertEqual(z, 10)
        for args in [("nowhere", None, "standard"), ("michigan", None, "huge"),
                     ("custom", ["10", "0", "5", "1"], "standard"), ("custom", ["a", "b", "c", "d"], "standard"),
                     ("custom", None, "standard"), ("custom", ["1", "2"], "standard")]:
            with self.assertRaises(ValueError, msg=str(args)):
                maps.parse_target(*args)

    def test_extract_with_fake_pmtiles_binary(self):
        fake = os.path.join(TMP, "fakepmtiles.sh")
        open(fake, "w").write('#!/bin/sh\nprintf "10%%\\r50%%\\r100%%\\n" >&2\nprintf TILES > "$3"\n')
        os.chmod(fake, 0o755)
        maps.PMTILES_BIN = fake
        maps.planet_url = lambda: "https://example.invalid/planet.pmtiles"
        job = maps.start_extract("detroit", None, "overview")
        wait(job)
        self.assertEqual(job.state, "done", job.message)
        self.assertEqual([m["name"] for m in maps.list_maps()], ["detroit-overview.pmtiles"])
        maps.delete("detroit-overview.pmtiles")

    def test_failed_extract_reports_error(self):
        fake = os.path.join(TMP, "failpmtiles.sh")
        with open(fake, "w") as f:
            f.write('#!/bin/sh\nprintf PARTIAL > "$3"\necho "no route to host"\nexit 3\n')
        os.chmod(fake, 0o755)
        maps.PMTILES_BIN = fake
        maps.planet_url = lambda: "https://example.invalid/planet.pmtiles"
        job = maps.start_extract("ohio", None, "overview")
        wait(job)
        self.assertEqual(job.state, "error")
        self.assertIn("no route to host", job.message)
        self.assertIn("pmtiles failed", job.message)   # the error, not the last progress line
        self.assertFalse(os.path.exists(os.path.join(maps.MAPS_DIR, "ohio-overview.pmtiles.part")))

    def test_build_lookup_failure_shows_real_error(self):
        def boom():
            raise RuntimeError("Could not find a recent Protomaps build")
        maps.planet_url = boom
        job = maps.start_extract("indiana", None, "overview")
        wait(job)
        self.assertEqual((job.state, job.message), ("error", "Could not find a recent Protomaps build"))


# ---- a hand-made PMTiles v3 file with vector tiles, in the same layout Protomaps uses ----

def _vi(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _pb(num, payload):
    """A protobuf field: bytes are length-delimited, an int is a varint."""
    if isinstance(payload, int):
        return _vi(num << 3) + _vi(payload)
    return _vi(num << 3 | 2) + _vi(len(payload)) + payload


def _zz(n):
    return (n << 1) ^ (n >> 63)


def mvt_layer(name, features, extent=4096):
    """features: list of (props dict, [(x, y), ...]). One point = a point; more = a line."""
    keys, values, body = [], [], b""
    for props, pts in features:
        tags = b""
        for k, v in props.items():
            if k not in keys:
                keys.append(k)
            if v not in values:
                values.append(v)
            tags += _vi(keys.index(k)) + _vi(values.index(v))
        geom, (x, y) = _vi(1 << 3 | 1) + _vi(_zz(pts[0][0])) + _vi(_zz(pts[0][1])), pts[0]
        if len(pts) > 1:
            geom += _vi((len(pts) - 1) << 3 | 2)
            for nx, ny in pts[1:]:
                geom += _vi(_zz(nx - x)) + _vi(_zz(ny - y))
                x, y = nx, ny
        body += _pb(2, _pb(2, tags) + _pb(3, 1 if len(pts) == 1 else 2) + _pb(4, geom))
    out = _pb(15, 2) + _pb(1, name.encode()) + body
    out += b"".join(_pb(3, k.encode()) for k in keys)
    out += b"".join(_pb(4, _pb(1, v.encode()) if isinstance(v, str) else _pb(4, v)) for v in values)
    return _pb(3, out + _pb(5, extent))


def make_pmtiles(path, zoom, tiles, leaf=False):
    """tiles: {(x, y): raw tile bytes}. With leaf=True the root directory points at a leaf directory."""
    import gzip, struct
    base = places._zoom_base(zoom)
    ids = {places.tile_xy(zoom, i): i for i in range(base, base + 4 ** zoom)}
    entries, data = [], b""
    for xy in sorted(tiles, key=lambda t: ids[t]):
        blob = gzip.compress(tiles[xy])
        entries.append((ids[xy], 1, len(data), len(blob)))
        data += blob

    def directory(rows):
        out, last = _vi(len(rows)), 0
        for tid, _, _, _ in rows:
            out += _vi(tid - last)
            last = tid
        out += b"".join(_vi(r[1]) for r in rows) + b"".join(_vi(r[3]) for r in rows)
        out += b"".join(_vi(r[2] + 1) for r in rows)
        return gzip.compress(out)

    leaves = directory(entries) if leaf else b""
    root = directory([(entries[0][0], 0, 0, len(leaves))]) if leaf else directory(entries)
    root_off, leaf_off = 127, 127 + len(root)
    data_off = leaf_off + len(leaves)
    head = b"PMTiles" + bytes([3]) + struct.pack("<11Q", root_off, len(root), 0, 0, leaf_off, len(leaves), data_off, len(data),
                                                  len(entries), len(entries), len(entries))
    head += bytes([1, 2, 2, 1, 0, zoom]) + struct.pack("<4i", -900000000, 400000000, -800000000, 500000000)
    head += bytes([zoom]) + struct.pack("<2i", -850000000, 450000000)
    assert len(head) == 127
    with open(path, "wb") as fh:
        fh.write(head + root + leaves + data)


class PlacesTests(unittest.TestCase):
    """Place names are read out of the map file itself, then searched."""

    @classmethod
    def setUpClass(cls):
        town = {"kind": "locality", "kind_detail": "town", "population_rank": 12}
        # Tile (2,2) holds Wayne; tile (5,2) holds Plymouth. Both have a Main Street. At zoom 3 one tile unit is
        # about a kilometre, so streets sit within a few units of their town to count as "near" it.
        west = (mvt_layer("places", [({"name": "Wayne", **town}, [(1000, 1000)]),
                                     ({"name": "Elm", "kind": "locality", "kind_detail": "hamlet"}, [(3000, 3000)]),
                                     ({"name": "Off The Edge", **town}, [(5000, 100)])])       # in the margin: skipped
                + mvt_layer("roads", [({"name": "Main Street", "kind": "minor_road"}, [(1000, 1000), (1002, 1004), (1004, 1008)]),
                                      ({"ref": "I 94", "kind": "highway"}, [(0, 2000), (4096, 2000)]),
                                      ({"name": "Michigan Avenue", "ref": "US 12", "kind": "major_road"}, [(996, 1000), (1003, 1000)]),
                                      ({"name": "Pere Marquette Railroad", "kind": "rail"}, [(0, 0), (10, 10)])])
                + mvt_layer("pois", [({"name": "Wayne Public Library", "kind": "library"}, [(1001, 1001)]),
                                     ({"name": "Wayne County", "kind": "administrative"}, [(1500, 1500)]),
                                     ({"kind": "park"}, [(5, 5)])])                           # no name: skipped
                + mvt_layer("buildings", [({"name": "Not Searched", "kind": "building"}, [(1, 1)])]))
        east = (mvt_layer("places", [({"name": "Plymouth", **town}, [(2000, 2000)]),
                                     ({"name": "Mount Clemens", **town}, [(3500, 500)])])
                + mvt_layer("roads", [({"name": "Main Street", "kind": "minor_road"}, [(2000, 1998), (2000, 2002)]),
                                      ({"ref": "I 94", "kind": "highway"}, [(0, 2000), (4096, 2000)])]))
        cls.file = "testland-detailed.pmtiles"
        cls.path = os.path.join(maps.MAPS_DIR, cls.file)
        make_pmtiles(cls.path, 3, {(2, 2): west, (5, 2): east})
        cls.count = places.build_index(cls.path)
        cls.wayne = places.to_lonlat(3, 2, 2, 1000, 1000, 4096)
        cls.plymouth = places.to_lonlat(3, 5, 2, 2000, 2000, 4096)

    @classmethod
    def tearDownClass(cls):
        for p in (cls.path, places.db_path(cls.path)):
            if os.path.exists(p):
                os.remove(p)

    def find(self, q, near=None):
        return places.search(self.file, q, *(near or (None, None)))["results"]

    def names(self, q, near=None):
        return [(r["name"], r["kind"], r["near"]) for r in self.find(q, near)]

    def test_reading_the_map_file(self):
        with open(self.path, "rb") as fh:
            h = places.read_header(fh)
            tiles = list(places.iter_tiles(fh, h, 3))
        self.assertEqual((h["max_zoom"], h["tile_type"]), (3, 1))
        self.assertEqual(sorted((x, y) for x, y, _ in tiles), [(2, 2), (5, 2)])
        self.assertEqual(self.count, 10)          # rail, the county label, nameless, out-of-tile and buildings left out
        self.assertTrue(places.is_current(self.path))
        self.assertEqual([places.tile_xy(1, i) for i in range(1, 5)], [(0, 0), (0, 1), (1, 1), (1, 0)])   # from the PMTiles spec

    def test_a_town_is_found_and_placed_correctly(self):
        hit = self.find("wayne")[0]
        self.assertEqual((hit["name"], hit["kind"], hit["zoom"]), ("Wayne", "City", 12))
        self.assertAlmostEqual(hit["lon"], self.wayne[0], places=4)
        self.assertAlmostEqual(hit["lat"], self.wayne[1], places=4)
        self.assertEqual(self.names("WAYNE pub"), [("Wayne Public Library", "Library", "Wayne")])
        self.assertEqual(self.names("elm"), [("Elm", "Community", "")])
        self.assertEqual(self.names("mt clemens")[0], ("Mount Clemens", "City", ""))
        self.assertEqual(self.find("zzz"), [])
        self.assertEqual(self.find("railroad") + self.find("county") + self.find("searched") + self.find("edge"), [])

    def test_streets_say_which_town_and_the_nearest_comes_first(self):
        both = [("Main Street", "Road", "Wayne"), ("Main Street", "Road", "Plymouth")]
        self.assertEqual(self.names("main st", self.wayne), both)
        self.assertEqual(self.names("main street", self.plymouth), both[::-1])
        self.assertEqual(self.names("main st plymouth", self.wayne), [both[1]])      # the town can be typed too
        self.assertEqual(self.names("michigan ave"), [("Michigan Avenue", "Road", "Wayne")])
        self.assertEqual(self.names("us 12 michigan"), [("Michigan Avenue", "Road", "Wayne")])   # road number works too
        self.assertEqual([n[:2] for n in self.names("i 94", self.wayne)], [("I 94", "Highway")])  # once, not per town

    def test_a_map_without_an_index_says_so(self):
        other = os.path.join(maps.MAPS_DIR, "noindex.pmtiles")
        make_pmtiles(other, 3, {(2, 2): mvt_layer("places", [({"name": "Nowhere", "kind": "locality"}, [(1, 1)])])}, leaf=True)
        try:
            self.assertEqual(places.search("noindex.pmtiles", "nowhere"), {"ready": False, "results": []})
            self.assertEqual(places.build_index(other), 1)                           # also reads a leaf directory
            self.assertEqual([r["name"] for r in places.search("noindex.pmtiles", "now")["results"]], ["Nowhere"])
            os.utime(other, (1, 1))                                                  # the map file changed
            self.assertFalse(places.is_current(other))
            maps.delete("noindex.pmtiles")
            self.assertFalse(os.path.exists(places.db_path(other)))                  # the index goes with the map
        finally:
            for p in (other, places.db_path(other)):
                if os.path.exists(p):
                    os.remove(p)
        for bad in ["../zim/library.xml", "x.txt", ""]:
            with self.assertRaises(ValueError):
                places.search(bad, "wayne")
        with self.assertRaises(FileNotFoundError):
            places.search("missing.pmtiles", "wayne")

    def test_maps_without_names_are_found_and_queued(self):
        junk = os.path.join(maps.MAPS_DIR, "junk.pmtiles")
        with open(junk, "wb") as fh:
            fh.write(b"TILES")
        try:
            started = maps.index_missing()
            for j in started:
                wait(j)
            self.assertEqual([j.title for j in started], ["Place names for junk"])   # testland already has its index
            self.assertEqual(started[0].state, "done")                                # a bad file is reported, not fatal
            self.assertIn("Could not read place names", started[0].message)
        finally:
            os.remove(junk)

    def test_search_over_the_api(self):
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_port}/api/maps/search?file={self.file}"
        try:
            r = json.load(urllib.request.urlopen(f"{base}&q=main%20st&lon={self.plymouth[0]}&lat={self.plymouth[1]}"))
            self.assertEqual((r["ready"], r["results"][0]["near"]), (True, "Plymouth"))
            self.assertEqual(json.load(urllib.request.urlopen(base + "&q=w"))["results"], [])     # too short to search
            for bad in ["/api/maps/search?file=../x.pmtiles&q=wayne", "/api/maps/search?file=missing.pmtiles&q=wayne"]:
                with self.assertRaises(urllib.error.HTTPError):
                    urllib.request.urlopen(f"http://127.0.0.1:{srv.server_port}{bad}")
        finally:
            srv.shutdown()


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = os.urandom(10_000)
        open(os.path.join(maps.MAPS_DIR, "t.pmtiles"), "wb").write(cls.payload)
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def get(self, path, headers=None):
        try:
            return urllib.request.urlopen(urllib.request.Request(self.base + path, headers=headers or {}))
        except urllib.error.HTTPError as e:
            return e

    def test_range_requests(self):
        r = self.get("/maps-data/t.pmtiles", {"Range": "bytes=100-199"})
        self.assertEqual(r.status, 206)
        self.assertEqual(r.read(), self.payload[100:200])
        self.assertEqual(r.headers["Content-Range"], "bytes 100-199/10000")
        r = self.get("/maps-data/t.pmtiles", {"Range": "bytes=-50"})
        self.assertEqual(r.read(), self.payload[-50:])
        r = self.get("/maps-data/t.pmtiles", {"Range": "bytes=9990-"})
        self.assertEqual(r.read(), self.payload[9990:])
        self.assertEqual(self.get("/maps-data/t.pmtiles", {"Range": "bytes=20000-"}).code, 416)
        self.assertEqual(self.get("/maps-data/t.pmtiles").read(), self.payload)

    def test_map_path_traversal_blocked(self):
        for p in ["/maps-data/../zim/library.xml", "/maps-data/%2e%2e/x.pmtiles", "/maps-data/missing.pmtiles"]:
            self.assertEqual(self.get(p).code, 404, p)

    def test_api(self):
        self.assertEqual(json.load(self.get("/api/status"))["services"], {})
        self.assertEqual(json.load(self.get("/api/zim/presets"))[0]["id"], "starter")
        regions = json.load(self.get("/api/maps/regions"))
        self.assertIn("michigan", [r["id"] for r in regions["regions"]])
        req = urllib.request.Request(self.base + "/api/zim/download", method="POST", headers=JSON,
                                     data=json.dumps({"url": "https://evil.example/x.zim"}).encode())
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 400)


    def post(self, path, body=b"{}", headers=None):
        req = urllib.request.Request(self.base + path, method="POST", data=body, headers=headers or {})
        try:
            return urllib.request.urlopen(req).status
        except urllib.error.HTTPError as e:
            return e.code

    def test_posts_from_other_websites_are_refused(self):
        # A page on another site can only send "simple" content types without asking first.
        self.assertEqual(self.post("/api/zim/rescan"), 403)                           # urllib's default form type
        self.assertEqual(self.post("/api/zim/rescan", headers={"Content-Type": "text/plain"}), 403)
        self.assertEqual(self.post("/api/zim/rescan", headers={**JSON, "Origin": "http://evil.example"}), 403)
        self.assertEqual(self.post("/api/zim/rescan", headers={**JSON, "Origin": "null"}), 403)
        self.assertEqual(self.post("/api/auth/unlock", headers={"Content-Type": "text/plain"}), 403)
        # Our own pages: JSON, and an Origin (when the browser sends one) that is this deck.
        self.assertEqual(self.post("/api/zim/rescan", headers=JSON), 200)
        self.assertEqual(self.post("/api/zim/rescan", headers={**JSON, "Origin": self.base}), 200)

    def test_oversized_and_broken_requests_are_refused(self):
        self.assertEqual(self.post("/api/zim/rescan", b"{" + b" " * app.MAX_BODY + b"}", JSON), 400)
        self.assertEqual(self.post("/api/zim/rescan", b"not json", JSON), 400)
        self.assertEqual(self.post("/api/zim/rescan", b"[1, 2]", JSON), 400)
        self.assertEqual(self.post("/api/maps/extract", json.dumps({"region": "custom", "detail": "overview"}).encode(), JSON), 400)

    def test_folders_are_not_listed(self):
        os.makedirs(os.path.join(app.STATIC, "img"), exist_ok=True)
        self.assertEqual(self.get("/img/").code, 404)
        self.assertEqual(self.get("/").status, 200)            # a folder with an index page still opens


class BooksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = books.BOOKS_DIR
        os.makedirs(os.path.join(d, "Covers")); os.makedirs(os.path.join(d, "sub"))
        make_epub3(os.path.join(d, "water.epub"))
        make_epub2(os.path.join(d, "sub", "Knots_Guide.epub"))
        open(os.path.join(d, "broken.epub"), "wb").write(b"this is not a zip")
        cls.pdf = b"%PDF-1.4\n" + os.urandom(5000)
        # Same naming mismatch as the real collection: punctuation differs, cover is in Covers/.
        open(os.path.join(d, "Prepper's Hacks - Gear, Gadgets & Kits.pdf"), "wb").write(cls.pdf)
        open(os.path.join(d, "Covers", "Preppers Hacks - Gear Gadgets  Kits.jpg"), "wb").write(b"JPGDATA")
        open(os.path.join(d, "notes.txt"), "w").write("ignored")
        open(os.path.join(TMP, "secret.pdf"), "wb").write(b"outside the books folder")
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def get(self, path, headers=None):
        try:
            return urllib.request.urlopen(urllib.request.Request(self.base + path, headers=headers or {}))
        except urllib.error.HTTPError as e:
            return e

    def test_shelf_listing(self):
        shelf = {b["file"]: b for b in json.load(self.get("/api/books"))}
        self.assertEqual(set(shelf), {"water.epub", "sub/Knots_Guide.epub", "broken.epub",
                                      "Prepper's Hacks - Gear, Gadgets & Kits.pdf"})
        w = shelf["water.epub"]
        self.assertEqual((w["title"], w["author"], w["cover"], w["type"]), ("Water & Fire", "A. Tester", True, "epub"))
        self.assertEqual(shelf["sub/Knots_Guide.epub"]["title"], "Knots Guide")   # no dc:title: from file name
        self.assertTrue(shelf["sub/Knots_Guide.epub"]["cover"])
        self.assertTrue(shelf["broken.epub"]["broken"])
        self.assertTrue(shelf["Prepper's Hacks - Gear, Gadgets & Kits.pdf"]["cover"])

    def test_epub_reading_order_and_titles(self):
        info = books.epub_info("water.epub")
        # the manifest entry whose file is missing from the zip is dropped
        self.assertEqual(info["spine"], [{"href": "OEBPS/text/ch 1.xhtml", "title": "Finding Water"},
                                         {"href": "OEBPS/text/ch2.xhtml", "title": "Making Fire"}])
        self.assertEqual(books.epub_info("sub/Knots_Guide.epub")["spine"], [{"href": "a.html", "title": "Knots"}])
        r = self.get("/api/books/info?file=broken.epub")
        self.assertEqual(r.code, 400)
        self.assertIn("EPUB", json.load(r)["error"])

    def test_oversized_book_parts_are_refused(self):
        orig, books.MAX_MEMBER = books.MAX_MEMBER, 10
        try:
            with self.assertRaises(ValueError):
                books.epub_member("water.epub", "OEBPS/text/ch 1.xhtml")
            self.assertEqual(self.get("/books-read/water.epub/OEBPS/text/ch%201.xhtml").code, 404)
        finally:
            books.MAX_MEMBER = orig

    def test_chapters_served_safely(self):
        r = self.get("/books-read/water.epub/OEBPS/text/ch%201.xhtml")
        self.assertEqual(r.headers["Content-Type"], "application/xhtml+xml")
        self.assertIn("script-src 'none'", r.headers["Content-Security-Policy"])   # book scripts never run
        self.assertIn(b"Text of Finding Water", r.read())
        sloppy = self.get("/books-read/water.epub/OEBPS/text/ch2.xhtml")
        self.assertEqual(sloppy.headers["Content-Type"], "text/html")              # not well-formed: lenient mode
        self.assertEqual(self.get("/books-read/water.epub/OEBPS/img/front.png").read(), PNG)
        self.assertEqual(self.get("/books-read/sub/Knots_Guide.epub/a.html").status, 200)
        for bad in ["/books-read/water.epub/OEBPS/nope.xhtml", "/books-read/water.epub/../secret.pdf",
                    "/books-read/broken.epub/x.html", "/books-read/nothing.epub/a.html", "/books-read/water.epub"]:
            self.assertEqual(self.get(bad).code, 404, bad)

    def test_covers(self):
        self.assertEqual(self.get("/api/books/cover?file=water.epub").read(), PNG)
        self.assertEqual(self.get("/api/books/cover?file=sub/Knots_Guide.epub").read(), PNG)
        pdf = urllib.parse.quote("Prepper's Hacks - Gear, Gadgets & Kits.pdf")
        self.assertEqual(self.get("/api/books/cover?file=" + pdf).read(), b"JPGDATA")
        self.assertEqual(self.get("/api/books/cover?file=broken.epub").code, 404)

    def test_pdf_served_with_range_and_no_escape(self):
        url = "/books-data/" + urllib.parse.quote("Prepper's Hacks - Gear, Gadgets & Kits.pdf")
        r = self.get(url)
        self.assertEqual(r.headers["Content-Type"], "application/pdf")
        self.assertEqual(r.read(), self.pdf)
        self.assertEqual(self.get(url, {"Range": "bytes=0-7"}).read(), self.pdf[:8])
        for bad in ["/books-data/../secret.pdf", "/books-data/%2e%2e/secret.pdf", "/books-data/notes.txt",
                    "/books-data/Covers/Preppers%20Hacks%20-%20Gear%20Gadgets%20%20Kits.jpg", "/books-data/missing.pdf"]:
            self.assertEqual(self.get(bad).code, 404, bad)


class SystemTests(unittest.TestCase):
    """Readings come from a fake /proc and /sys tree shaped like a Raspberry Pi 5."""

    def setUp(self):
        self.root = tempfile.mkdtemp(dir=TMP)
        self.proc, self.sys = os.path.join(self.root, "proc"), os.path.join(self.root, "sys")
        self.put("proc/stat", "cpu  100 0 100 700 100 0 0 0 0 0\ncpu0 1 1 1 1 1 1 1 1 1 1\n")
        self.put("proc/meminfo", "MemTotal:        4000000 kB\nMemFree:          100000 kB\n"
                                 "MemAvailable:    1000000 kB\nSwapTotal:        200000 kB\nSwapFree:         150000 kB\n")
        self.put("proc/loadavg", "0.52 0.40 0.31 1/234 5678\n")
        self.put("proc/uptime", "93784.21 370000.00\n")
        self.put("proc/diskstats", " 179       0 mmcblk0 5000 10 400000 900 3000 20 2000000 800 0 100 1700\n"
                                   " 179       2 mmcblk0p2 4000 10 300000 800 2900 20 1900000 700 0 90 1500\n")
        self.put("sys/class/thermal/thermal_zone0/temp", "48350\n")
        self.put("sys/devices/platform/cooling_fan/hwmon/hwmon2/fan1_input", "2950\n")
        self.put("sys/devices/platform/soc/soc:firmware/get_throttled", "0\n")
        self.put("sys/devices/mmc/mmcblk0/mmcblk0p2/partition", "2\n")
        os.makedirs(os.path.join(self.sys, "dev/block"))
        os.symlink(os.path.join(self.sys, "devices/mmc/mmcblk0/mmcblk0p2"), os.path.join(self.sys, "dev/block/179:2"))
        self.saved = (system.PROC, system.SYS, system._dev_numbers, system._prev_cpu)
        system.PROC, system.SYS, system._prev_cpu = self.proc, self.sys, None
        system._dev_numbers = lambda path: (179, 2)

    def tearDown(self):
        system.PROC, system.SYS, system._dev_numbers, system._prev_cpu = self.saved

    def put(self, rel, text):
        p = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(text)

    def test_healthy_pi(self):
        system._prev_cpu = (700, 900)     # earlier sample: idle+iowait 700 of 900
        s = system.snapshot()
        # since then: 100 new ticks, all 100 of them idle
        self.assertEqual(s["cpu"]["percent"], 0.0)
        self.assertEqual(s["cpu"]["load"], [0.52, 0.40, 0.31])
        self.assertEqual(s["memory"]["total"], 4000000 * 1024)
        self.assertEqual(s["memory"]["used_percent"], 75.0)          # uses MemAvailable, not MemFree
        self.assertEqual(s["memory"]["swap_used"], 50000 * 1024)
        self.assertEqual((s["temp_c"], s["fan_rpm"], s["uptime_s"]), (48.4, 2950, 93784))
        self.assertEqual(s["disk"], {"device": "mmcblk0", "read": 400000 * 512, "written": 2000000 * 512})
        self.assertEqual((s["power"], s["warnings"]), ([], []))

    def test_cpu_percent_between_calls(self):
        system._prev_cpu = (400, 500)     # now idle 800 of 1000: 400 of the 500 new ticks were idle
        self.assertEqual(system.cpu_percent(), 20.0)
        self.assertEqual(system._prev_cpu, (800, 1000))

    def test_warnings(self):
        self.put("sys/class/thermal/thermal_zone0/temp", "81200\n")
        self.put("sys/devices/platform/soc/soc:firmware/get_throttled", "0x50005\n")   # bits 0, 2, 16, 18
        self.put("proc/meminfo", "MemTotal: 4000000 kB\nMemAvailable: 200000 kB\n")
        s = system.snapshot()
        self.assertEqual(s["power"], ["throttled", "throttled_past", "undervoltage", "undervoltage_past"])
        text = " | ".join(s["warnings"])
        for word in ("voltage is too low right now", "slowed down", "Running hot (81", "Memory is nearly full"):
            self.assertIn(word, text)
        self.put("sys/class/thermal/thermal_zone0/temp", "72000\n")
        self.put("sys/devices/platform/soc/soc:firmware/get_throttled", "0x10000\n")   # only "happened earlier"
        w = " | ".join(system.snapshot()["warnings"])
        self.assertIn("Running warm (72", w)
        self.assertIn("at some point since startup", w)
        self.assertNotIn("right now", w)

    def test_undervoltage_from_hwmon_driver(self):
        self.put("sys/class/hwmon/hwmon1/name", "rpi_volt\n")
        self.put("sys/class/hwmon/hwmon1/in0_lcrit_alarm", "1\n")
        self.assertIn("undervoltage", system.power_flags())

    def test_machine_without_pi_sensors(self):
        system.PROC = system.SYS = os.path.join(self.root, "nothing-here")
        system._dev_numbers = lambda path: (0, 55)
        s = system.snapshot()
        self.assertEqual((s["temp_c"], s["fan_rpm"], s["memory"], s["disk"], s["uptime_s"]), (None, None, None, None, None))
        self.assertEqual((s["cpu"]["percent"], s["cpu"]["load"], s["warnings"]), (None, None, []))


# Shape copied from kiwix-serve 3.8.2 on the Pi (/search?pattern=water+filter&format=xml), shortened.
KIWIX_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Search: water filter</title>
    <opensearch:totalResults>3,000</opensearch:totalResults>
    <opensearch:startIndex>0</opensearch:startIndex>
    <item>
      <title>Ceramic water filter</title>
      <link>/content/wikipedia_en_medicine_nopic_2026-10/Ceramic_water_filter</link>
        <description>...<b>water</b> <b>filter</b> A Victorian ceramic <b>water</b> <b>filter</b> Ceramic filters &amp; more......</description>
        <book>
          <title>WikiMed Medical Encyclopedia (nopic)</title>
        </book>
        <wordCount>1,401</wordCount>
    </item>
    <item>
      <title>Somewhere else</title>
      <link>//evil.example/page</link>
      <description>a link that does not stay on the Library app</description>
    </item>
  </channel>
</rss>"""


class FakeKiwix(http.server.BaseHTTPRequestHandler):
    mode = "ok"       # ok | mixed (refuses until the language filter is added) | empty | broken
    seen = []

    def log_message(self, *a): pass

    def do_GET(self):
        FakeKiwix.seen.append(self.path)
        if self.mode == "empty" or (self.mode == "mixed" and "books.filter.lang=eng" not in self.path):
            return self.send_error(400)
        if self.mode == "broken":
            return self.send_error(500)
        body = KIWIX_FEED.encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kiwix = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeKiwix)
        threading.Thread(target=cls.kiwix.serve_forever, daemon=True).start()
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.root = tempfile.mkdtemp(dir=TMP)
        for rel, text in {"Water Filter Build.md": "# Parts\nSand, gravel and **charcoal** in a bucket.",
                          "Shop/Printer fixes.md": "Clogged nozzle? Do a cold pull. Check the water cooling filter too.",
                          "Groceries.md": "eggs, coffee",
                          ".flatnotes/index.md": "water filter (search index, never shown)",
                          "attachments/water filter.md": "an attachment, not a note",
                          "photo.jpg": "water filter"}.items():
            p = os.path.join(cls.root, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as fh:
                fh.write(text)
        cls.saved = (search.KIWIX_URL, search.NOTES_DIR, books.list_books)
        search.KIWIX_URL, search.NOTES_DIR = f"http://127.0.0.1:{cls.kiwix.server_port}", cls.root
        books.list_books = lambda: [
            {"file": "survival/Water Purification.pdf", "type": "pdf", "title": "Water Purification", "author": "", "size": 1},
            {"file": "knots.epub", "type": "epub", "title": "Knots", "author": "A. Filter", "size": 1}]

    @classmethod
    def tearDownClass(cls):
        search.KIWIX_URL, search.NOTES_DIR, books.list_books = cls.saved
        cls.kiwix.shutdown(); cls.srv.shutdown()

    def setUp(self):
        FakeKiwix.mode, FakeKiwix.seen = "ok", []

    def test_library_results_are_tidied(self):
        r = search.libraries("water filter")
        self.assertEqual(r["total"], 3000)
        self.assertEqual(len(r["results"]), 1)                       # the off-site link is dropped
        hit = r["results"][0]
        self.assertEqual((hit["title"], hit["library"]), ("Ceramic water filter", "WikiMed Medical Encyclopedia (nopic)"))
        self.assertEqual(hit["path"], "/content/wikipedia_en_medicine_nopic_2026-10/Ceramic_water_filter")
        self.assertEqual(hit["snippet"], "water filter A Victorian ceramic water filter Ceramic filters & more")
        self.assertIn("pattern=water+filter", FakeKiwix.seen[0])

    def test_library_search_problems_do_not_break_the_page(self):
        FakeKiwix.mode = "mixed"                                     # libraries in two languages
        self.assertEqual(len(search.libraries("water")["results"]), 1)
        self.assertEqual(len(FakeKiwix.seen), 2)
        FakeKiwix.mode = "empty"                                     # nothing installed: no results, no alarm
        self.assertEqual(search.libraries("water"), {"total": 0, "results": [], "error": ""})
        FakeKiwix.mode = "broken"
        self.assertIn("error 500", search.libraries("water")["error"])
        search.KIWIX_URL, keep = "http://127.0.0.1:9", search.KIWIX_URL
        try:
            self.assertEqual(search.libraries("water")["error"], "The Library app is not answering")
        finally:
            search.KIWIX_URL = keep

    def test_notes_are_searched_by_title_and_text(self):
        got = search.notes("WATER filter")
        self.assertEqual([n["title"] for n in got], ["Water Filter Build", "Printer fixes"])    # title match first
        self.assertEqual(got[0]["snippet"], "Parts Sand, gravel and charcoal in a bucket.")      # markdown marks removed
        self.assertIn("water cooling filter", got[1]["snippet"])
        self.assertEqual([n["title"] for n in search.notes("charcoal bucket")], ["Water Filter Build"])
        self.assertEqual(search.notes("unicorn"), [])

    def test_books_match_on_title_author_and_file(self):
        self.assertEqual([b["title"] for b in search.shelf("water")], ["Water Purification"])
        self.assertEqual([b["title"] for b in search.shelf("filter")], ["Knots"])
        self.assertEqual([b["title"] for b in search.shelf("survival")], ["Water Purification"])

    def test_one_request_searches_everything(self):
        base = f"http://127.0.0.1:{self.srv.server_port}"
        r = json.load(urllib.request.urlopen(base + "/api/search?q=%20water%20%20filter%20"))
        self.assertEqual(r["q"], "water filter")
        self.assertEqual((len(r["notes"]), len(r["books"]), len(r["libraries"]["results"])), (2, 0, 1))
        for bad in ["", "%20%20", "x" * 201]:
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(base + "/api/search?q=" + bad)
            self.assertEqual(cm.exception.code, 400)


class BackupTests(unittest.TestCase):
    """A USB drive is a folder listed in a fake /proc/mounts, the way the Pi's desktop mounts one."""

    def setUp(self):
        self.root = tempfile.mkdtemp(dir=TMP)
        self.data, self.media = os.path.join(self.root, "data"), os.path.join(self.root, "media")
        self.stick = os.path.join(self.media, "nomad", "MY STICK")
        self.locked = os.path.join(self.media, "nomad", "LOCKED")
        os.makedirs(self.stick); os.makedirs(self.locked)
        self.put("notes/Shopping.md", "filament, nozzles")
        self.put("notes/What now?.md", "a title a FAT drive cannot store")
        self.put("notes/attachments/photo.jpg", "JPG")
        self.put("notes/.flatnotes/index", "search index: rebuilt by the Notes app, not backed up")
        self.put("books/manuals/Printer Manual.pdf", "%PDF" + "x" * 5000)
        mounts = os.path.join(self.root, "mounts")
        with open(mounts, "w") as fh:
            fh.write("/dev/root / ext4 rw,noatime 0 0\n"
                     f"/dev/sda1 {self.stick.replace(' ', chr(92) + '040')} vfat rw,nosuid,uid=1000 0 0\n"
                     f"/dev/sdb1 {self.locked} vfat ro,nosuid 0 0\n"
                     f"/dev/sdc1 {self.media}/nomad/GONE vfat rw 0 0\n"
                     "/dev/sdd1 /mnt/elsewhere vfat rw 0 0\n")
        self.saved = (backup.DATA, backup.MEDIA_DIR, backup.MOUNTS_FILE)
        backup.DATA, backup.MEDIA_DIR, backup.MOUNTS_FILE = self.data, self.media, mounts

    def tearDown(self):
        backup.DATA, backup.MEDIA_DIR, backup.MOUNTS_FILE = self.saved

    def put(self, rel, text):
        p = os.path.join(self.data, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(text)

    def made(self):
        folder = os.path.join(self.stick, backup.FOLDER)
        return sorted(os.listdir(folder)) if os.path.isdir(folder) else []

    def tree(self, top):
        return sorted(os.path.relpath(os.path.join(d, n), top) for d, _, names in os.walk(top) for n in names)

    def test_only_drives_under_media_are_offered(self):
        drives = backup.list_drives()
        self.assertEqual([(d["id"], d["name"], d["read_only"]) for d in drives],
                         [("nomad/MY STICK", "MY STICK", False), ("nomad/LOCKED", "LOCKED", True)])
        self.assertEqual(drives[0]["backups"], [])
        self.assertGreater(drives[0]["free"], 0)
        self.assertEqual(backup.sizes()["notes"]["files"], 3)        # the hidden index is not counted

    def test_backup_to_usb_copies_notes_and_books(self):
        job = backup.start_usb("nomad/MY STICK")
        wait(job)
        self.assertEqual(job.state, "done", job.message)
        self.assertEqual(job.done, job.total)
        (name,) = self.made()
        self.assertEqual(self.tree(os.path.join(self.stick, backup.FOLDER, name)),
                         ["books/manuals/Printer Manual.pdf", "installed-content.txt", "notes/Shopping.md",
                          "notes/What now_.md", "notes/attachments/photo.jpg"])
        self.assertEqual(backup.list_drives()[0]["backups"], [name])
        again = backup.start_usb("nomad/MY STICK", books=False)      # same minute: a second folder, nothing overwritten
        wait(again)
        newest = [n for n in self.made() if n != name][0]
        self.assertNotIn("books/manuals/Printer Manual.pdf", self.tree(os.path.join(self.stick, backup.FOLDER, newest)))
        self.assertIn("Libraries (Content Manager):", open(os.path.join(self.stick, backup.FOLDER, newest, "installed-content.txt")).read())

    def test_bad_drive_choices_are_refused(self):
        for drive in ["nomad/LOCKED", "nomad/GONE", "nomad/NOPE", "../data", "", "/"]:
            with self.assertRaises(ValueError, msg=drive):
                backup.start_usb(drive)
        self.assertEqual(os.listdir(self.locked), [])

    def test_full_drive_leaves_no_half_backup(self):
        import collections
        usage, orig = collections.namedtuple("usage", "total used free"), backup.shutil.disk_usage
        backup.shutil.disk_usage = lambda p: usage(1 << 30, 1 << 30, 1000)
        try:
            job = backup.start_usb("nomad/MY STICK")
            wait(job)
        finally:
            backup.shutil.disk_usage = orig
        self.assertEqual((job.state, job.message), ("error", "Not enough room on that drive"))
        self.assertEqual(self.made(), [])

    def test_cancelled_backup_is_removed(self):
        self.put("books/big.pdf", "x" * (3 << 20))
        orig = backup.manifest
        def cancel_then_list():                # cancel after the files are copied, before it finishes
            jobs.cancel(job.id)
            raise InterruptedError
        backup.manifest = cancel_then_list
        try:
            job = backup.start_usb("nomad/MY STICK")
            wait(job)
        finally:
            backup.manifest = orig
        self.assertEqual(job.state, "cancelled")
        self.assertEqual(self.made(), [])

    def test_notes_download_is_a_zip(self):
        import io
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{srv.server_port}"
            r = urllib.request.urlopen(base + "/api/backup/download")
            self.assertIn("attachment", r.headers["Content-Disposition"])
            z = zipfile.ZipFile(io.BytesIO(r.read()))
            info = json.load(urllib.request.urlopen(base + "/api/backup"))
        finally:
            srv.shutdown()
        self.assertEqual(sorted(z.namelist()), ["installed-content.txt", "notes/Shopping.md", "notes/What now?.md",
                                                "notes/attachments/photo.jpg"])
        self.assertEqual(z.read("notes/Shopping.md"), b"filament, nozzles")
        self.assertIsNone(z.testzip())
        self.assertEqual([d["name"] for d in info["drives"]], ["MY STICK", "LOCKED"])
        self.assertEqual(info["sizes"]["books"]["files"], 1)


class PowerTests(unittest.TestCase):
    """The app only ever writes one word to a file; the helper on the Pi does the rest."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=TMP)
        self.saved, power.POWER_DIR = power.POWER_DIR, self.dir
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_port}"

    def tearDown(self):
        power.POWER_DIR = self.saved
        self.srv.shutdown()

    def post(self, action):
        req = urllib.request.Request(self.base + "/api/power", headers=JSON, data=json.dumps({"action": action}).encode())
        try:
            r = urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            r = e
        return (r.status if hasattr(r, "status") else r.code), json.load(r)

    def asked(self):
        p = os.path.join(self.dir, "request")
        return open(p).read() if os.path.exists(p) else None

    def test_nothing_happens_until_the_helper_is_installed(self):
        self.assertEqual(json.load(urllib.request.urlopen(self.base + "/api/power")), {"available": False, "busy": []})
        status, data = self.post("poweroff")
        self.assertEqual(status, 400)
        self.assertIn("install.sh", data["error"])
        self.assertIsNone(self.asked())

    def test_only_two_requests_can_be_made(self):
        open(os.path.join(self.dir, "helper-installed"), "w").close()
        self.assertTrue(power.available())
        for bad in ["rm -rf /", "halt", "", None, "poweroff; reboot", ["reboot"]]:
            self.assertEqual(self.post(bad)[0], 400, bad)
            self.assertIsNone(self.asked())
        self.assertEqual(self.post("reboot"), (200, {"ok": True, "action": "reboot", "message": "Restarting"}))
        self.assertEqual(self.asked(), "reboot\n")
        self.assertEqual(self.post("poweroff")[0], 200)
        self.assertEqual(self.asked(), "poweroff\n")

    def test_running_work_is_reported_before_a_shutdown(self):
        go = threading.Event()
        job = jobs.start("backup", "Backup to USB", lambda j: go.wait(5))
        time.sleep(0.1)
        try:
            self.assertIn("Backup to USB", power.status()["busy"])
        finally:
            go.set(); wait(job)
        self.assertNotIn("Backup to USB", power.status()["busy"])


class AuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"
        cls.iters, auth.ITERATIONS = auth.ITERATIONS, 1000      # keep the tests quick

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        auth.ITERATIONS = cls.iters

    def setUp(self):
        auth.clear_pin()

    def tearDown(self):
        auth.clear_pin()        # leave the other test classes with no PIN set

    def call(self, path, body=None, cookie=""):
        """Returns (status, json, cookie value set by the reply or None)."""
        req = urllib.request.Request(self.base + path, headers={**JSON, **({"Cookie": cookie} if cookie else {})},
                                     data=None if body is None else json.dumps(body).encode())
        try:
            r = urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            r = e
        set_cookie = r.headers.get("Set-Cookie")
        return r.status if hasattr(r, "status") else r.code, json.load(r), set_cookie

    def test_open_until_a_pin_is_set(self):
        self.assertEqual(self.call("/api/auth")[1], {"pin_set": False, "unlocked": False})
        self.assertEqual(self.call("/api/zim/rescan", {})[0], 200)           # no PIN: actions still work
        self.assertEqual(self.call("/api/auth/unlock", {"pin": "1234"})[0], 403)
        self.assertEqual(self.call("/api/auth/set", {"pin": "123"})[0], 400)  # too short
        self.assertFalse(auth.pin_set())

    def test_pin_protects_every_changing_action_but_not_reading(self):
        status, _, cookie = self.call("/api/auth/set", {"pin": "2468"})
        self.assertEqual(status, 200)
        self.assertIn("HttpOnly", cookie); self.assertIn("SameSite=Strict", cookie)
        mine = cookie.split(";")[0]
        for path, body in [("/api/zim/download", {"url": "https://download.kiwix.org/zim/a.zim"}),
                           ("/api/zim/delete", {"file": "x.zim"}), ("/api/zim/rescan", {}),
                           ("/api/jobs/cancel", {"id": "x"}), ("/api/power", {"action": "poweroff"}),
                           ("/api/backup/usb", {"drive": "x"}),
                           ("/api/maps/extract", {"region": "detroit", "detail": "overview"}),
                           ("/api/maps/estimate", {"region": "detroit", "detail": "overview"}),
                           ("/api/maps/delete", {"file": "x.pmtiles"}), ("/api/auth/set", {"pin": "0000"}),
                           ("/api/auth/clear", {}), ("/api/anything-new", {})]:
            status, data, _ = self.call(path, body)
            self.assertEqual((status, data.get("locked")), (401, True), path)
        for path in ["/api/status", "/api/books", "/api/system", "/api/maps/list", "/api/jobs", "/"]:
            self.assertEqual(urllib.request.urlopen(self.base + path).status, 200, path)
        self.assertEqual(self.call("/api/zim/rescan", {}, mine)[0], 200)      # the device that set it is unlocked
        self.assertEqual(self.call("/api/auth", cookie=mine)[1], {"pin_set": True, "unlocked": True})
        self.assertEqual(self.call("/api/zim/rescan", {}, "nomad_admin=made-up-token")[0], 401)

    def test_unlock_lock_and_change(self):
        auth.set_pin("2468")
        self.assertEqual(self.call("/api/auth/unlock", {"pin": "1111"})[:2], (403, {"error": "Wrong PIN"}))
        status, _, cookie = self.call("/api/auth/unlock", {"pin": "2468"})
        mine = cookie.split(";")[0]
        self.assertEqual((status, self.call("/api/zim/rescan", {}, mine)[0]), (200, 200))
        self.assertEqual(self.call("/api/auth/lock", {}, mine)[0], 200)
        self.assertEqual(self.call("/api/zim/rescan", {}, mine)[0], 401)       # locked again
        mine = self.call("/api/auth/unlock", {"pin": "2468"})[2].split(";")[0]
        newer = self.call("/api/auth/set", {"pin": "new-pin"}, mine)[2].split(";")[0]
        self.assertEqual(self.call("/api/zim/rescan", {}, mine)[0], 401)       # changing the PIN signs old sessions out
        self.assertEqual(self.call("/api/zim/rescan", {}, newer)[0], 200)
        self.assertFalse(auth.verify("2468")); self.assertTrue(auth.verify("new-pin"))
        self.assertEqual(self.call("/api/auth/clear", {}, newer)[0], 200)
        self.assertEqual(self.call("/api/zim/rescan", {})[0], 200)             # no PIN: open again

    def test_wrong_tries_cause_a_pause(self):
        auth.set_pin("2468")
        for _ in range(auth.MAX_FAILS):
            self.assertEqual(self.call("/api/auth/unlock", {"pin": "nope"})[0], 403)
        status, data, _ = self.call("/api/auth/unlock", {"pin": "2468"})       # even the right PIN must wait
        self.assertEqual(status, 429); self.assertIn("Wait", data["error"])
        auth._fails["until"] = time.time() - 1                                 # the pause has passed
        self.assertEqual(self.call("/api/auth/unlock", {"pin": "2468"})[0], 200)
        self.assertEqual(auth._fails["count"], 0)

    def test_pin_is_stored_hashed_and_sessions_expire(self):
        auth.set_pin("zebra-pin")      # letters a hex hash can never contain, so this cannot fail by chance
        raw = open(os.path.join(auth.CONFIG_DIR, "admin.json")).read()
        self.assertNotIn("zebra", raw)
        self.assertEqual(os.stat(os.path.join(auth.CONFIG_DIR, "admin.json")).st_mode & 0o777, 0o600)
        token = auth.new_session()
        self.assertTrue(auth.valid(token))
        auth._sessions[token] = time.time() - 1
        self.assertFalse(auth.valid(token))
        open(os.path.join(auth.CONFIG_DIR, "admin.json"), "w").write("garbage")   # damaged file = no PIN, not a crash
        self.assertFalse(auth.pin_set())


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
