"""Admin PIN: protects the actions that change the deck (downloads, deletes), not reading.

- No PIN set: everything is open, as before, and the dashboard says so.
- PIN set: changing things needs an unlocked session (a cookie that lasts SESSION_HOURS).
- The PIN is stored only as a salted PBKDF2 hash in CONFIG_DIR/admin.json. CONFIG_DIR is a
  Docker volume of its own, so the Files app (which shows /srv/nomad) cannot read or delete it.
- Forgot the PIN?  docker compose exec command-center python auth.py reset
"""
import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
import time

CONFIG_DIR = os.environ.get("CONFIG_DIR", "/config")
SESSION_HOURS = 12
MAX_FAILS = 5            # wrong tries allowed before a pause
LOCKOUT = 30             # seconds; doubles with each further wrong try, up to 15 minutes
ITERATIONS = 200_000
MIN_LEN, MAX_LEN = 4, 64

_sessions = {}           # token -> expiry time (kept in memory: a restart locks everyone again)
_fails = {"count": 0, "until": 0.0}
_lock = threading.Lock()


class TooManyAttempts(Exception):
    def __init__(self, wait):
        super().__init__(f"Too many wrong tries. Wait {int(wait) + 1} seconds.")
        self.wait = wait


def _file():
    return os.path.join(CONFIG_DIR, "admin.json")


def _load():
    try:
        with open(_file()) as f:
            d = json.load(f)
        bytes.fromhex(d["salt"]), bytes.fromhex(d["hash"]), int(d["iterations"])
        return d
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _hash(pin, salt, iterations):
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, iterations)


def pin_set():
    return _load() is not None


def set_pin(pin):
    if not isinstance(pin, str) or not MIN_LEN <= len(pin) <= MAX_LEN:
        raise ValueError(f"The PIN must be {MIN_LEN} to {MAX_LEN} characters long")
    salt = secrets.token_bytes(16)
    data = {"salt": salt.hex(), "hash": _hash(pin, salt, ITERATIONS).hex(), "iterations": ITERATIONS}
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = _file() + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, _file())
    with _lock:
        _sessions.clear()                # a new PIN signs every device out
        _fails.update(count=0, until=0.0)


def clear_pin():
    try:
        os.remove(_file())
    except FileNotFoundError:
        pass
    with _lock:
        _sessions.clear()
        _fails.update(count=0, until=0.0)


def verify(pin):
    """True if the PIN is right. Raises TooManyAttempts while paused after repeated wrong tries."""
    d = _load()
    if d is None:
        return False
    with _lock:
        wait = _fails["until"] - time.time()
        if wait > 0:
            raise TooManyAttempts(wait)
    ok = isinstance(pin, str) and len(pin) <= MAX_LEN and hmac.compare_digest(
        _hash(pin, bytes.fromhex(d["salt"]), int(d["iterations"])), bytes.fromhex(d["hash"]))
    with _lock:
        if ok:
            _fails.update(count=0, until=0.0)
        else:
            _fails["count"] += 1
            over = _fails["count"] - MAX_FAILS
            if over >= 0:
                _fails["until"] = time.time() + min(900, LOCKOUT * 2 ** over)
    return ok


def new_session():
    token = secrets.token_urlsafe(32)
    with _lock:
        now = time.time()
        for t in [t for t, exp in _sessions.items() if exp < now]:
            del _sessions[t]
        _sessions[token] = now + SESSION_HOURS * 3600
    return token


def valid(token):
    with _lock:
        return bool(token) and _sessions.get(token, 0) > time.time()


def end_session(token):
    with _lock:
        _sessions.pop(token, None)


def allowed(token):
    """May this request change things? Yes if no PIN is set, or the session is unlocked."""
    return not pin_set() or valid(token)


if __name__ == "__main__":
    if sys.argv[1:] == ["reset"]:
        clear_pin()
        print("Admin PIN removed. Set a new one from the dashboard.")
    else:
        print("usage: python auth.py reset")
