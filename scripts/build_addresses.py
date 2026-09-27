#!/usr/bin/env python3
"""Build Mimi's offline street-address index (``maps/addresses.sqlite``).

``core/mimi/address.py`` reads it to answer "123 Main St, Springfield, IL" with no
network connection. Every source's street names go through
``mimi.address_norm.street_key``, so "N Main St" (TIGER), "North Main Street" (OSM)
and "MAIN ST N" (NAR) meet on one key.

Sources (any subset; with no input options the files under ``.tools/dl`` are used)
    --tiger       US Census TIGER/Line address ranges, as preprocessed by Nominatim
                  (tiger2025-nominatim-preprocessed.csv.tar.gz: one semicolon CSV per
                  county). Public domain.
    --zips        US ZIP code centroids (us_postcodes.csv.gz: postcode,lat,lon).
    --nar         Statistics Canada National Address Register (<yyyymm>.zip with
                  Addresses/ and Locations/ CSVs joined on LOC_GUID). Statistics
                  Canada Open Licence.
    --osm-roads   OpenStreetMap extracts: named drivable ways become streets (ODbL).
    --osm-points  OpenStreetMap extracts: addr:housenumber + addr:street nodes and
                  buildings become exact address points (ODbL).

Tables (coordinates are INTEGER degrees * 1e6)
    streets    one row per (street_key, 0.1 degree grid cell), all sources merged;
               name is the fullest spelling seen, lat/lon a point in the cell
    ranges     TIGER house-number ranges; geom is a Google polyline (precision 6)
               in the direction the numbers run from ``lo`` (rev=0) or ``hi`` (rev=1)
    points     exact civic numbers (NAR, OSM), one per (street, number, unit)
    postcodes  US ZIPs, Canadian postal codes and FSAs (means of NAR points)
    meta       norm_version (must match address_norm.VERSION), built_at, sources, counts

Everything is streamed. Rows are staged in scratch SQLite files next to the output
and merged with set-based SQL (a window over (key, cell) for streets, joins for the
street ids), so memory stays flat (~0.5-1 GB) however large the inputs are. OSM
node coordinates are fetched with a second, node-only pass per ~2 billion node ids
(osmium's IdFilter bitmap costs 1 bit per id in the window).

Measured on a handheld PC (2026 data): TIGER ~45k rows/s (~36M rows), NAR ~65k
addresses/s plus ~200k locations/s, OSM ~130k named ways/s. The full default build
takes roughly 45 minutes, needs ~12 GB of free space next to the output while it
runs and leaves an index of ~5.5 GB.

The index is written to ``<out>.building`` and moved into place at the end, so a
failed or interrupted build never leaves a half-written ``addresses.sqlite``. When a
running Mimi holds the old file open (Windows), the new one is left as
``<out>.new`` and Mimi installs it on its next start.

Usage (from the repository root, with Mimi's portable Python):

    python\\python.exe scripts\\build_addresses.py
    python\\python.exe scripts\\build_addresses.py --nar .tools\\dl\\nar\\202606.zip --nar-provinces 10 11 --out x.sqlite
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import gzip
import io
import json
import math
import os
import re
import shutil
import sqlite3
import sys
import tarfile
import time
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Iterator, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from mimi.address_norm import STATE_CODES, VERSION, house_number, street_base, street_key  # noqa: E402

DL = ROOT / ".tools" / "dl"
DEFAULT_OUT = ROOT / "maps" / "addresses.sqlite"
DEFAULTS = {
    "tiger": DL / "tiger" / "tiger2025-nominatim-preprocessed.csv.tar.gz",
    "zips": DL / "tiger" / "us_postcodes.csv.gz",
    "nar": DL / "nar" / "202606.zip",
    "osm_roads": [DL / "osm" / "keep-us.roads.osm.pbf", DL / "osm" / "keep-canada.roads.osm.pbf"],
}

# Named ways of these kinds are streets people give as addresses: the routing build's
# drivable set (scripts/build_routing.py) plus the residential kinds.
ROAD_TYPES = frozenset((
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link",
    "tertiary", "tertiary_link", "unclassified", "residential", "living_street", "service", "road", "track",
))
NAR_PROVINCES = {"10": "nl", "11": "pe", "12": "ns", "13": "nb", "24": "qc", "35": "on", "46": "mb", "47": "sk",
                 "48": "ab", "59": "bc", "60": "yt", "61": "nt", "62": "nu"}
ATTRIBUTION = {
    "tiger": "US Census Bureau TIGER/Line address ranges (public domain)",
    "zips": "US ZIP code centroids (Nominatim us_postcodes, derived from public-domain Census data)",
    "nar": "Statistics Canada National Address Register (Statistics Canada Open Licence)",
    "osm": "© OpenStreetMap contributors (ODbL)",
}

E6 = 1_000_000
BATCH = 20_000
COMBINE_MAX = 250_000  # (key, cell) entries held before the street combiner flushes to disk
NODE_WINDOW = 1 << 31  # node ids per IdFilter pass (the filter's bitmap: 256 MB)
MIN_STEP2 = (5 / 111_320) ** 2  # TIGER vertices closer than ~5 m to the last kept one are dropped
# peak scratch + output bytes per input byte, measured on 2026 data (TIGER: ~3 GB staged, ~3.4 GB in the index)
DISK_FACTORS = {"tiger": 3.5, "nar": 1.8, "zips": 2.0, "osm_roads": 0.8, "osm_points": 0.5}

SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE streets(id INTEGER PRIMARY KEY, key TEXT NOT NULL, base TEXT NOT NULL, name TEXT NOT NULL, cell INTEGER NOT NULL,
                     lat INTEGER NOT NULL, lon INTEGER NOT NULL, region TEXT, postcode TEXT);
CREATE TABLE ranges(sid INTEGER NOT NULL, lo INTEGER NOT NULL, hi INTEGER NOT NULL, parity INTEGER NOT NULL, rev INTEGER NOT NULL,
                    postcode TEXT, geom TEXT NOT NULL);
CREATE TABLE points(sid INTEGER NOT NULL, num INTEGER NOT NULL, numtext TEXT NOT NULL, unit TEXT, lat INTEGER NOT NULL,
                    lon INTEGER NOT NULL, postcode TEXT, source TEXT NOT NULL);
CREATE TABLE postcodes(code TEXT PRIMARY KEY, lat INTEGER NOT NULL, lon INTEGER NOT NULL, region TEXT);
"""
STAGE_SCHEMA = """
CREATE TABLE {s}.obs(key TEXT, base TEXT, name TEXT, cell INTEGER, lat INTEGER, lon INTEGER, region TEXT, postcode TEXT);
CREATE TABLE {s}.ranges(key TEXT, cell INTEGER, lo INTEGER, hi INTEGER, parity INTEGER, rev INTEGER, postcode TEXT, geom TEXT);
CREATE TABLE {s}.points(key TEXT, cell INTEGER, num INTEGER, numtext TEXT, unit TEXT, lat INTEGER, lon INTEGER, postcode TEXT,
                        source TEXT);
"""
# SQL twin of cell_of() for integer micro-degrees
TMP_VARS = ("SQLITE_TMPDIR", "TMP", "TEMP", "TMPDIR")
CELL_SQL = "((({lat}) + 90000000) / 100000) * 3600 + ((({lon}) + 180000000) / 100000)"

_T0 = time.monotonic()


def log(msg: str) -> None:
    elapsed = time.monotonic() - _T0
    print(f"[{int(elapsed // 60):02d}:{elapsed % 60:04.1f}] {msg}", flush=True)


def fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} GB"


class Progress:
    """Rows done and rows/s every ~10 s, with a percentage when the input size is known."""

    def __init__(self, label: str, total: int | None = None, pos=None) -> None:
        self.label, self.total, self.pos = label, total, pos
        self.n = 0
        self.t0 = self.last = time.monotonic()

    def add(self, n: int) -> None:
        self.n += n
        now = time.monotonic()
        if now - self.last >= 10:
            self.last = now
            pct = f", {100 * self.pos() / self.total:.1f}%" if self.total and self.pos else ""
            log(f"  {self.label}: {self.n:,} rows ({self.n / (now - self.t0):,.0f}/s{pct})")

    def done(self, extra: str = "") -> None:
        dt = max(time.monotonic() - self.t0, 1e-9)
        log(f"  {self.label}: {self.n:,} rows in {dt:.0f} s ({self.n / dt:,.0f}/s){extra}")


# ---------------------------------------------------------------------------
# Geometry (the same definitions as core/mimi/address.py)
# ---------------------------------------------------------------------------


def cell_of(lat: float, lon: float) -> int:
    """0.1 degree grid cell of a point."""
    return int((lat + 90) * 10) * 3600 + int((lon + 180) * 10)


def encode_polyline(points: Iterable[tuple[int, int]]) -> str:
    """Google polyline encoding of (lat, lon) pairs already scaled to integer micro-degrees."""
    out, plat, plon = [], 0, 0
    for ilat, ilon in points:
        for d in (ilat - plat, ilon - plon):
            v = ~(d << 1) if d < 0 else d << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        plat, plon = ilat, ilon
    return "".join(out)


def simplify_line(pts: list[tuple[float, float]]) -> tuple[list[tuple[float, float]], tuple[float, float]]:
    """Drop vertices within ~5 m of the last kept one (endpoints always stay) and find the
    point halfway along the line, which decides the grid cell a segment is filed under."""
    if len(pts) == 1:
        return pts, pts[0]
    k = math.cos(math.radians(pts[0][0]))
    kept, lens = [pts[0]], []
    plat, plon = pts[0]
    last = len(pts) - 1
    for i in range(1, last + 1):
        lat, lon = pts[i]
        dy, dx = lat - plat, (lon - plon) * k
        d2 = dy * dy + dx * dx
        if d2 >= MIN_STEP2 or i == last:
            kept.append(pts[i])
            lens.append(math.sqrt(d2))
            plat, plon = lat, lon
    half = sum(lens) / 2
    for (a, b), seg in zip(zip(kept, kept[1:]), lens):
        if half <= seg and seg > 0:
            t = half / seg
            return kept, (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        half -= seg
    return kept, kept[-1]


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


@lru_cache(maxsize=300_000)
def keys_of(name: str) -> tuple[str, str]:
    key = street_key(name)
    return key, (street_base(key) if key else "")


def us_zip(text: str | None) -> str | None:
    m = re.match(r"\s*(\d{5})", text or "")
    return m.group(1) if m else None


def ca_postcode(text: str | None) -> str | None:
    t = (text or "").replace(" ", "").upper()
    return t if re.fullmatch(r"[A-Z]\d[A-Z]\d[A-Z]\d", t) else None


def any_postcode(text: str | None) -> str | None:
    return ca_postcode(text) or us_zip(text)


# French street types come first ("Rue Principale", "Chemin du Lac"), as OpenStreetMap
# and people write them, so NAR's "Principale RUE" must be turned around to share a key.
FR_TYPES = {
    "RUE": "Rue", "AV": "Avenue", "BOUL": "Boulevard", "CH": "Chemin", "ROUTE": "Route", "RTE": "Route", "RANG": "Rang",
    "MONTÉE": "Montée", "MONTEE": "Montée", "TSSE": "Terrasse", "CROIS": "Croissant", "CÔTE": "Côte", "COTE": "Côte",
    "ALLÉE": "Allée", "ALLEE": "Allée", "CAR": "Carré", "CARREF": "Carrefour", "IMP": "Impasse", "PROM": "Promenade",
    "SENT": "Sentier", "RDPT": "Rond-point", "RLE": "Ruelle", "QUAI": "Quai", "CERCLE": "Cercle", "PARC": "Parc",
    "VOIE": "Voie", "AUT": "Autoroute", "PLACE": "Place", "DOMAINE": "Domaine", "PLAT": "Plateau", "ÎLE": "Île",
    "ILE": "Île", "ÉCH": "Échangeur", "CDS": "Cul-de-sac", "ESPL": "Esplanade", "PASS": "Passage", "SQ": "Square",
    "PL": "Place", "BOIS": "Bois", "PTIE": "Pointe", "PT": "Pointe", "CARRÉ": "Carré",
}
FR_AMBIGUOUS = frozenset(("PASS", "SQ", "ESPL", "PL", "PT"))  # English abbreviations too: French only in Quebec
FR_DIRS = {"N": "Nord", "S": "Sud", "E": "Est", "O": "Ouest", "W": "Ouest", "NE": "Nord-Est", "NO": "Nord-Ouest",
           "SE": "Sud-Est", "SO": "Sud-Ouest"}
_PARTICLES = frozenset(("de", "du", "des", "la", "le", "les", "d", "l", "et", "à", "au", "aux", "of", "the", "and"))


def smart_title(text: str) -> str:
    """'LAC-WILSON DU' -> 'Lac-Wilson du' style casing for names the register stores in capitals."""
    words = []
    for i, w in enumerate(text.lower().split()):
        parts = []
        for j, p in enumerate(w.split("-")):
            if "'" in p:
                a, _, b = p.partition("'")
                p = (a if a in ("d", "l") and (i or j) else a.capitalize()) + "'" + b.capitalize()
            elif not ((i or j) and p in _PARTICLES):
                p = p[:1].upper() + p[1:]
            parts.append(p)
        words.append("-".join(parts))
    return " ".join(words)


def nar_street(name: str, stype: str, sdir: str, qc: bool) -> str:
    """Display name from the register's (name, type, direction) fields."""
    name = name.strip()
    if name.isupper() and len(name) > 3:
        name = smart_title(name)
    stype, sdir = stype.strip().upper(), sdir.strip().upper()
    if stype in ("HWY", "HIGHWAY") and re.fullmatch(r"\d+[A-Z]?", name, re.I):
        return " ".join(p for p in ("Highway", name.upper(), sdir) if p)  # "6 HWY" is Highway 6
    french = stype in FR_TYPES and (stype not in FR_AMBIGUOUS or qc)
    if not french and stype and name[:1].islower():
        french = True  # "du Lac-Wilson" + any type
    if french:
        first, _, rest = name.partition(" ")
        if rest and first.lower() in _PARTICLES:
            name = f"{first.lower()} {rest}"  # "DU LAC-WILSON" -> "Chemin du Lac-Wilson"
        parts = [FR_TYPES.get(stype, stype.title()), name, FR_DIRS.get(sdir, sdir)]
    else:
        parts = [name, stype.title(), sdir]
    return " ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Build context
# ---------------------------------------------------------------------------


class Build:
    """One index build: the output connection, the staging files, the street combiner."""

    def __init__(self, out: Path) -> None:
        self.out = out
        self.path = out.with_name(out.name + ".building")
        self.tmpdir = out.with_name(out.name + ".tmp")
        self.stage = {s: out.with_name(f"{out.name}.{s}") for s in ("stage", "scratch")}
        self.combined: dict[tuple[str, int], list] = {}
        self.pc_region: dict[str, dict[str, int]] = {}  # US ZIP -> state counts (TIGER)
        self.pc_sum: dict[str, list[float]] = {}  # US ZIP -> [lat sum, lon sum, n] of TIGER segments
        self.sources: list[dict] = []

    def open(self) -> None:
        self.cleanup()
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        # SQLite's sorter spills to the OS temp dir; keep that on the output's disk, not C:
        # (main() restores these afterwards).
        for var in TMP_VARS:
            os.environ[var] = str(self.tmpdir)
        self.db = db = sqlite3.connect(self.path, isolation_level=None)
        for s, p in self.stage.items():
            db.execute("ATTACH DATABASE ? AS " + s, (str(p),))
        for s, cache_mb in (("main", 192), ("stage", 64), ("scratch", 96)):
            db.execute(f"PRAGMA {s}.journal_mode = OFF")
            db.execute(f"PRAGMA {s}.synchronous = OFF")
            db.execute(f"PRAGMA {s}.cache_size = {-cache_mb * 1024}")
        db.execute("PRAGMA temp_store = FILE")
        db.execute("PRAGMA locking_mode = EXCLUSIVE")
        try:
            db.execute("PRAGMA temp_store_directory = '%s'" % str(self.tmpdir).replace("'", "''"))
        except sqlite3.Error:
            pass
        db.executescript(SCHEMA + STAGE_SCHEMA.format(s="stage"))

    def close(self) -> None:
        try:
            self.db.execute("PRAGMA temp_store_directory = ''")  # process-wide; don't leave it pointing at tmpdir
        except (AttributeError, sqlite3.Error):
            pass
        try:
            self.db.close()
        except (AttributeError, sqlite3.Error):
            pass

    def abort(self) -> None:
        """Close and delete everything this build wrote; the existing index is untouched."""
        self.close()
        self.cleanup()

    def cleanup(self) -> None:
        for p in (self.path, *self.stage.values()):
            p.unlink(missing_ok=True)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def begin(self) -> None:
        self.db.execute("BEGIN")

    def commit(self) -> None:
        self.db.execute("COMMIT")

    def observe(self, key: str, base: str, name: str, cell: int, ilat: int, ilon: int, region: str | None,
                postcode: str | None) -> None:
        """Note that a street is in a cell. Duplicates are merged in memory first (a bounded
        combiner, flushed when full); the exact merge is one GROUP BY at the end."""
        k = (key, cell)
        cur = self.combined.get(k)
        if cur is None:
            self.combined[k] = [base, name, ilat, ilon, region, postcode]
            if len(self.combined) >= COMBINE_MAX:
                self.flush()
            return
        if len(name) > len(cur[1]):
            cur[1], cur[2], cur[3] = name, ilat, ilon
        if region and cur[4] != region:
            cur[4] = region if cur[4] is None else ""  # "": streets of this name in two regions here
        if cur[5] is None and postcode:
            cur[5] = postcode

    def flush(self) -> None:
        if self.combined:
            self.db.executemany("INSERT INTO stage.obs VALUES (?,?,?,?,?,?,?,?)",
                                ((k, v[0], v[1], c, v[2], v[3], v[4], v[5]) for (k, c), v in self.combined.items()))
            self.combined.clear()

    def reset_scratch(self, schema: str) -> None:
        """Empty the per-input scratch file (NAR locations, OSM node lists) and create tables."""
        db = self.db
        db.execute("DETACH DATABASE scratch")
        self.stage["scratch"].unlink(missing_ok=True)
        db.execute("ATTACH DATABASE ? AS scratch", (str(self.stage["scratch"]),))
        db.execute("PRAGMA scratch.journal_mode = OFF")
        db.execute("PRAGMA scratch.synchronous = OFF")
        db.execute(f"PRAGMA scratch.cache_size = {-96 * 1024}")
        if schema:
            db.executescript(schema)


# ---------------------------------------------------------------------------
# TIGER address ranges
# ---------------------------------------------------------------------------


def load_tiger(b: Build, path: Path, limit: int | None) -> int:
    log(f"TIGER address ranges: {path}")
    parity_of = {"odd": 1, "even": 2}
    rows: list[tuple] = []
    n = bad = 0
    raw = open(path, "rb")
    prog = Progress("tiger", path.stat().st_size, raw.tell)
    b.begin()
    try:
        with tarfile.open(fileobj=raw, mode="r|gz") as tar:
            for member in tar:
                if not (member.isfile() and member.name.endswith(".csv")):
                    continue
                f = tar.extractfile(member)  # a stream member isn't seekable, which TextIOWrapper wants
                reader = csv.reader((line.decode("utf-8", "replace") for line in f), delimiter=";")
                header = next(reader, None)
                if header and header[0] != "from":
                    raise ValueError(f"{member.name}: unexpected header {header}")
                for row in reader:
                    if len(row) != 8:
                        bad += 1
                        continue
                    frm, to, interp, street, _county, state, postcode, geom = row
                    key, base = keys_of(street)
                    if not key:
                        bad += 1
                        continue
                    try:
                        a, z = int(frm), int(to)
                        i, j = geom.index("("), geom.rindex(")")
                        pts = [(float(lat), float(lon)) for lon, lat in (c.split() for c in geom[i + 1:j].split(","))]
                    except ValueError:
                        bad += 1
                        continue
                    kept, (mlat, mlon) = simplify_line(pts)
                    cell = cell_of(mlat, mlon)
                    region = state.lower() if state.lower() in STATE_CODES else None
                    zipc = us_zip(postcode)
                    rows.append((key, cell, min(a, z), max(a, z), parity_of.get(interp, 0), 1 if a > z else 0, zipc,
                                 encode_polyline((round(la * E6), round(lo * E6)) for la, lo in kept)))
                    b.observe(key, base, street, cell, round(mlat * E6), round(mlon * E6), region, zipc)
                    if zipc:
                        if region:
                            counts = b.pc_region.setdefault(zipc, {})
                            counts[region] = counts.get(region, 0) + 1
                        s = b.pc_sum.setdefault(zipc, [0.0, 0.0, 0])
                        s[0] += mlat
                        s[1] += mlon
                        s[2] += 1
                    n += 1
                    if len(rows) >= BATCH:
                        b.db.executemany("INSERT INTO stage.ranges VALUES (?,?,?,?,?,?,?,?)", rows)
                        prog.add(len(rows))
                        rows.clear()
                    if limit and n >= limit:
                        break
                if limit and n >= limit:
                    break
        if rows:
            b.db.executemany("INSERT INTO stage.ranges VALUES (?,?,?,?,?,?,?,?)", rows)
            prog.add(len(rows))
        b.flush()
        b.commit()
    finally:
        raw.close()
    prog.done(f", {bad:,} skipped")
    b.sources.append({"name": "tiger", "file": path.name, "bytes": path.stat().st_size, "rows": n,
                      "attribution": ATTRIBUTION["tiger"]})
    return n


# ---------------------------------------------------------------------------
# US ZIP centroids
# ---------------------------------------------------------------------------


def load_zips(b: Build, path: Path, limit: int | None) -> int:
    log(f"US ZIP centroids: {path}")
    rows, seen = [], set()
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        for rec in csv.DictReader(f):
            code = us_zip(rec.get("postcode"))
            try:
                lat, lon = float(rec["lat"]), float(rec["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            if not code or code in seen:
                continue
            seen.add(code)
            rows.append((code, round(lat * E6), round(lon * E6), _majority(b.pc_region.get(code))))
            if limit and len(rows) >= limit:
                break
    # ZIPs TIGER knows but the centroid file doesn't: the mean of their street segments
    extra = [(code, round(s[0] / s[2] * E6), round(s[1] / s[2] * E6), _majority(b.pc_region.get(code)))
             for code, s in b.pc_sum.items() if code not in seen]
    b.begin()
    b.db.executemany("INSERT OR IGNORE INTO postcodes VALUES (?,?,?,?)", rows + extra)
    b.commit()
    log(f"  zips: {len(rows):,} centroids + {len(extra):,} from TIGER segments")
    b.sources.append({"name": "zips", "file": path.name, "bytes": path.stat().st_size, "rows": len(rows),
                      "attribution": ATTRIBUTION["zips"]})
    return len(rows)


def _majority(counts: dict[str, int] | None) -> str | None:
    return max(counts, key=counts.get) if counts else None


# ---------------------------------------------------------------------------
# Canada: National Address Register
# ---------------------------------------------------------------------------


def _text_lines(raw: io.BufferedIOBase) -> Iterator[str]:
    """UTF-8 lines, falling back to cp1252 for a line that isn't (the register mixes them)."""
    first = True
    for line in raw:
        try:
            s = line.decode("utf-8")
        except UnicodeDecodeError:
            s = line.decode("cp1252", "replace")
        if first:
            s, first = s.lstrip("﻿"), False
        yield s


def _nar_files(zf: zipfile.ZipFile, kind: str, prov: str) -> list[str]:
    pat = re.compile(rf"(?:.*/)?{kind}_{prov}(?:_part_(\d+))?\.csv$", re.I)
    found = [(int(m.group(1) or 0), n) for n in zf.namelist() if (m := pat.match(n))]
    return [n for _, n in sorted(found)]


def _coord(rec: list[str], i_lat: int, i_lon: int) -> tuple[float, float] | None:
    try:
        lat, lon = float(rec[i_lat]), float(rec[i_lon])
    except (IndexError, ValueError):
        return None
    return (lat, lon) if 40 <= lat <= 84 and -142 <= lon <= -50 else None


def load_nar(b: Build, path: Path, provinces: Sequence[str] | None, limit: int | None) -> int:
    log(f"National Address Register: {path}")
    total = 0
    with zipfile.ZipFile(path) as zf:
        for prov in provinces or sorted(NAR_PROVINCES):
            region = NAR_PROVINCES.get(prov)
            if not region:
                raise SystemExit(f"unknown NAR province code {prov!r} (use {', '.join(sorted(NAR_PROVINCES))})")
            locs, addrs = _nar_files(zf, "Location", prov), _nar_files(zf, "Address", prov)
            if not locs or not addrs:
                log(f"  {region}: no files in the archive, skipped")
                continue
            total += _nar_province(b, zf, prov, region, locs, addrs, limit and max(limit - total, 0))
            if limit and total >= limit:
                break
    b.sources.append({"name": "nar", "file": path.name, "bytes": path.stat().st_size, "rows": total,
                      "provinces": list(provinces or sorted(NAR_PROVINCES)), "attribution": ATTRIBUTION["nar"]})
    return total


def _nar_province(b: Build, zf: zipfile.ZipFile, prov: str, region: str, locs: list[str], addrs: list[str],
                  limit: int | None) -> int:
    """Stage the province's locations (LOC_GUID -> point) in an indexed scratch table, then
    stream its addresses and look their points up a batch at a time."""
    db = b.db
    b.reset_scratch("CREATE TABLE scratch.loc(guid TEXT, lat INTEGER, lon INTEGER);")
    prog = Progress(f"{region} locations")
    b.begin()
    for name in locs:
        with io.BufferedReader(zf.open(name), 1 << 20) as raw:
            reader = csv.reader(_text_lines(raw))
            h = {c.strip().upper(): i for i, c in enumerate(next(reader))}
            ig, bg, bf = h["LOC_GUID"], (h["BG_LATITUDE"], h["BG_LONGITUDE"]), (h["BF_REPPOINT_LATITUDE"], h["BF_REPPOINT_LONGITUDE"])
            rows = []
            for rec in reader:
                p = _coord(rec, *bg) or _coord(rec, *bf)
                if p:
                    rows.append((rec[ig], round(p[0] * E6), round(p[1] * E6)))
                if len(rows) >= BATCH:
                    db.executemany("INSERT INTO scratch.loc VALUES (?,?,?)", rows)
                    prog.add(len(rows))
                    rows.clear()
            db.executemany("INSERT INTO scratch.loc VALUES (?,?,?)", rows)
            prog.add(len(rows))
    db.execute("CREATE INDEX scratch.loc_guid ON loc(guid)")
    b.commit()
    prog.done()

    qc = prov == "24"
    lookup = ("SELECT l.guid, l.lat, l.lon FROM json_each(?) j CROSS JOIN scratch.loc l ON l.guid = j.value")
    n = nocoord = noname = 0
    prog = Progress(f"{region} addresses")
    b.begin()
    for name in addrs:
        with io.BufferedReader(zf.open(name), 1 << 20) as raw:
            reader = csv.reader(_text_lines(raw))
            h = {c.strip().upper(): i for i, c in enumerate(next(reader))}
            cols = [h[c] for c in ("LOC_GUID", "APT_NO_LABEL", "CIVIC_NO", "CIVIC_NO_SUFFIX", "OFFICIAL_STREET_NAME",
                                   "OFFICIAL_STREET_TYPE", "OFFICIAL_STREET_DIR", "MAIL_STREET_NAME", "MAIL_STREET_TYPE",
                                   "MAIL_STREET_DIR", "MAIL_POSTAL_CODE")]
            width = max(cols) + 1
            done = False
            while not done:
                batch = []
                for rec in reader:
                    if len(rec) >= width:
                        batch.append([rec[i] for i in cols])
                    if len(batch) >= BATCH or (limit and n + len(batch) >= limit):
                        break
                else:
                    done = True
                if limit and n + len(batch) >= limit:
                    batch, done = batch[:limit - n], True
                if not batch:
                    break
                where = {g: (la, lo) for g, la, lo in db.execute(lookup, (json.dumps(list({r[0] for r in batch})),))}
                pts = []
                for guid, apt, civic, suffix, oname, otype, odir, mname, mtype, mdir, postal in batch:
                    p = where.get(guid)
                    if p is None:
                        nocoord += 1
                        continue
                    street = nar_street(oname, otype, odir, qc) if oname.strip() else (
                        nar_street(mname, mtype, mdir, qc) if mname.strip() else "")
                    key, base = keys_of(street) if street else ("", "")
                    if not key:
                        noname += 1
                        continue
                    ilat, ilon = p
                    cell = cell_of(ilat / E6, ilon / E6)
                    pc = ca_postcode(postal)
                    b.observe(key, base, street, cell, ilat, ilon, region, pc)
                    civic, suffix = civic.strip(), suffix.strip()
                    hn = house_number(civic + ((" " if "/" in suffix else "") + suffix if suffix else ""))
                    if hn is None and civic.isdigit():
                        hn = (int(civic), civic + suffix)
                    if hn:
                        pts.append((key, cell, hn[0], hn[1], apt.strip() or None, ilat, ilon, pc, "nar"))
                db.executemany("INSERT INTO stage.points VALUES (?,?,?,?,?,?,?,?,?)", pts)
                n += len(batch)
                prog.add(len(batch))
        if limit and n >= limit:
            break
    b.flush()
    b.commit()
    prog.done(f", {nocoord:,} without a location, {noname:,} without a street name")
    b.reset_scratch("")
    return n


# ---------------------------------------------------------------------------
# OpenStreetMap
# ---------------------------------------------------------------------------

OSM_SCRATCH = """
CREATE TABLE scratch.ways(node INTEGER, key TEXT, base TEXT, name TEXT);
CREATE TABLE scratch.addrs(node INTEGER, key TEXT, base TEXT, name TEXT, num INTEGER, numtext TEXT, unit TEXT,
                           postcode TEXT, region TEXT);
CREATE TABLE scratch.nodes(id INTEGER PRIMARY KEY, lat INTEGER, lon INTEGER);
"""


def _osm_names(tags) -> list[str]:
    names = [x.strip() for x in (tags.get("name") or "").split(";")]
    for r in (tags.get("ref") or "").split(";"):
        r = r.strip()
        if r and not r.isdigit() and any(c.isdigit() for c in r):  # "WY 59", "I 80"; a bare "401" says nothing
            names.append(r)
    return [x for x in names if x]


def _osm_numbers(text: str) -> list[tuple[int, str]]:
    return [hn for part in re.split(r"[;,]", text) if (hn := house_number(part))]


def load_osm(b: Build, path: Path, roads: bool, points: bool, limit: int | None) -> dict:
    """Pass 1 reads ways (and address nodes) and stages the node ids whose coordinates are
    needed; pass 2 reads only nodes, filtered to those ids in C++, a window of ids at a time."""
    import osmium

    log(f"OpenStreetMap {'roads' if roads else ''}{' + ' if roads and points else ''}{'addresses' if points else ''}: {path}")
    db = b.db
    b.reset_scratch(OSM_SCRATCH)
    keys = (["highway"] if roads else []) + (["addr:housenumber"] if points else [])
    ents = osmium.osm.WAY | osmium.osm.NODE if points else osmium.osm.WAY
    ways, addrs, direct = [], [], []
    n_ways = n_addr = seen = 0
    prog = Progress("osm objects")
    b.begin()
    fp = osmium.FileProcessor(str(path), ents).with_filter(osmium.filter.KeyFilter(*keys))
    for o in fp:
        seen += 1
        t = o.tags
        if points and "addr:housenumber" in t:
            street = t.get("addr:street")
            key, base = keys_of(street) if street else ("", "")
            nums = _osm_numbers(t.get("addr:housenumber", "")) if key else []
            if nums:
                unit = t.get("addr:unit") or None
                pc = any_postcode(t.get("addr:postcode"))
                st = (t.get("addr:state") or t.get("addr:province") or "").strip().lower()
                region = st if st in STATE_CODES else None
                if o.is_node():
                    if o.location.valid():
                        ilat, ilon = round(o.location.lat * E6), round(o.location.lon * E6)
                        cell = cell_of(o.location.lat, o.location.lon)
                        b.observe(key, base, street, cell, ilat, ilon, region, pc)
                        direct.extend((key, cell, num, numtext, unit, ilat, ilon, pc, "osm") for num, numtext in nums)
                        n_addr += len(nums)
                elif o.is_way() and len(o.nodes):
                    ref = o.nodes[0].ref
                    addrs.extend((ref, key, base, street, num, numtext, unit, pc, region) for num, numtext in nums)
                    n_addr += len(nums)
        if roads and o.is_way() and t.get("highway") in ROAD_TYPES:
            names = _osm_names(t)
            if names:
                nn = len(o.nodes)
                refs = {o.nodes[nn // 2].ref} | ({o.nodes[0].ref, o.nodes[nn - 1].ref} if nn > 8 else set())
                for name in names:
                    key, base = keys_of(name)
                    if key:
                        ways.extend((ref, key, base, name) for ref in refs)
                n_ways += 1
        if len(ways) + len(addrs) + len(direct) >= BATCH:
            db.executemany("INSERT INTO scratch.ways VALUES (?,?,?,?)", ways)
            db.executemany("INSERT INTO scratch.addrs VALUES (?,?,?,?,?,?,?,?,?)", addrs)
            db.executemany("INSERT INTO stage.points VALUES (?,?,?,?,?,?,?,?,?)", direct)
            prog.add(len(ways) + len(addrs) + len(direct))
            ways.clear(), addrs.clear(), direct.clear()
        if limit and seen >= limit:
            break
    db.executemany("INSERT INTO scratch.ways VALUES (?,?,?,?)", ways)
    db.executemany("INSERT INTO scratch.addrs VALUES (?,?,?,?,?,?,?,?,?)", addrs)
    db.executemany("INSERT INTO stage.points VALUES (?,?,?,?,?,?,?,?,?)", direct)
    prog.add(len(ways) + len(addrs) + len(direct))
    b.flush()
    db.execute("CREATE TABLE scratch.need(id INTEGER PRIMARY KEY)")
    db.execute("INSERT OR IGNORE INTO scratch.need SELECT node FROM scratch.ways UNION ALL SELECT node FROM scratch.addrs")
    b.commit()
    prog.done(f": {n_ways:,} named ways, {n_addr:,} address numbers")

    windows = [w for (w,) in db.execute(f"SELECT DISTINCT id / {NODE_WINDOW} FROM scratch.need ORDER BY 1")]
    need = db.execute("SELECT count(*) FROM scratch.need").fetchone()[0]
    prog = Progress("osm node coordinates")
    b.begin()
    for w in windows:
        lo, hi = w * NODE_WINDOW, (w + 1) * NODE_WINDOW
        ids = (i for (i,) in db.cursor().execute("SELECT id FROM scratch.need WHERE id >= ? AND id < ?", (lo, hi)))
        flt = osmium.filter.IdFilter(ids)
        rows = []
        for o in osmium.FileProcessor(str(path), osmium.osm.NODE).with_filter(flt):
            if o.location.valid():
                rows.append((o.id, round(o.location.lat * E6), round(o.location.lon * E6)))
                if len(rows) >= BATCH:
                    db.executemany("INSERT OR IGNORE INTO scratch.nodes VALUES (?,?,?)", rows)
                    prog.add(len(rows))
                    rows.clear()
        db.executemany("INSERT OR IGNORE INTO scratch.nodes VALUES (?,?,?)", rows)
        prog.add(len(rows))
        del flt
    cell = CELL_SQL.format(lat="n.lat", lon="n.lon")
    db.execute(f"""INSERT INTO stage.obs SELECT w.key, w.base, w.name, {cell}, n.lat, n.lon, NULL, NULL
                   FROM scratch.ways w JOIN scratch.nodes n ON n.id = w.node""")
    db.execute(f"""INSERT INTO stage.obs SELECT a.key, a.base, a.name, {cell}, n.lat, n.lon, a.region, a.postcode
                   FROM scratch.addrs a JOIN scratch.nodes n ON n.id = a.node""")
    db.execute(f"""INSERT INTO stage.points SELECT a.key, {cell}, a.num, a.numtext, a.unit, n.lat, n.lon, a.postcode, 'osm'
                   FROM scratch.addrs a JOIN scratch.nodes n ON n.id = a.node""")
    b.commit()
    found = db.execute("SELECT count(*) FROM scratch.nodes").fetchone()[0]
    prog.done(f" in {len(windows)} pass(es); {need - found:,} of {need:,} nodes missing from the file")
    b.reset_scratch("")
    b.sources.append({"name": "osm", "file": path.name, "bytes": path.stat().st_size, "roads": roads, "points": points,
                      "ways": n_ways, "addresses": n_addr, "attribution": ATTRIBUTION["osm"]})
    return {"ways": n_ways, "addresses": n_addr}


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


def merge(b: Build) -> dict[str, int]:
    """Staging rows -> final tables: one street per (key, cell), then ranges and points
    joined to their street ids."""
    db = b.db
    t = time.monotonic()
    log(f"merging streets (staged: {fmt_bytes(b.stage['stage'].stat().st_size)}) ...")
    b.begin()
    # the fullest name (and its point) wins; region/postcode come from any source that has one.
    # Two regions for one (key, cell) (State St on the TN/VA line, border towns) stay "" through
    # the neighbour fill below and end as NULL, so neither side's addresses get filtered out.
    db.execute("""
        INSERT INTO streets(key, base, name, cell, lat, lon, region, postcode)
        SELECT key, base, name, cell, lat, lon, region, postcode FROM (
            SELECT key, base, name, cell, lat, lon,
                   CASE WHEN max(region) OVER w IS NULL OR min(region) OVER w = max(region) OVER w
                        THEN max(region) OVER w ELSE '' END AS region,
                   max(postcode) OVER w AS postcode,
                   row_number() OVER (PARTITION BY key, cell ORDER BY length(name) DESC, name) AS rn
            FROM stage.obs
            WINDOW w AS (PARTITION BY key, cell)
        ) WHERE rn = 1 ORDER BY key, cell""")
    # OSM-only streets get the region most streets in their cell have, else in the 8 cells around it
    db.execute("""CREATE TEMP TABLE cell_region AS
                  SELECT cell, region, max(n) AS n FROM (SELECT cell, region, count(*) AS n FROM streets
                                                         WHERE region IS NOT NULL AND region <> ''
                                                         GROUP BY cell, region) GROUP BY cell""")
    db.execute("CREATE UNIQUE INDEX temp.cell_region_cell ON cell_region(cell)")
    db.execute("""UPDATE streets SET region = (SELECT region FROM temp.cell_region c WHERE c.cell = streets.cell)
                  WHERE region IS NULL""")
    around = ", ".join(f"streets.cell + {d}" for d in (-3601, -3600, -3599, -1, 1, 3599, 3600, 3601))
    db.execute(f"""UPDATE streets SET region = (SELECT region FROM temp.cell_region c WHERE c.cell IN ({around})
                                                ORDER BY n DESC LIMIT 1)
                   WHERE region IS NULL""")
    db.execute("DROP TABLE temp.cell_region")
    db.execute("UPDATE streets SET region = NULL WHERE region = ''")
    db.execute("CREATE INDEX streets_key ON streets(key, cell)")
    db.execute("CREATE INDEX streets_base ON streets(base, cell)")
    b.commit()
    log(f"  streets: {db.execute('SELECT count(*) FROM streets').fetchone()[0]:,} ({time.monotonic() - t:.0f} s)")

    t = time.monotonic()
    b.begin()
    db.execute("""INSERT INTO ranges SELECT s.id, r.lo, r.hi, r.parity, r.rev, r.postcode, r.geom
                  FROM stage.ranges r JOIN streets s ON s.key = r.key AND s.cell = r.cell""")
    # exact duplicates (the same number and unit on the same street) keep one row, NAR first
    db.execute("""INSERT INTO points SELECT sid, num, numtext, unit, lat, lon, postcode, source FROM (
                      SELECT s.id AS sid, p.num, p.numtext, p.unit, p.lat, p.lon, p.postcode, p.source,
                             row_number() OVER (PARTITION BY s.id, p.numtext, p.unit ORDER BY p.source) AS rn
                      FROM stage.points p JOIN streets s ON s.key = p.key AND s.cell = p.cell
                  ) WHERE rn = 1""")
    b.commit()
    staged = {k: db.execute(f"SELECT count(*) FROM stage.{k}").fetchone()[0] for k in ("ranges", "points")}
    counts = {k: db.execute(f"SELECT count(*) FROM {k}").fetchone()[0] for k in ("ranges", "points")}
    if counts["ranges"] != staged["ranges"]:
        raise RuntimeError(f"{staged['ranges'] - counts['ranges']:,} ranges found no street; the merge is broken")
    log(f"  ranges: {counts['ranges']:,}; points: {counts['points']:,} ({staged['points'] - counts['points']:,} "
        f"duplicates dropped) ({time.monotonic() - t:.0f} s)")
    db.execute("DETACH DATABASE stage")
    b.stage["stage"].unlink(missing_ok=True)

    t = time.monotonic()
    b.begin()
    # Canadian postal codes and FSAs: the mean of the register's points
    for code in ("p.postcode", "substr(p.postcode, 1, 3)"):
        db.execute(f"""INSERT OR IGNORE INTO postcodes
                       SELECT {code}, CAST(round(avg(p.lat)) AS INTEGER), CAST(round(avg(p.lon)) AS INTEGER), max(s.region)
                       FROM points p JOIN streets s ON s.id = p.sid
                       WHERE p.source = 'nar' AND p.postcode IS NOT NULL GROUP BY 1""")
    db.execute("CREATE INDEX ranges_sid ON ranges(sid, lo)")
    db.execute("CREATE INDEX points_sid ON points(sid, num)")
    b.commit()
    log(f"  postcodes + indexes ({time.monotonic() - t:.0f} s)")
    return {k: db.execute(f"SELECT count(*) FROM {k}").fetchone()[0] for k in ("streets", "ranges", "points", "postcodes")}


def finish(b: Build, counts: dict[str, int]) -> Path:
    db = b.db
    meta = {"norm_version": str(VERSION),
            "built_at": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
            "sources": json.dumps(b.sources, ensure_ascii=False),
            "attribution": "; ".join(dict.fromkeys(s["attribution"] for s in b.sources)),
            **{k: str(v) for k, v in counts.items()}}
    db.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)", meta.items())
    log("ANALYZE ...")
    db.execute("PRAGMA analysis_limit = 2000")
    db.execute("ANALYZE")
    b.close()
    for p in b.stage.values():
        p.unlink(missing_ok=True)
    shutil.rmtree(b.tmpdir, ignore_errors=True)
    b.out.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(b.path, b.out)
        b.out.with_name(b.out.name + ".new").unlink(missing_ok=True)
        return b.out
    except PermissionError:
        pending = b.out.with_name(b.out.name + ".new")
        os.replace(b.path, pending)
        log(f"{b.out.name} is in use (Mimi is running?); the new index is {pending.name} and Mimi installs it on its next start")
        return pending


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tiger", type=Path, help="TIGER address ranges, Nominatim's preprocessed .csv.tar.gz")
    ap.add_argument("--zips", type=Path, help="US ZIP centroids, postcode,lat,lon .csv.gz")
    ap.add_argument("--nar", type=Path, help="Statistics Canada National Address Register .zip")
    ap.add_argument("--nar-provinces", nargs="+", metavar="CODE", help="NAR province codes to load (default: all)")
    ap.add_argument("--osm-roads", nargs="+", type=Path, default=[], metavar="PBF", help="OSM files whose named roads become streets")
    ap.add_argument("--osm-points", nargs="+", type=Path, default=[], metavar="PBF", help="OSM files whose addr:* objects become points")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"output file (default: {DEFAULT_OUT})")
    ap.add_argument("--limit-rows", type=int, metavar="N", help="read at most N rows/objects from each source (for testing)")
    args = ap.parse_args(argv)
    if not (args.tiger or args.zips or args.nar or args.osm_roads or args.osm_points):
        args.tiger, args.zips, args.nar = (p if p.is_file() else None for p in (DEFAULTS["tiger"], DEFAULTS["zips"], DEFAULTS["nar"]))
        args.osm_roads = [p for p in DEFAULTS["osm_roads"] if p.is_file()]
        if not (args.tiger or args.zips or args.nar or args.osm_roads):
            ap.error("no inputs given and none of the default inputs exist under .tools/dl")
    return args


def check_disk(args: argparse.Namespace) -> None:
    """Refuse to start when the output disk can't hold the scratch files plus the index."""
    need = 256 << 20
    inputs = [("tiger", args.tiger), ("zips", args.zips), ("nar", args.nar)] + \
        [("osm_roads", p) for p in args.osm_roads] + [("osm_points", p) for p in args.osm_points]
    for kind, p in inputs:
        if p is None:
            continue
        if not p.is_file():
            raise SystemExit(f"input not found: {p}")
        size = p.stat().st_size * DISK_FACTORS[kind]
        need += min(size, args.limit_rows * 2000) if args.limit_rows else size * 1.1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(args.out.parent).free
    if free < need:
        raise SystemExit(f"not enough disk space on {args.out.parent}: the build needs about {fmt_bytes(need)} "
                         f"of scratch and output space, {fmt_bytes(free)} is free")
    log(f"disk: about {fmt_bytes(need)} needed, {fmt_bytes(free)} free")


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    args = parse_args(argv)
    check_disk(args)
    saved_env = {v: os.environ.get(v) for v in TMP_VARS}
    b = Build(args.out.resolve())
    try:
        b.open()
        if args.tiger:
            load_tiger(b, args.tiger, args.limit_rows)
        if args.zips:
            load_zips(b, args.zips, args.limit_rows)
        if args.nar:
            load_nar(b, args.nar, args.nar_provinces, args.limit_rows)
        for p in dict.fromkeys(args.osm_roads + args.osm_points):
            load_osm(b, p, p in args.osm_roads, p in args.osm_points, args.limit_rows)
        counts = merge(b)
        out = finish(b, counts)
    except BaseException:
        b.abort()
        raise
    finally:
        for var, value in saved_env.items():
            if value is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = value
    log(f"wrote {out} ({fmt_bytes(out.stat().st_size)}): " + ", ".join(f"{v:,} {k}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
