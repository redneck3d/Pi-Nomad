"""Place search for the offline maps: find a town, street or landmark by name.

The names are already inside the map files. A .pmtiles file holds vector tiles, and each tile
carries the names of the places, roads and points of interest it draws. So nothing extra is
downloaded: after a region is saved we read its tiles once, pull the names out, and keep them
in a small SQLite file beside the map (<map>.places.db).

Everything here is standard library: a PMTiles v3 reader (header, directories, Hilbert tile
ids) and just enough of a Mapbox Vector Tile (protobuf) decoder to read names and one point
per feature. Formats: https://github.com/protomaps/PMTiles/blob/main/spec/v3/spec.md and
https://github.com/mapbox/vector-tile-spec (layer names are the Protomaps basemap's).
"""
import gzip
import math
import os
import re
import sqlite3
import struct
import unicodedata

MAPS_DIR = os.environ.get("MAPS_DIR", "/data/maps")
DB_VERSION = 2
# Layer -> the kinds worth finding. None = every kind in that layer.
PLACE_ZOOM = 12        # towns and neighbourhoods are all present by here
DETAIL_ZOOM = 14       # street names and points of interest
GRID = 0.01            # degrees (about 1 km): one entry per street name per grid square


# ---------- PMTiles v3 ----------

def _varint(buf, pos):
    result = shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7


def read_header(f):
    f.seek(0)
    h = f.read(127)
    if len(h) < 127 or h[:7] != b"PMTiles" or h[7] != 3:
        raise ValueError("not a PMTiles version 3 file")
    (root_off, root_len, _meta_off, _meta_len, leaf_off, _leaf_len, data_off, _data_len) = struct.unpack_from("<8Q", h, 8)
    min_lon, min_lat, max_lon, max_lat = (v / 1e7 for v in struct.unpack_from("<4i", h, 102))
    return {"root": (root_off, root_len), "leaf_off": leaf_off, "data_off": data_off,
            "internal_compression": h[97], "tile_compression": h[98], "tile_type": h[99],
            "min_zoom": h[100], "max_zoom": h[101], "bounds": (min_lon, min_lat, max_lon, max_lat)}


def _unpack(data, compression):
    if compression == 2:
        return gzip.decompress(data)
    if compression in (0, 1):
        return data
    raise ValueError("this map uses a compression this deck cannot read")


def _read_dir(f, offset, length, compression):
    """One directory as a list of (tile_id, run_length, offset, length)."""
    f.seek(offset)
    buf = _unpack(f.read(length), compression)
    n, pos = _varint(buf, 0)
    ids, runs, lens, offs = [], [], [], []
    last = 0
    for _ in range(n):
        d, pos = _varint(buf, pos)
        last += d
        ids.append(last)
    for _ in range(n):
        v, pos = _varint(buf, pos)
        runs.append(v)
    for _ in range(n):
        v, pos = _varint(buf, pos)
        lens.append(v)
    for i in range(n):
        v, pos = _varint(buf, pos)
        offs.append(offs[i - 1] + lens[i - 1] if v == 0 and i > 0 else v - 1)
    return list(zip(ids, runs, offs, lens))


def _zoom_base(z):
    return (4 ** z - 1) // 3


def tile_xy(z, tile_id):
    """Hilbert position within a zoom level -> (x, y)."""
    d = tile_id - _zoom_base(z)
    x = y = 0
    s = 1
    n = 1 << z
    while s < n:
        rx = 1 & (d >> 1)
        ry = 1 & (d ^ rx)
        if ry == 0:
            if rx == 1:
                x, y = s - 1 - x, s - 1 - y
            x, y = y, x
        x += s * rx
        y += s * ry
        d >>= 2
        s <<= 1
    return x, y


def iter_tiles(f, header, zoom):
    """Yield (x, y, raw tile bytes) for every distinct tile at one zoom level."""
    lo, hi = _zoom_base(zoom), _zoom_base(zoom + 1)
    comp = header["internal_compression"]
    seen = set()

    def walk(offset, length):
        entries = _read_dir(f, offset, length, comp)
        for i, (tid, run, off, ln) in enumerate(entries):
            if run == 0:                                   # a leaf directory covering ids from tid on
                nxt = entries[i + 1][0] if i + 1 < len(entries) else None
                if tid < hi and (nxt is None or nxt > lo):
                    yield from walk(header["leaf_off"] + off, ln)
            elif tid < hi and tid + run > lo and off not in seen:
                seen.add(off)                              # identical tiles (open water) are stored once
                first = max(tid, lo)
                f.seek(header["data_off"] + off)
                yield (*tile_xy(zoom, first), f.read(ln))

    yield from walk(*header["root"])


# ---------- vector tiles ----------

def _fields(buf, pos, end):
    """Walk protobuf fields: yields (field number, wire type, value or (start, end))."""
    while pos < end:
        key, pos = _varint(buf, pos)
        wire = key & 7
        if wire == 0:
            val, pos = _varint(buf, pos)
        elif wire == 2:
            ln, pos = _varint(buf, pos)
            val = (pos, pos + ln)
            pos += ln
        elif wire == 5:
            val = None
            pos += 4
        elif wire == 1:
            val = None
            pos += 8
        else:
            raise ValueError("bad tile data")
        yield key >> 3, wire, val


def _value(buf, start, end):
    for num, wire, val in _fields(buf, start, end):
        if num == 1:
            return buf[val[0]:val[1]].decode("utf-8", "replace")
        if wire == 0:
            return val
    return None


def _mid_point(buf, start, end, is_point):
    """A representative point of a geometry in tile units: the point itself, or the middle of the first line."""
    pos, x, y, pts = start, 0, 0, []
    while pos < end:
        cmd, pos = _varint(buf, pos)
        op, count = cmd & 7, cmd >> 3
        if op == 7:
            continue
        if op == 1 and pts:                    # a second part starts: the first is enough
            break
        for _ in range(count):
            dx, pos = _varint(buf, pos)
            dy, pos = _varint(buf, pos)
            x += (dx >> 1) ^ -(dx & 1)
            y += (dy >> 1) ^ -(dy & 1)
            pts.append((x, y))
        if is_point:
            break
    return pts[len(pts) // 2] if pts else None


def tile_features(data, wanted):
    """Yield (layer, props, x, y, extent) for named features in the wanted layers.

    props holds only the keys we use. x and y are in tile units (0..extent).
    """
    buf = data
    for num, wire, val in _fields(buf, 0, len(buf)):
        if num != 3 or wire != 2:
            continue
        ls, le = val
        name, keys, values, feats, extent = None, [], [], [], 4096
        for n2, w2, v2 in _fields(buf, ls, le):
            if n2 == 1:
                name = buf[v2[0]:v2[1]].decode("utf-8", "replace")
                if name not in wanted:
                    break
            elif n2 == 2:
                feats.append(v2)
            elif n2 == 3:
                keys.append(buf[v2[0]:v2[1]].decode("utf-8", "replace"))
            elif n2 == 4:
                values.append(v2)
            elif n2 == 5:
                extent = v2
        if name not in wanted:
            continue
        want_keys = {i for i, k in enumerate(keys) if k in ("name", "name:en", "kind", "kind_detail", "ref", "population_rank", "min_zoom")}
        if not any(keys[i] in ("name", "name:en", "ref") for i in want_keys):
            continue
        for fs, fe in feats:
            tags = geom = None
            gtype = 0
            for n3, w3, v3 in _fields(buf, fs, fe):
                if n3 == 2:
                    tags = v3
                elif n3 == 3:
                    gtype = v3
                elif n3 == 4:
                    geom = v3
            if not tags or not geom:
                continue
            props, pos = {}, tags[0]
            while pos < tags[1]:
                k, pos = _varint(buf, pos)
                v, pos = _varint(buf, pos)
                if k in want_keys:
                    props[keys[k]] = _value(buf, *values[v])
            if not (props.get("name") or props.get("name:en") or props.get("ref")):
                continue
            pt = _mid_point(buf, geom[0], geom[1], gtype == 1)
            if pt:
                yield name, props, pt[0], pt[1], extent


def to_lonlat(z, tx, ty, px, py, extent):
    n = 1 << z
    lon = (tx + px / extent) / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ty + py / extent) / n))))
    return lon, lat


def fold(text):
    """Lower-case, accents removed, punctuation to spaces: 'Saint-Étienne' -> 'saint etienne'."""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


# ---------- building the index ----------

SKIP_ROADS = {"aeroway", "rail", "ferry", "pier", "runway", "taxiway"}
SKIP_POIS = {"administrative"}                 # township and county labels: the places layer already has the towns
LABELS = {"city": "City", "town": "City", "village": "Village", "hamlet": "Community", "locality": "Place", "farm": "Farm",
          "suburb": "Neighborhood", "quarter": "Neighborhood", "neighbourhood": "Neighborhood", "macrohood": "Neighborhood",
          "highway": "Highway", "major_road": "Road", "minor_road": "Road", "path": "Trail", "water": "Lake",
          "lake": "Lake", "river": "River", "stream": "Stream", "canal": "Canal", "bay": "Bay", "ocean": "Water", "sea": "Water"}
TOWN_SCORE = {"city": 80, "town": 70, "village": 60}     # real towns: listed first, and used for "near ..."
TOWN = 60                                                # score at or above this = a real town
BIG_POIS = {"national_park", "forest", "nature_reserve", "protected_area", "aerodrome", "university", "military"}


def db_path(pmtiles_path):
    return pmtiles_path[:-len(".pmtiles")] + ".places.db"


def _stamp(pmtiles_path):
    st = os.stat(pmtiles_path)
    return f"{DB_VERSION}:{st.st_size}:{int(st.st_mtime)}"


def is_current(pmtiles_path):
    """True if this map already has an up-to-date place index."""
    try:
        con = sqlite3.connect(f"file:{db_path(pmtiles_path)}?mode=ro", uri=True)
        try:
            row = con.execute("SELECT value FROM meta WHERE key='stamp'").fetchone()
        finally:
            con.close()
        return bool(row) and row[0] == _stamp(pmtiles_path)
    except (sqlite3.Error, OSError):
        return False


def _label(layer, kind, detail=""):
    return LABELS.get(detail) or LABELS.get(kind) or (kind or layer).replace("_", " ").capitalize()


class _Towns:
    """Nearest-town lookup, so 'Main Street' can say which Main Street it is."""
    CELL = 0.1

    def __init__(self):
        self.grid = {}

    def add(self, name, lon, lat):
        self.grid.setdefault((int(lon // self.CELL), int(lat // self.CELL)), []).append((lon, lat, name))

    def near(self, lon, lat):
        cx, cy = int(lon // self.CELL), int(lat // self.CELL)
        best, best_d = "", 0.2 ** 2          # nothing farther than about 20 km counts as "near"
        k = math.cos(math.radians(lat)) ** 2
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for tlon, tlat, name in self.grid.get((gx, gy), ()):
                    d = (tlon - lon) ** 2 * k + (tlat - lat) ** 2
                    if d < best_d:
                        best, best_d = name, d
        return best


def build_index(pmtiles_path, job=None):
    """Read a map's tiles once and write <map>.places.db. Returns the number of places kept."""
    out = db_path(pmtiles_path)
    tmp = out + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    con = sqlite3.connect(tmp)
    try:
        con.executescript("""
            PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
            CREATE TABLE places (name TEXT, fold TEXT, hay TEXT, label TEXT, layer TEXT, lon REAL, lat REAL,
                                 near TEXT, score INTEGER, cx INTEGER, cy INTEGER,
                                 UNIQUE (fold, layer, cx, cy) ON CONFLICT IGNORE);
            CREATE TABLE words (word TEXT, id INTEGER);
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);""")
        towns = _Towns()
        with open(pmtiles_path, "rb") as f:
            h = read_header(f)
            if h["tile_type"] != 1:
                raise ValueError("this map has no names to search (not a vector map)")
            passes = [(min(h["max_zoom"], PLACE_ZOOM), {"places"}),
                      (min(h["max_zoom"], DETAIL_ZOOM), {"roads", "pois", "water"})]
            for n_pass, (zoom, layers) in enumerate(passes):
                batch, done = [], 0
                for x, y, raw in iter_tiles(f, h, zoom):
                    if job is not None and job.cancel.is_set():
                        raise InterruptedError
                    done += 1
                    if job is not None and done % 500 == 0:
                        what = "towns" if n_pass == 0 else "streets and landmarks"
                        job.message = f"Reading place names ({what}, {done:,} map tiles)"
                    try:
                        tile = _unpack(raw, h["tile_compression"])
                        feats = list(tile_features(tile, layers))
                    except (ValueError, IndexError, OSError, EOFError):
                        continue                              # one damaged tile must not stop the rest
                    for layer, p, px, py, extent in feats:
                        if not (0 <= px <= extent and 0 <= py <= extent):
                            continue                          # in the overlap margin: the neighbouring tile has it
                        kind = p.get("kind") or ""
                        if (layer == "roads" and kind in SKIP_ROADS) or (layer == "pois" and kind in SKIP_POIS):
                            continue
                        name = p.get("name:en") or p.get("name") or ""
                        ref = p.get("ref") or ""
                        if layer == "roads" and kind == "highway" and ref:
                            name = name or str(ref)
                        if not name or not isinstance(name, str):
                            continue
                        fold_name = fold(name)
                        if len(fold_name) < 2:
                            continue
                        lon, lat = to_lonlat(zoom, x, y, px, py, extent)
                        detail = p.get("kind_detail") or ""
                        if layer == "places":
                            score = TOWN_SCORE.get(detail, 30)
                            if score >= TOWN:
                                towns.add(name, lon, lat)
                                try:
                                    score += min(9, int(p.get("population_rank") or 0) // 3)
                                except (TypeError, ValueError):
                                    pass
                            near, grid = "", GRID
                        else:
                            near = towns.near(lon, lat)
                            score, grid = ((25, 0.1) if kind == "highway" else (10, 0.02) if layer == "roads"
                                           else (22, GRID) if kind in BIG_POIS else (20, GRID))
                        extra = f" {fold(ref)}" if ref and layer == "roads" else ""
                        batch.append((name, fold_name, f"{fold_name}{extra} | {fold(near)}", _label(layer, kind, detail), layer,
                                      round(lon, 5), round(lat, 5), near, score, int(lon // grid), int(lat // grid)))
                    if len(batch) >= 5000:
                        con.executemany("INSERT INTO places VALUES (?,?,?,?,?,?,?,?,?,?,?)", batch)
                        batch = []
                con.executemany("INSERT INTO places VALUES (?,?,?,?,?,?,?,?,?,?,?)", batch)
        if job is not None:
            job.message = "Sorting the place names"
        batch = []
        for rowid, folded in con.execute("SELECT rowid, fold FROM places").fetchall():
            batch += [(w, rowid) for w in set(folded.split())]
            if len(batch) >= 20000:
                con.executemany("INSERT INTO words VALUES (?,?)", batch)
                batch = []
        con.executemany("INSERT INTO words VALUES (?,?)", batch)
        con.execute("CREATE INDEX words_word ON words (word)")
        count = con.execute("SELECT COUNT(*) FROM places").fetchone()[0]
        con.executemany("INSERT INTO meta VALUES (?,?)", [("stamp", _stamp(pmtiles_path)), ("count", str(count))])
        con.commit()
    except BaseException:
        con.close()
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    con.close()
    os.replace(tmp, out)
    return count


def remove_index(pmtiles_path):
    for p in (db_path(pmtiles_path), db_path(pmtiles_path) + ".tmp"):
        try:
            os.remove(p)
        except OSError:
            pass


# ---------- searching ----------

# What people type -> what the map calls it.
SHORT = {"rd": ["road"], "st": ["street", "saint"], "ave": ["avenue"], "av": ["avenue"], "blvd": ["boulevard"],
         "dr": ["drive"], "ln": ["lane"], "ct": ["court"], "hwy": ["highway"], "pkwy": ["parkway"], "pl": ["place"],
         "ter": ["terrace"], "cir": ["circle"], "trl": ["trail"], "mt": ["mount"], "ft": ["fort"],
         "n": ["north"], "s": ["south"], "e": ["east"], "w": ["west"]}
ZOOMS = {"City": 12, "Village": 13, "Community": 14, "Place": 14, "Neighborhood": 14, "Highway": 11, "Road": 15,
         "Trail": 15, "Lake": 12, "River": 12, "Bay": 11}


def _like(word):
    return word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _same(typed, word):
    """Is a typed word the same as a word of a name, allowing 'st' for 'street' or 'saint' and the like?"""
    return typed == word or word in SHORT.get(typed, ()) or typed in SHORT.get(word, ())


def _match(typed, name):
    """How well the typed words fit a name: 0 the whole name, 1 its first words, 2 its start, 3 somewhere in it."""
    if len(typed) <= len(name) and all(_same(t, n) for t, n in zip(typed, name)):
        return 0 if len(typed) == len(name) else 1
    if (len(typed) <= len(name) and all(_same(t, n) for t, n in zip(typed[:-1], name))
            and name[len(typed) - 1].startswith(typed[-1])):
        return 2
    return 3


def search(filename, q, lon=None, lat=None, limit=12):
    """Places in one map whose name matches every word typed. Nearest to (lon, lat) first when given."""
    if os.path.basename(filename) != filename or not filename.endswith(".pmtiles"):
        raise ValueError("bad file name")
    path = os.path.join(MAPS_DIR, filename)
    if not os.path.isfile(path):
        raise FileNotFoundError(filename)
    words = fold(q).split()[:6]
    if not words or len("".join(words)) < 2:
        return {"ready": True, "results": []}
    if not is_current(path):
        return {"ready": False, "results": []}
    here = lon is not None and lat is not None
    k = math.cos(math.radians(lat)) ** 2 if here else 1.0
    dist = "((lon - ?) * (lon - ?) * ? + (lat - ?) * (lat - ?))"
    rows = []
    con = sqlite3.connect(f"file:{db_path(path)}?mode=ro", uri=True)
    try:
        # One word typed is looked up in the word index of the names; the longest narrows things most
        # ("clair" beats "st"). The other words may match the name, its road number or the nearby
        # town, and may be the usual short forms. If the longest word turns out to be the town
        # ("main st plymouth"), the next longest is tried.
        for anchor in sorted(set(words), key=len, reverse=True):
            where = ["rowid IN (SELECT id FROM words WHERE word >= ? AND word < ?)"]
            args = [anchor, anchor + "{"]                    # "{" sorts just after "z"
            rest = list(words)
            rest.remove(anchor)
            for w in rest:
                clause = []
                for form in sorted({w, *SHORT.get(w, ())}):  # "main st" finds "Main Street"
                    clause.append("(hay LIKE ? ESCAPE '\\' OR hay LIKE ? ESCAPE '\\')")
                    args += [_like(form) + "%", "% " + _like(form) + "%"]
                where.append("(" + " OR ".join(clause) + ")")
            sql = "SELECT name, fold, label, layer, lon, lat, near, score FROM places WHERE " + " AND ".join(where)
            rows = con.execute(sql + f" AND score >= {TOWN} ORDER BY score DESC LIMIT 60", args).fetchall()
            if here:
                rows += con.execute(sql + f" AND score < {TOWN} ORDER BY {dist} LIMIT 300",
                                    args + [lon, lon, k, lat, lat]).fetchall()
            else:
                rows += con.execute(sql + f" AND score < {TOWN} ORDER BY score DESC LIMIT 300", args).fetchall()
            if rows:
                break
    finally:
        con.close()
    seen, out = set(), []

    def key(r):
        name, f, label, layer, rlon, rlat, near, score = r
        d = ((rlon - lon) ** 2 * k + (rlat - lat) ** 2) if here else 0.0
        match = _match(words, f.split())
        if score >= TOWN:                      # real towns first, the bigger the better, then the nearer
            return (match, 0, -score, d)
        return (match, 1, d / 16 if score == 22 else d, -score)      # big parks and airports count as closer

    for r in sorted(rows, key=key):
        name, f, label, layer, rlon, rlat, near, score = r
        # One long street shows once per town, not once per kilometre; a highway shows once.
        dedupe = ((f, label) if label == "Highway" else (f, label, near) if near
                  else (f, label, round(rlon, 1), round(rlat, 1)))
        if dedupe in seen:
            continue
        seen.add(dedupe)
        out.append({"name": name, "kind": label, "near": near if near and fold(near) != f else "",
                    "lon": rlon, "lat": rlat, "zoom": ZOOMS.get(label, 16)})
        if len(out) >= limit:
            break
    return {"ready": True, "results": out}
