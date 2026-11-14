# Pi-NOMAD

An offline-first knowledge server for a Raspberry Pi 5, modeled on [Project NOMAD](https://github.com/Crosstalk-Solutions/project-nomad) without the AI stack.

## Feature map

| NOMAD feature | Pi-NOMAD | Status |
|---|---|---|
| Information Library (Kiwix) | `kiwix` | Working config |
| Notes (FlatNotes) | `flatnotes` | Working config |
| Data tools (CyberChef) | `cyberchef` | Working config |
| Supply Depot / file tools | `files` ([Dufs](https://github.com/sigoden/dufs)) | Working config |
| Offline maps (ProtoMaps) | Viewer at `/maps/`, region manager at `/maps/manage.html` | Tested in Docker |
| Content downloads (ZIM manager) | `/zim.html`: collections, catalog search, resumable downloads, delete | Tested in Docker |
| Education (Kolibri) | `kolibri`, built from the Kolibri Python package (no current upstream image) | Installed and running on the Pi; lesson import not yet tried |
| Your own books (not in NOMAD) | Bookshelf at `/books/`: lists EPUB and PDF files from `/srv/nomad/books`, built-in EPUB reader | Tested on the Pi with 30 real books |
| System info | System panel on the dashboard: temperature, fan, processor, memory, uptime, drive writes, clock check, power and heat warnings | Checked on the real Pi except the fan reading (no fan fitted) |
| Admin lock (not in NOMAD) | Optional admin PIN: reading stays open, downloads, deletes, backup and power need the PIN | Tested on the Pi |
| Command Center (dashboard) | `command-center` (Python, no deps) | Done: tiles, live status, storage, content and map managers, app start/stop |
| Setup wizard + content collections | `install.sh` + Content Manager collections | Collections done; no first-run wizard yet |
| Auto updates | none | Phase 3 (Watchtower or cron) |
| Benchmark | none | Optional |
| AI chat + RAG | dropped on purpose | n/a |

Added for the cyberdeck: `hotspot.sh` makes the Pi its own Wi-Fi network, so it works with no internet.

## Install (on the Pi)

Needs Raspberry Pi OS 64-bit. Content lives in `/srv/nomad` on the SD card (see Storage below).

    sudo ./install.sh
    sudo ./hotspot.sh            # optional: makes the Pi its own Wi-Fi network; asks you for a password
    sudo ./hotspot.sh off        # back to the normal Wi-Fi

Then open `http://<pi>.local/`, or `http://10.42.0.1/` when you are joined to the hotspot.

The hotspot takes over the Pi's Wi-Fi, so start it over Ethernet or with a screen and keyboard. It comes back by itself after a restart.

## Storage (128GB SD card)

The card has about 96GB free after install. All 7 collections together come to about 99GB, so they won't all fit. Pick one Wikipedia: every other collection plus the 53GB full text comes to about 85GB. The 127GB Wikipedia with images doesn't fit. The workload is mostly reads, which SD cards handle well. Things to do:

- Buy a high-endurance or A2-rated card from a known brand; fakes are common at this size.
- Keep it read-mostly: Docker logs were the main steady writer, so `compose.yaml` caps them at 15 MB per app.
- Back up your notes and books off the card now and then with the Backup page, since SD cards fail without warning.
- If you outgrow it, mount a USB SSD at `/srv/nomad` and nothing else changes.
- The dashboard's Storage panel shows free space and what is using it.

## How content and maps work

- **ZIM manager:** searches the Kiwix catalog, downloads into `/srv/nomad/zim` (resumes if Wi-Fi drops, one download at a time, refuses if the card would fill up), checks each file against the checksum Kiwix publishes, and adds the file to `library.xml` itself. Kiwix reloads that file automatically.
- **Files app:** browse, upload and delete anything on the data drive. After adding or deleting a ZIM there, press **Rescan folder** in the Content Manager. A note uploaded there can't be edited in Notes until the `flatnotes` container restarts.
- **Maps:** the Protomaps planet file is far too big for the card, so the manager cuts out just your region with the `pmtiles extract` tool. The viewer (MapLibre) and Protomaps' fonts and icons are bundled into the Docker image, so maps work with no internet. You can also drop any `.pmtiles` file into `/srv/nomad/maps`.

## Starting and stopping apps

The Apps panel on the dashboard can stop, start or restart the Library, Notes, Data Tools and Files. A stopped app stays off, even after the deck restarts, until you press Start. The dashboard itself has no stop button. If an admin PIN is set, these buttons need it.

## Shut down and restart

The dashboard has Restart and Shut down buttons under the system readings. Use Shut down before cutting power so the memory card is not damaged. After a shut down the Pi stays off until you press its power button or reconnect power. The installer adds a small helper to the Pi that makes this possible; it can only do those two things.

## Search

The search box on the dashboard looks through every library, your notes and your book titles at once. Library results come from Kiwix, so anything you install is searchable straight away. The text inside your own books is not searched, only titles and authors.

## Education (Kolibri)

The Education tile opens Kolibri, an offline learning platform with courses such as Khan Academy. It has its own accounts: the first time you open it, it walks you through a short setup and has you create an admin user. Lessons are added from inside Kolibri, by download while you have internet or from a USB drive, and they are large (tens of GB for all of Khan Academy), so pick subjects. It opens in its own browser tab because it does not allow being shown under the Pi-Nomad bar. Its data lives in `/srv/nomad/kolibri` and is not part of the USB backup.

## Finding places on the map

The map has a search box for towns, streets, highways, parks, lakes and other named places. It works with no internet: the names come out of the map file you already downloaded. After a region is saved the deck reads its names once (about a minute for all of Michigan in full detail), and maps saved earlier are read the next time the deck starts. Streets are listed nearest-first with the town they are in, and the usual short forms work (`main st`, `mt clemens`, `telegraph rd`). There are no house numbers, so it finds the street, not the address.

## Backup

The Backup page copies your notes and books to a USB drive plugged into the Pi, into a dated folder inside `pi-nomad-backup`. It can also download your notes as a zip to the phone or PC you are using. Libraries and maps are not copied because they can be downloaded again; every backup includes `installed-content.txt`, a list of them. To restore, upload the `notes` and `books` folders back through the Files app, then press Restart on the dashboard (restored notes can be read but not edited until the Notes app restarts). USB drives are found through the Pi desktop, which mounts them automatically while it is logged in.

## Bookshelf

Put EPUB and PDF files in `/srv/nomad/books` (subfolders are fine) and they appear at `/books/`. EPUBs open in a built-in reader (chapter list, text size, light/sepia/dark, remembers your place per device). PDFs open in the browser's own viewer. Covers come from inside the EPUB, or from a JPG/PNG with the same name as the book, anywhere in the books folder (a `Covers` subfolder works; punctuation differences are ignored). Scripts inside books are blocked. EPUBs with DRM will not open.

To add books: upload them into the `books` folder with the Files app, or `sudo cp -r /path/to/books/* /srv/nomad/books/` on the Pi.

## Admin PIN

Set a PIN from the banner at the top of the dashboard. After that, anyone on the network can still read everything, but downloading, deleting and other changes ask for the PIN. An unlocked device stays unlocked for 12 hours or until you press Lock. Five wrong tries cause a pause that grows with each further try.

- Forgot it: `docker compose exec command-center python auth.py reset`, then set a new one.
- The PIN is stored only as a salted hash in its own Docker volume (`nomad-config`).
- **It does not cover the other apps.** Files (port 8083) has no login and can still change or delete anything under `/srv/nomad`, and Notes is open to everyone.
- Traffic is plain HTTP, so the PIN is only as private as your Wi-Fi password.

## What has been verified (2026-11-08)

Unit tests (`cd command-center && python3 tests/test_backend.py`) cover resuming a dropped download, path-traversal checks, Range requests and library writing. The map viewer was loaded in real Chrome against a generated test map. The live services were then checked from a real browser:

- **Kiwix catalog:** the real feed format is parsed (the parser test uses an entry copied from the live catalog). The catalog moved to `opds.library.kiwix.org`, and download links use `lb.download.kiwix.org`; both are handled. Kiwix publishes variants (nopic, mini, maxi) under one name, so presets pick a flavour. All 7 collections resolve against the live catalog with the sizes shown in their descriptions.
- **library.xml:** the attributes written match what libkiwix 14.2.1 (used by kiwix-tools 3.8.2) reads. The next libkiwix, currently unreleased, switches this file to a different format, so the compose file pins `kiwix-serve:3.8.2`. Don't change that tag without re-checking.
- **Protomaps:** the `build.protomaps.com/YYYYMMDD.pmtiles` URL pattern is right (the newest build is probed first, then older ones). The `pmtiles extract` flags (`--bbox`, `--maxzoom`, `--dry-run`) exist in the CLI source. The font and icon repo layout matches the Dockerfile, and the builds are compatible with `@protomaps/basemaps` 4 and 5 (the image uses 5).

## Verified in Docker (2026-11-09)

The full stack was run on a PC with Docker Desktop (amd64), with the data on a root-owned Linux filesystem like the Pi's. Real ZIM downloads, resume (the checksum matched), cancel and delete all worked, and `kiwix-serve` listed, opened and dropped books from the `library.xml` we write. A real Detroit map extract rendered in a headless browser with labels and icons and no internet requests. Notes and Files can both write. The Command Center image also builds and runs a real extract as arm64 under emulation, and the other four images publish arm64 builds. Unit tests: 19.

## Verified on the Pi (2026-11-09)

On a Raspberry Pi 5 (4 GB, Debian 13 trixie), `install.sh` installed Docker and started all five apps as arm64. A real ZIM download opened in Kiwix, a real Detroit map rendered in a browser from the Pi, and Notes and Files could both save and delete. After a real reboot, everything came back on its own within about 40 seconds. Eleven libraries (14 GB, the largest 3.7 GB) and a 1.1 GB detailed Michigan map then downloaded cleanly.

## Combined version (2026-11-12)

The bookshelf, system panel and admin PIN were written on a second PC from the original files, then combined with the fixes and the redesign above. All 34 unit tests pass on the Pi, and the combined dashboard, system panel and bookshelf page were opened in a browser from a preview on the Pi. The system panel's temperature, memory, uptime and low-voltage readings match the Pi's own. This Pi's kernel has no `get_throttled` file, so only the low-voltage alarm is available, and no fan is fitted, so the fan reading is unchecked.

## Added and verified on the Pi (2026-11-14)

Review fixes, Backup, Search, and the Shut down and Restart buttons were each tested on the Pi before going live: 57 unit tests pass, a real download was checksum-verified, a backup was written to a real exFAT USB stick and matched byte for byte, search ran against 11 real libraries, and both power buttons were pressed for real.

## Still not tested

- **Biggest content:** files up to 3.7 GB work; the 14 GB and 53 GB Wikipedias are untried on 4 GB of RAM.
- **Fan speed** on the system panel (needs a Pi fan fitted).

## Next steps

1. Confirm the hotspot comes back by itself after a restart.
2. Add Kolibri accounts and progress to the backup.
3. Tell the owner when newer libraries or maps are available.
4. Meshtastic radios (waiting on hardware).

## Notes

- The admin PIN is a light lock for a private network, not real security. Keep the deck on the hotspot/LAN, not the open internet.
- On 4GB RAM, skip full Wikipedia with images in memory-heavy use and prefer the nopic builds.
