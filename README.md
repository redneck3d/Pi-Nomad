# Pi-NOMAD

An offline-first knowledge server for a Raspberry Pi 5, modeled on [Project NOMAD](https://github.com/Crosstalk-Solutions/project-nomad) without the AI stack.

## Feature map

| NOMAD feature | Pi-NOMAD | Status |
|---|---|---|
| Information Library (Kiwix) | `kiwix` | Working config |
| Notes (FlatNotes) | `flatnotes` | Working config |
| Data tools (CyberChef) | `cyberchef` | Verify arm64 image |
| Supply Depot / file tools | `filebrowser` | Working config |
| Offline maps (ProtoMaps) | Viewer at `/maps/`, region manager at `/maps/manage.html` | Built; see "Still not tested" |
| Content downloads (ZIM manager) | `/zim.html`: collections, catalog search, resumable downloads, delete | Built; see "Still not tested" |
| Education (Kolibri) | commented out in compose | Need arm64 image |
| Your own books (not in NOMAD) | Bookshelf at `/books/`: lists EPUB and PDF files from `/srv/nomad/books`, built-in EPUB reader | Built and browser-tested with generated books; not yet tried with real ones |
| System info | System panel on the dashboard: temperature, fan, processor, memory, uptime, drive writes, clock check, power and heat warnings | Built; tested with simulated Pi readings, not on a real Pi |
| Admin lock (not in NOMAD) | Optional admin PIN: reading stays open, downloads and deletes need the PIN | Built; tested in a browser |
| Command Center (dashboard) | `command-center` (Python, no deps) | Done: tiles, live status, storage, content and map managers. Start/stop buttons are next |
| Setup wizard + content collections | `install.sh` + Content Manager collections | Collections done; no first-run wizard yet |
| Auto updates | none | Phase 3 (Watchtower or cron) |
| Benchmark | none | Optional |
| AI chat + RAG | dropped on purpose | n/a |

Added for the cyberdeck: `hotspot.sh` makes the Pi its own Wi-Fi network, so it works with no internet.

## Install (on the Pi)

Needs Raspberry Pi OS 64-bit. Content lives in `/srv/nomad` on the SD card (see Storage below).

    sudo ./install.sh
    sudo ./hotspot.sh MyDeck 'a-good-passphrase'   # optional

Then open `http://<pi>.local/`.

## Storage (512GB SD card)

512GB is enough for this build. The workload is mostly reads, which SD cards handle well. Things to do:

- Buy a high-endurance or A2-rated card from a known brand; fakes are common at this size.
- Keep it read-mostly: Docker logs are the main steady writer, so cap them (`log-opts` in `/etc/docker/daemon.json`).
- Back up your notes (`/srv/nomad/notes`) off the card now and then, since SD cards fail without warning.
- If you outgrow it, mount a USB SSD at `/srv/nomad` and nothing else changes.
- The dashboard's Storage panel shows free space and what is using it.

## How content and maps work

- **ZIM manager:** searches the Kiwix catalog, downloads into `/srv/nomad/zim` (resumes if Wi-Fi drops, one download at a time, refuses if the card would fill up), and adds the file to `library.xml` itself. Kiwix reloads that file automatically.
- **Maps:** the Protomaps planet file is far too big for the card, so the manager cuts out just your region with the `pmtiles extract` tool. The viewer (MapLibre) and Protomaps' fonts and icons are bundled into the Docker image, so maps work with no internet. You can also drop any `.pmtiles` file into `/srv/nomad/maps`.

## Bookshelf

Put EPUB and PDF files in `/srv/nomad/books` (subfolders are fine) and they appear at `/books/`. EPUBs open in a built-in reader (chapter list, text size, light/sepia/dark, remembers your place per device). PDFs open in the browser's own viewer. Covers come from inside the EPUB, or from a JPG/PNG with the same name as the book, anywhere in the books folder (a `Covers` subfolder works; punctuation differences are ignored). Scripts inside books are blocked. EPUBs with DRM will not open.

To add books: `sudo cp -r /path/to/books/* /srv/nomad/books/` on the Pi, or upload through the Files app.

## Admin PIN

Set a PIN from the banner at the top of the dashboard. After that, anyone on the network can still read everything, but downloading, deleting and other changes ask for the PIN. An unlocked device stays unlocked for 12 hours or until you press Lock. Five wrong tries cause a pause that grows with each further try.

- Forgot it: `docker compose exec command-center python auth.py reset`, then set a new one.
- The PIN is stored only as a salted hash in its own Docker volume (`nomad-config`).
- **It does not cover the other apps.** Files (port 8083) can still change or delete anything under `/srv/nomad`, and Notes is open to everyone. Files has its own login; check how it behaves on first run.
- Traffic is plain HTTP, so the PIN is only as private as your Wi-Fi password.

## What has been verified (2026-11-08)

Unit tests (`cd command-center && python3 tests/test_backend.py`, 30 tests) cover resuming a dropped download, path-traversal checks, Range requests and library writing. The map viewer was loaded in real Chrome against a generated test map. The live services were then checked from a real browser:

- **Kiwix catalog:** the real feed format is parsed (the parser test uses an entry copied from the live catalog). The catalog moved to `opds.library.kiwix.org`, and download links use `lb.download.kiwix.org`; both are handled. Kiwix publishes variants (nopic, mini, maxi) under one name, so presets pick a flavour. All 7 collections resolve against the live catalog with the sizes shown in their descriptions.
- **library.xml:** the attributes written match what libkiwix 14.2.1 (used by kiwix-tools 3.8.2) reads. The next libkiwix, currently unreleased, switches this file to a different format, so the compose file pins `kiwix-serve:3.8.2`. Don't change that tag without re-checking.
- **Protomaps:** the `build.protomaps.com/YYYYMMDD.pmtiles` URL pattern is right (the newest build is probed first, then older ones). The `pmtiles extract` flags (`--bbox`, `--maxzoom`, `--dry-run`) exist in the CLI source. The font and icon repo layout matches the Dockerfile, and the builds are compatible with `@protomaps/basemaps` 4 and 5 (the image uses 5).

## Still not tested

- **The Docker build itself:** building `pmtiles` with Go, fetching the fonts and icons, and arm64 on the Pi. Docker Desktop on a PC could not be reached from the Claude session, so the first `docker compose build` on the Pi is the real test.
- **A real download:** Kiwix mirrors should honor resume (Range) requests, but this wasn't confirmed.
- **A real `kiwix-serve` reading a file we wrote:** verified against the source code, not by running it.
- **A real map extract** (the tool only runs on the Pi or in Docker).

## Next steps

1. First run on the Pi: build, then download the Starter kit and a Detroit-metro map as a smoke test.
2. Command Center: start/stop buttons, updates.
3. Place search on the map (geocoding).
4. Kolibri: pick and test an arm64 image.

## Notes

- The admin PIN is a light lock for a private network, not real security. Keep the deck on the hotspot/LAN, not the open internet.
- On 4GB RAM, skip full Wikipedia with images in memory-heavy use and prefer the nopic builds.
