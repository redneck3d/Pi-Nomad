"""Mesh radios for the offline map.

MeshMonitor (the Mesh Radio app) keeps every radio it has heard in a SQLite file under
/srv/nomad/mesh. Its own map needs internet, so the deck's map shows them instead. This
module only ever reads that file, through the read-only data mount, and only the handful of
columns below: if a MeshMonitor update renames them, the map says so instead of failing.
"""
import os
import sqlite3

DATA = os.environ.get("NOMAD_DATA", "/data")
MAX_NODES = 2000


def db_path():
    return os.path.join(DATA, "mesh", "meshmonitor.db")


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def nodes():
    """Radios with a known position. {"available": False} when Mesh Radio has no data yet."""
    path = db_path()
    if not os.path.isfile(path):
        return {"available": False, "nodes": [], "total": 0}
    try:
        con = sqlite3.connect("file:" + path + "?mode=ro", uri=True, timeout=2)
        try:
            con.row_factory = sqlite3.Row
            have = {r["name"] for r in con.execute("pragma table_info(nodes)")}
            if not {"nodeId", "latitude", "longitude"} <= have:
                raise sqlite3.Error("the node table is not laid out as expected")
            rows = con.execute("select * from nodes order by lastHeard desc limit ?"
                               if "lastHeard" in have else "select * from nodes limit ?", (MAX_NODES,)).fetchall()
        finally:
            con.close()
    except sqlite3.Error as e:
        return {"available": False, "nodes": [], "total": 0, "error": f"Could not read the mesh radio list: {e}"}

    out = []
    for r in rows:
        get = lambda k: r[k] if k in have else None          # noqa: E731
        if get("hideFromMap") or get("isIgnored"):
            continue
        lat, lon = _num(get("latitude")), _num(get("longitude"))
        if get("positionOverrideEnabled") and _num(get("latitudeOverride")) is not None \
                and _num(get("longitudeOverride")) is not None:   # a position the owner typed in by hand
            lat, lon = get("latitudeOverride"), get("longitudeOverride")
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
            continue
        out.append({
            "id": str(get("nodeId") or ""),
            "name": str(get("longName") or get("shortName") or get("nodeId") or "Unnamed radio")[:60],
            "short": str(get("shortName") or "")[:8],
            "lat": round(lat, 6), "lon": round(lon, 6),
            "alt": _num(get("altitude")),
            "heard": _num(get("lastHeard")),                # seconds, by the radio's own clock
            "hops": _num(get("hopsAway")),
            "snr": _num(get("snr")),
            "battery": _num(get("batteryLevel")),
            "internet": bool(get("viaMqtt")),               # heard through an internet relay, not by radio
        })
    return {"available": True, "nodes": out, "total": len(rows)}
