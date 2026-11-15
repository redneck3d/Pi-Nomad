"""The other apps on the deck: are they running, and stop / start / restart them.

This talks to Docker over its socket. That socket can do anything on the Pi, so this module
is deliberately narrow: it only ever touches containers of this compose project, only the
apps named in CONTROLLABLE, and only with the three actions in ACTIONS. The Command
Center itself is not in the list: stopping it would take the buttons away.
"""
import http.client
import json
import os
import socket
import urllib.parse

PROJECT = os.environ.get("COMPOSE_PROJECT", "pi-nomad")
DOCKER_SOCK = os.environ.get("DOCKER_SOCK", "/var/run/docker.sock")
CONTROLLABLE = {"kiwix": "Information Library", "flatnotes": "Notes", "cyberchef": "Data Tools", "files": "Files",
                "kolibri": "Education", "meshmonitor": "Mesh Radio"}
ACTIONS = ("start", "stop", "restart")
STOP_WAIT = 10          # seconds Docker gives an app to shut down cleanly before ending it


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(self.timeout)
        s.connect(self._path)
        self.sock = s


def _docker(method, path, timeout=3):
    """One Docker API call. Returns (status, parsed JSON or None)."""
    conn = _UnixHTTPConnection(DOCKER_SOCK, timeout)
    try:
        conn.request(method, path)
        r = conn.getresponse()
        body = r.read()
        try:
            return r.status, json.loads(body) if body else None
        except ValueError:
            return r.status, None
    finally:
        conn.close()


def _containers():
    flt = json.dumps({"label": [f"com.docker.compose.project={PROJECT}"]})
    status, items = _docker("GET", "/containers/json?all=1&filters=" + urllib.parse.quote(flt))
    if status != 200 or not isinstance(items, list):
        raise OSError("Docker did not answer")
    return {c["Labels"].get("com.docker.compose.service"): c for c in items}


def states():
    """Map compose service name -> container state, or {} if Docker is unreachable."""
    try:
        return {name: c["State"] for name, c in _containers().items()}
    except Exception:
        return {}


def act(service, action):
    """Start, stop or restart one of the apps. Returns its state afterwards."""
    if service not in CONTROLLABLE:
        raise ValueError("That app cannot be started or stopped from here")
    if action not in ACTIONS:
        raise ValueError("Unknown action")
    try:
        found = _containers().get(service)
    except OSError:
        raise ValueError("Docker is not answering, so the app could not be changed") from None
    if not found:
        raise ValueError(f"{CONTROLLABLE[service]} is not installed")
    path = f"/containers/{found['Id']}/{action}" + ("" if action == "start" else f"?t={STOP_WAIT}")
    try:
        status, body = _docker("POST", path, timeout=STOP_WAIT + 20)
    except OSError:
        raise ValueError(f"{CONTROLLABLE[service]} did not respond in time") from None
    if status not in (204, 304):                 # 304 = it was already in that state
        why = body.get("message") if isinstance(body, dict) else ""
        raise ValueError(f"Docker refused to {action} {CONTROLLABLE[service]}" + (f": {why}" if why else ""))
    return {"ok": True, "service": service, "state": states().get(service, "unknown")}
