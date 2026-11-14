# Pi-NOMAD: handoff notes for Claude Code

Offline-first knowledge server for a **Raspberry Pi 5 (4 GB, arm64, 128 GB SD card, about 96 GB free after install)** inside a Pelican-case cyberdeck.
It is modeled on Project NOMAD (https://github.com/Crosstalk-Solutions/project-nomad) **without the AI stack**.
Owner: Mike, who runs a 3D printing and printer repair business in Wayne, Michigan. Keep answers plain and practical.

## Layout

- `compose.yaml`: stack: `command-center` (built from `./command-center`), `kiwix`, `flatnotes`, `cyberchef`, `files` (Dufs). Kolibri is commented out (no arm64 image picked yet).
- `command-center/`: Python **stdlib-only** web app on port 80.
  - `app.py` router and Range-capable `/maps-data/` file server; `zim.py` Kiwix catalog search, resumable downloads, `library.xml` writer; `maps.py` Protomaps region extracts via the `pmtiles` CLI; `jobs.py` background job registry.
  - `books.py` bookshelf: lists EPUB/PDF under `/data/books` (read-only mount), serves EPUB chapters straight out of the zip at `/books-read/<book>.epub/<member>` with a no-scripts CSP, PDFs at `/books-data/`. Pages: `static/books/index.html`, `static/books/read.html`. Tested with generated EPUB 2/3 files only, not real books yet.
  - `system.py` system panel (`/api/system`): reads `/proc` and `/sys` directly (host values are visible inside Docker). Checked on the real Pi 5 on 2026-11-12: `thermal_zone*/temp`, memory, uptime, disk and the `rpi_volt` hwmon `in0_lcrit_alarm` all read correctly. The firmware `get_throttled` file does not exist on this kernel (Debian 13), so throttle flags are never reported. `cooling_fan/hwmon/*/fan1_input` is unchecked because no fan is fitted.
  - `auth.py` optional admin PIN. No PIN set = everything open. PIN set = every POST except `/api/auth/unlock|lock` needs an unlocked session cookie (`nomad_admin`, 12 h, in memory); GETs stay open. Hash lives in the `nomad-config` volume at `/config/admin.json`. `static/auth.js` holds the `Admin` object (PIN dialogs, dashboard strip, styled with the theme's CSS variables, so the page must load `style.css`); `shared.js` `api()` prompts for the PIN on a 401 and retries. Any new endpoint that changes state must be a POST so it is covered.
  - `static/`: dashboard (`index.html`), Content Manager (`zim.html`), map viewer (`maps/index.html`), map region manager (`maps/manage.html`), bookshelf (`books/`). All share `style.css` (colours taken from the logo) and `shared.js`. `img/` holds the logo cut-outs and icons; `fonts/` bundles Outfit (OFL), so the design needs no internet.
  - `Dockerfile`: 3 stages: Go builds `pmtiles`; Node fetches maplibre-gl@5, pmtiles@4, @protomaps/basemaps@5 plus Protomaps fonts/sprites from GitHub; Python runs the app.
  - `tests/test_backend.py`: 43 unit tests. Run: `cd command-center && python3 tests/test_backend.py`
- `install.sh` (Docker + data dirs + `docker compose up -d --build`), `hotspot.sh` (Wi-Fi AP via NetworkManager).
- Data lives in `/srv/nomad/{zim,maps,notes,books}`. Command-center mounts `zim` and `maps` writable, the rest read-only, plus the `nomad-config` volume at `/config`.
- `.gitattributes` forces LF line endings. Keep it: `install.sh` copied to the Pi with Windows line endings will not run.

## Hard constraints (verified 2026-11-08, don't break these)

- **Keep `ghcr.io/kiwix/kiwix-serve:3.8.2` pinned.** It uses libkiwix 14.2.1, which reads `library.xml` as `<library><book .../></library>`. Unreleased libkiwix `main` switches to an Atom/OPDS feed, which would make our library writer silently stop working. Attribute names we write were checked against `Book::updateFromXml` in libkiwix 14.2.1; `size` is KiB.
- The kiwix image's start script adds `--port` itself; it runs as uid 1001, so ZIMs must be world-readable.
- `ghcr.io/gchq/cyberchef` listens on 8080 inside the container. `files` (Dufs, which replaced the archived File Browser) must run as root to write to the root-owned data folder.
- kiwix-serve reloads `library.xml` only when its whole-second mtime increases, so `_write_library` always advances it.
- A note uploaded through Files is root-owned, so Notes can't save edits to it until the `flatnotes` container restarts (its start script fixes ownership).
- Kiwix catalog is `https://opds.library.kiwix.org/catalog/v2/entries` (the old host redirects). The `name=` filter is exact. One name can have several **flavours** (`nopic`, `mini`, `maxi`), so presets pick `(name, flavour)`. Download links are on `lb.download.kiwix.org` and end in `.zim.meta4` (strip it). Downloads are restricted to `*.download.kiwix.org`.
- `gutenberg_en_all` is 221 GB: never offer it. Wikipedia `nopic` is ~53 GB, `mini` ~14 GB, `maxi` ~127 GB.
- Protomaps daily builds: `https://build.protomaps.com/YYYYMMDD.pmtiles` (~139 GB planet; today's UTC build often 404s, so probe newest-first). They are compatible with `@protomaps/basemaps` 4 and 5. `pmtiles extract` has `--bbox`, `--maxzoom`, `--dry-run`. Fonts/sprites repo: `protomaps/basemaps-assets` (`fonts/`, `sprites/v4/light.*`).
- Every POST must carry `Content-Type: application/json` and, when the browser sends an `Origin`, it must match `Host` (`_from_our_pages` in `app.py`). This stops another website from making a browser on the LAN delete or download things. `shared.js` `api()` and `auth.js` already do this; curl needs `-H "Content-Type: application/json"`.
- Downloads are checked against the `<url>.sha256` file Kiwix publishes (verified live 2026-11-14 on `lb.download.kiwix.org`). A mismatch deletes the file; no checksum file means no check.
- Successful GETs are not logged (dashboards poll every few seconds), and compose caps each container log at 3 x 5 MB.
- maplibre-gl **6.x is ESM-only**; we use 5.x because the viewer loads the UMD build with a plain `<script>`.
- Only a light admin PIN (see `auth.py`); the other apps (Files, Notes, Kiwix) are not behind it. Don't expose to the internet.
- Files is Dufs, which serves the data folder at its root: the books folder is `http://<pi>:8083/books/`.

## What has and hasn't been tested

Tested 2026-11-09 on Docker Desktop (amd64), full `docker compose` stack with data on a root-owned Linux filesystem: image build; all unit tests; real ZIM download, resume (mirror answered 206, SHA-256 matched), cancel, delete; `kiwix-serve:3.8.2` listing, opening and dropping books from our `library.xml`; real `pmtiles extract`; map viewer in headless Chromium (fonts, sprites, labels, no external requests); Notes write; Files upload/delete; all 7 presets. The command-center image also builds and runs a real extract as arm64 under QEMU; the other four images publish arm64.

Windows bind mounts hide ownership problems. To test permissions, use a Linux path such as `NOMAD_DATA=/tmp/nomad-test`, created as root.

Tested 2026-11-09 on the real Pi 5 (4 GB, Debian 13 trixie, 192.168.1.26 on Wi-Fi): `install.sh` with Docker 29.9.3; all five containers running as arm64 with no errors in their logs; real ZIM download opened in Kiwix; real Detroit overview extract; dashboard and map viewer in a browser (fonts, sprites and tiles all served from the Pi); Notes and Files write and delete. Memory stayed at about 750 MB used with those small files. After a real reboot, all five apps, the ZIM and the map came back with no manual steps, within about 40 seconds of boot.

Since then the owner downloaded 11 libraries (14 GB, largest 3.7 GB) and a 1.1 GB detailed Michigan map on the Pi with no failures.

Combined 2026-11-12: the bookshelf, system panel and admin PIN were written on a second PC starting from the original zip, so that line of work lacked every fix and the redesign. They were merged here (three-way against the original zip). All 34 unit tests pass on the Pi inside the command-center image. The combined dashboard, system panel and empty bookshelf were viewed from a temporary preview container on the Pi (port 8090).

Review fixes 2026-11-14 (cross-site POST check, body size cap, no folder listings, checksum verification, installed marks in the Content Manager, zip-bomb cap in the reader, log cap): 43 unit tests pass on the Pi; a real 21 MB ZIM downloaded and verified in an isolated preview; pages exercised in a browser.

**Not yet tested:** `hotspot.sh` (it takes over wlan0, so connect Ethernet first); the 14 GB and 53 GB Wikipedias on 4 GB RAM; the bookshelf with real books; the admin PIN in a browser on the Pi; the fan reading.

## Next work, in order

1. Finish the Pi checks above: hotspot, real books, admin PIN.
2. Meshtastic (researched 2026-11-09, nothing built): MeshMonitor plus its serial bridge for USB radios; open questions are offline map tiles and memory use.
3. Dashboard start/stop buttons (discuss the risk first). The Docker socket is already root-equivalent: `:ro` on a socket does not restrict API calls.
4. Map place search (geocoding); first-run setup wizard; auto-update option.
5. Kolibri: find a maintained arm64 image, test it, then uncomment in `compose.yaml`.
## Working style

- Verify against real sources before claiming something works; say plainly what wasn't tested.
- Keep the command-center dependency-free (stdlib only) unless there is a strong reason.
- Add or update a unit test with every backend change.
- Commits: author them as the repo owner (`redneck3d`, GitHub noreply email). Do not add `Co-Authored-By: Claude` or any other Claude/AI attribution lines to commit messages or pull requests.
