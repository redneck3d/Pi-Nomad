# What has been tested

Pi-NOMAD is checked on real hardware before changes go in. This page says what has been tried and, just as important, what hasn't.

## Hardware it has run on

| Machine | Storage | Result |
|---|---|---|
| Raspberry Pi 5, 4 GB | 128 GB SD card, then a 256 GB NVMe SSD | Main test machine. Everything below unless noted. |
| Raspberry Pi 400, 4 GB | 128 GB SD card | Full install, stress test and hotspot. |
| PC with Docker Desktop (amd64) | Linux filesystem | Early full-stack tests; the dashboard image also built and ran as arm64 under emulation. |

Raspberry Pi OS 64-bit (Debian 13 "trixie") on both Pis. A Pi 4 with 4 GB or more has the same chip as the Pi 400 and should behave the same, but hasn't been tried.

## Tested and working

- **Install and restart:** `install.sh` on a Pi 5 and a Pi 400; after a real power-off restart, every app came back on its own within about 40 seconds.
- **Libraries:** 20 real libraries downloaded, including the 53 GB full-text Wikipedia (about 27 minutes on home Wi-Fi to an SSD; the connection dropped once and the download resumed by itself; checksum matched). Cancel and delete work. A full-text search of the 53 GB Wikipedia took 0.24 seconds.
- **Search:** across 20 libraries, notes and books.
- **Maps:** real Detroit and Michigan extracts; fonts, icons and labels all served from the Pi with no internet. Place search, including streets.
- **Bookshelf:** 30 real EPUB and PDF books.
- **Notes and Files:** saving, uploading and deleting.
- **Admin PIN, Backup** (to a real exFAT USB stick, matched byte for byte) and the **Shut down / Restart** buttons.
- **Mesh Radio:** a Heltec V4 radio over USB; messages, node list and radios on the offline map.
- **Comms tools:** every Morse character converts both ways; FRS/GMRS channels checked against the FCC table.
- **Hotspot:** an iPhone joined and every app opened on `10.42.0.1`; the hotspot came back by itself after a restart (Pi 400).
- **Moving to an SSD:** a Pi 5 moved from its SD card to an NVMe SSD with `tools/move-to-ssd.sh` and booted from it.
- **Unit tests:** 73 backend tests, run on the Pi:

  ```bash
  cd command-center && python3 tests/test_backend.py
  ```

## Stress test (Pi 400, SD card)

Eight minutes with all four processor cores flat out, 1.5 GB of memory held, a 2 GB card write and read, and eight people searching at the same time.

- Peak temperature 53 °C, no slowdown from heat, no low-voltage warnings, no app restarts, no errors.
- Card speed: 24 MB/s writing, 46 MB/s reading, the same under load.
- Search: 0.23 s for one person; 1.8 s typical (5 s worst) with eight at once under full load. None of 990 requests failed.

## Not tested yet

- A clean install from a blank card on a Pi 400 (it was tested as an upgrade).
- A Raspberry Pi 4, or any Pi with less than 4 GB of memory.
- Several people using the 53 GB Wikipedia for a long time, or a run of hours inside a closed case.
- Mesh Radio with a GPS module, sending from the deck for long periods, and unplugging the radio mid-use.
- Kolibri lessons (Kolibri installs and runs; importing courses hasn't been tried).
- The emergency phrase translations have not been checked by a native speaker.

Found something that doesn't work? Please [open an issue](https://github.com/redneck3d/Pi-Nomad/issues).
