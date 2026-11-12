# Pi-NOMAD: handoff notes for Claude Code

Offline-first knowledge server for a **Raspberry Pi 5 (4 GB, arm64, 512 GB SD card)** inside a Pelican-case cyberdeck.
It is modeled on Project NOMAD (https://github.com/Crosstalk-Solutions/project-nomad) **without the AI stack**.
Owner: Mike, who runs a 3D printing and printer repair business in Wayne, Michigan. Keep answers plain and practical.

## Layout

- `compose.yaml`: stack: `command-center` (built from `./command-center`), `kiwix`, `flatnotes`, `cyberchef`, `filebrowser`. Kolibri is commented out (no arm64 image picked yet).
- `command-center/`: Python **stdlib-only** web app on port 80.
  - `app.py` router and Range-capable `/maps-data/` file server; `zim.py` Kiwix catalog search, resumable downloads, `library.xml` writer; `maps.py` Protomaps region extracts via the `pmtiles` CLI; `jobs.py` background job registry.
  - `books.py` bookshelf: lists EPUB/PDF under `/data/books` (read-only mount), serves EPUB chapters straight out of the zip at `/books-read/<book>.epub/<member>` with a no-scripts CSP, PDFs at `/books-data/`. Pages: `static/books/index.html`, `static/books/read.html`. Tested with generated EPUB 2/3 files only, not real books yet.
  - `system.py` system panel (`/api/system`): reads `/proc` and `/sys` directly (host values are visible inside Docker). Pi paths used: `thermal_zone*/temp`, `cooling_fan/hwmon/*/fan1_input`, firmware `get_throttled`, `rpi_volt` hwmon. Those sysfs paths were written from memory and tested only against a fake tree (`PROC_DIR`/`SYS_DIR` env vars), so confirm them on the real Pi 5.
  - `auth.py` optional admin PIN. No PIN set = everything open. PIN set = every POST except `/api/auth/unlock|lock` needs an unlocked session cookie (`nomad_admin`, 12 h, in memory); GETs stay open. Hash lives in the `nomad-config` volume at `/config/admin.json`. `static/auth.js` holds the `Admin` object (PIN dialogs, dashboard strip); `shared.js` `api()` prompts for the PIN on a 401 and retries. Any new endpoint that changes state must be a POST so it is covered.
  - `static/`: dashboard (`index.html`), Content Manager (`zim.html`), map viewer (`maps/index.html`), map region manager (`maps/manage.html`).
  - `Dockerfile`: 3 stages: Go builds `pmtiles`; Node fetches maplibre-gl@5, pmtiles@4, @protomaps/basemaps@5 plus Protomaps fonts/sprites from GitHub; Python runs the app.
  - `tests/test_backend.py`: 30 unit tests. Run: `cd command-center && python3 tests/test_backend.py`
- `install.sh` (Docker + data dirs + `docker compose up -d --build`), `hotspot.sh` (Wi-Fi AP via NetworkManager).
- Data lives in `/srv/nomad/{zim,maps,notes,books}`. Command-center mounts `zim` and `maps` writable, the rest read-only, plus the `nomad-config` volume at `/config`.

## Hard constraints (verified 2026-11-08, don't break these)

- **Keep `ghcr.io/kiwix/kiwix-serve:3.8.2` pinned.** It uses libkiwix 14.2.1, which reads `library.xml` as `<library><book .../></library>`. Unreleased libkiwix `main` switches to an Atom/OPDS feed, which would make our library writer silently stop working. Attribute names we write were checked against `Book::updateFromXml` in libkiwix 14.2.1; `size` is KiB.
- The kiwix image's start script adds `--port` itself; it runs as uid 1001, so ZIMs must be world-readable.
- Kiwix catalog is `https://opds.library.kiwix.org/catalog/v2/entries` (the old host redirects). The `name=` filter is exact. One name can have several **flavours** (`nopic`, `mini`, `maxi`), so presets pick `(name, flavour)`. Download links are on `lb.download.kiwix.org` and end in `.zim.meta4` (strip it). Downloads are restricted to `*.download.kiwix.org`.
- `gutenberg_en_all` is 221 GB: never offer it. Wikipedia `nopic` is ~53 GB, `mini` ~14 GB, `maxi` ~127 GB.
- Protomaps daily builds: `https://build.protomaps.com/YYYYMMDD.pmtiles` (~139 GB planet; today's UTC build often 404s, so probe newest-first). They are compatible with `@protomaps/basemaps` 4 and 5. `pmtiles extract` has `--bbox`, `--maxzoom`, `--dry-run`. Fonts/sprites repo: `protomaps/basemaps-assets` (`fonts/`, `sprites/v4/light.*`).
- maplibre-gl **6.x is ESM-only**; we use 5.x because the viewer loads the UMD build with a plain `<script>`.
- Only a light admin PIN (see `auth.py`); the other apps (Files, Notes, Kiwix) are not behind it. Don't expose to the internet.

## What has and hasn't been tested

Tested: all unit tests; the map viewer in headless Chrome with a generated PMTiles file (Range requests work); live Kiwix catalog (all 7 presets resolve); live Protomaps URLs; libkiwix source.

**Not yet tested (do these first, on Docker Desktop):**
1. `docker build -t pi-nomad-cc ./command-center` (Go build, npm, GitHub clone of fonts/sprites).
2. Run it: `docker run --rm -p 8099:80 -e NOMAD_DATA=/data -v "${PWD}/testdata/zim:/data/zim" -v "${PWD}/testdata/maps:/data/maps" pi-nomad-cc`, then in the UI download `zimgit-water_en` (21 MB, real download + resume + registration) and a Detroit-metro **Overview** map (real `pmtiles extract`), then open the map viewer. Check fonts/labels render (the headless test had no fonts).
3. Run kiwix against the same folder: `docker run --rm -p 8080:8080 -v "${PWD}/testdata/zim:/data/zim:ro" ghcr.io/kiwix/kiwix-serve:3.8.2 --library --monitorLibrary /data/zim/library.xml` and confirm the downloaded book is listed and opens. This is the first real test of our hand-written `library.xml`.
4. Whether Kiwix mirrors honor HTTP Range (resume). If not, resume silently restarts (the code handles a 200 reply).
5. arm64 specifics can only be confirmed on the Pi. `cyberchef` (`ghcr.io/gchq/cyberchef`) arm64 support is unconfirmed.

## Next work, in order

1. Fix anything the Docker tests above turn up.
2. Dashboard start/stop buttons (needs the Docker socket without read-only intent; discuss the risk first, it is root-equivalent).
3. Map place search (geocoding); first-run setup wizard; auto-update option.
4. Kolibri: find a maintained arm64 image, test it, then uncomment in `compose.yaml`.
5. Cap Docker log size in `/etc/docker/daemon.json` (SD card wear): add to `install.sh`.

## Working style

- Verify against real sources before claiming something works; say plainly what wasn't tested.
- Keep the command-center dependency-free (stdlib only) unless there is a strong reason.
- Add or update a unit test with every backend change.
- Commits: author them as the repo owner (`redneck3d`, GitHub noreply email). Do not add `Co-Authored-By: Claude` or any other Claude/AI attribution lines to commit messages or pull requests.
