"""Shut down or restart the Pi from the dashboard, so nobody has to pull the plug.

The app cannot turn the Pi off by itself: it runs in a container. install.sh puts a small
helper on the Pi (a systemd path unit) that watches one file. Writing "poweroff" or "reboot"
into that file is all this module does, and those two words are all the helper understands,
so this adds no other control over the Pi.
"""
import os

import jobs

POWER_DIR = os.environ.get("POWER_DIR", "/power")
ACTIONS = {"poweroff": "Shutting down", "reboot": "Restarting"}


def available():
    """True once install.sh has put the helper in place (it leaves a marker file)."""
    return os.path.isfile(os.path.join(POWER_DIR, "helper-installed")) and os.access(POWER_DIR, os.W_OK)


def busy():
    """Titles of downloads, extracts or backups that a shutdown would cut off."""
    return [j["title"] for j in jobs.snapshot() if j["state"] in ("running", "queued")]


def status():
    return {"available": available(), "busy": busy()}


def request(action):
    if action not in ACTIONS:
        raise ValueError("Unknown power action")
    if not available():
        raise ValueError("Shut down and restart are not set up on this Pi. Run install.sh again.")
    with open(os.path.join(POWER_DIR, "request"), "w") as f:
        f.write(action + "\n")
    return {"ok": True, "action": action, "message": ACTIONS[action]}
