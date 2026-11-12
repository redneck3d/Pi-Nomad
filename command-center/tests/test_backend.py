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
                  BOOKS_DIR=os.path.join(TMP, "books"))
os.makedirs(os.environ["ZIM_DIR"]); os.makedirs(os.environ["MAPS_DIR"]); os.makedirs(os.environ["BOOKS_DIR"])

import zipfile  # noqa: E402

import app, books, jobs, maps, zim  # noqa: E402

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


class DownloadTests(unittest.TestCase):
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
                     ("custom", ["10", "0", "5", "1"], "standard"), ("custom", ["a", "b", "c", "d"], "standard")]:
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
        maps.PMTILES_BIN = "false"
        maps.planet_url = lambda: "https://example.invalid/planet.pmtiles"
        job = maps.start_extract("ohio", None, "overview")
        wait(job)
        self.assertEqual(job.state, "error")
        self.assertFalse(os.path.exists(os.path.join(maps.MAPS_DIR, "ohio-overview.pmtiles.part")))


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
        req = urllib.request.Request(self.base + "/api/zim/download", method="POST",
                                     data=json.dumps({"url": "https://evil.example/x.zim"}).encode())
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 400)


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


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
