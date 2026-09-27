#!/usr/bin/env python3
"""Build MIMI's offline geodata databases (``maps/places.sqlite``, ``maps/geowiki.sqlite``).

MIMI (Machine Intelligence, Minus the Internet) answers "where am I?" and "what's
near me?" with no network connection. This script turns two public datasets into
compact, indexed SQLite files. They are queried by ``core/mimi/geodata.py``.

places.sqlite: GeoNames gazetteer (default countries: US, CA)
    Source   https://download.geonames.org/export/dump/
             <CC>.zip, admin1CodesASCII.txt, featureCodes_en.txt
    License  Creative Commons Attribution 4.0 (CC BY 4.0)
             Attribution: "Place data (c) GeoNames (CC BY 4.0)"
    Tables   places        one row per GeoNames feature (id = geonameid)
             places_rtree  R*Tree over the points (minlat = maxlat, minlon = maxlon)
             places_fts    FTS5 over name/asciiname (external content = places)
             admin1        (country, code) -> state/province name
             meta          key/value build information and attribution
    Notes    * places.elevation is GeoNames' surveyed ``elevation`` when present,
               else the SRTM/GTOPO ``dem`` value (metres). NULL if neither exists.
             * places.admin1 holds the human name ('Kentucky'), not the code.
             * Features that have no class or code are kept. fdesc is 'locale'
               when only the class is 'S', which is what GNIS calls them.
             * Dropped as noise (see DROP_FCODES): R.RDJCT road junctions and
               freeway interchanges ("Exit 5A"), and S.SWT sewage treatment
               plants. Together that is about 16k of 2.56M US+CA rows.

geowiki.sqlite: coordinates of English Wikipedia articles (global)
    Source   https://dumps.wikimedia.org/enwiki/<date>/
             enwiki-<date>-geo_tags.sql.gz (GeoData extension table) and
             enwiki-<date>-page.sql.gz, both taken from the same dump run
    License  Wikipedia content is CC BY-SA 4.0.
             Attribution: "Wikipedia geotags, CC BY-SA 4.0"
    Tables   geo           one row per article: gt_globe='earth', gt_primary=1,
                           page_namespace=0, not a redirect
             geo_rtree     R*Tree over the points
             geo_fts       FTS5 over the title (external content = geo)
             meta          key/value build information and attribution
    Notes    * geo.path is the page title with underscores, exactly as in
               Wikipedia URLs. It is also the article path inside the Kiwix
               wikipedia_en ZIM files.
             * geo.type is the {{coord}} ``type:`` parameter, normalised: lower
               case, with any "(population)" or ":region" suffix removed.
             * geo.page_len is the article length in bytes. It is not part of
               GeoData; it comes from the page table and is used as a rough
               notability signal when ranking.

Both dumps are streamed; nothing is loaded into memory whole. The Wikipedia
join keeps one bit per page id (a bitmap of about 10 MB) plus SQLite staging
tables on disk. On a handheld PC (2026 data), places takes about 1 minute and
geowiki about 4-5 minutes, most of it parsing the 66M-row page table. Peak
memory is about 230 MB. Downloads come to about 80 MB (GeoNames) plus 2.4 GB
(Wikipedia). dumps.wikimedia.org throttles downloads, often to a few hundred
KB/s, so a mirror with the same files is usually much faster. The dump date
and MD5 sums always come from the official site.

Usage (from the repository root, with MIMI's portable Python):

    python\\python.exe scripts\\build_geodata.py                  # download + build both
    python\\python.exe scripts\\build_geodata.py --only places
    python\\python.exe scripts\\build_geodata.py --skip-download  # reuse files in the work dir
    python\\python.exe scripts\\build_geodata.py --wiki-mirror https://mirror.accum.se/mirror/wikimedia.org/dumps

Downloads go to ``.tools/dl/geodata/`` and are resumed if interrupted. They are
deleted after a successful build unless ``--keep-downloads`` is given. Outputs
are built in the work dir and then moved into ``maps/`` in one step, so a failed
run never leaves a half-written database behind. Re-running the script is safe:
it simply rebuilds. The MySQL dump parser is exact: it cross-checks its fast
path and falls back to a token-level parser, and each build ends with spot
checks of well-known places.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import gzip
import hashlib
import http.client
import io
import json
import operator
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Iterable, Iterator, Sequence

# --------------------------------------------------------------------------
# Locations and constants
# --------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]  # scripts/ -> repository root
DEFAULT_MAPS_DIR = ROOT / "maps"
DEFAULT_WORK_DIR = ROOT / ".tools" / "dl" / "geodata"

GEONAMES_BASE = "https://download.geonames.org/export/dump"
WIKI_OFFICIAL = "https://dumps.wikimedia.org"  # RSS feeds and md5sums always come from here
WIKI_NAME = "enwiki"
USER_AGENT = "MIMI-geodata-builder/1.0 (offline assistant; scripts/build_geodata.py)"

SCHEMA_VERSION = 1
PLACES_ATTRIBUTION = "Place data © GeoNames (CC BY 4.0)"
WIKI_ATTRIBUTION = "Wikipedia geotags, CC BY-SA 4.0"

# GeoNames feature codes dropped as low-value noise ("<class>.<code>": reason).
DROP_FCODES = {
    "R.RDJCT": "road junction / freeway interchange (e.g. 'Exit 5A', 'Interchange 40')",
    "S.SWT": "sewage treatment plant",
}

FTS_TOKENIZER = "unicode61 remove_diacritics 2"

# --------------------------------------------------------------------------
# Small utilities
# --------------------------------------------------------------------------

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


def utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def hilbert_key(lat: float, lon: float) -> int:
    """Position of a point on a 65536 x 65536 Hilbert curve.

    Inserting R-tree entries in this order puts neighbouring points into the
    same nodes. The build is fast, and the tree comes out about as compact as
    with random insertion (measured on GeoNames US+CA: 146 MB vs 138-155 MB for
    other orders)."""
    n = 1 << 16
    x = int((lon + 180.0) * ((n - 1) / 360.0))
    y = int((lat + 90.0) * ((n - 1) / 180.0))
    d = 0
    s = n >> 1
    while s:
        rx = 1 if x & s else 0
        ry = 1 if y & s else 0
        d += s * s * ((3 * rx) ^ ry)
        if not ry:  # rotate the quadrant
            if rx:
                x, y = n - 1 - x, n - 1 - y
            x, y = y, x
        s >>= 1
    return d


def open_build_db(path: Path) -> sqlite3.Connection:
    """A fast, crash-unsafe connection for building (the output is rebuilt from
    scratch if anything goes wrong, so durability is irrelevant)."""
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA locking_mode = EXCLUSIVE")
    conn.execute("PRAGMA cache_size = -65536")  # 64 MB page cache; keeps memory modest
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.create_function("hilbert", 2, hilbert_key, deterministic=True)
    return conn


def write_meta(conn: sqlite3.Connection, items: dict[str, object]) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.executemany(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        [(k, v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)) for k, v in items.items()],
    )


def finalize_db(conn: sqlite3.Connection, build_path: Path, final_path: Path) -> Path:
    """Optimise, compact into ``<final>.tmp`` with VACUUM INTO, then swap it into place.

    On Windows a database that a running MIMI has open cannot be replaced. In
    that case the finished file is kept as ``<final>.new``, and
    ``mimi.geodata.GeoData`` installs it the next time it opens the maps
    directory while the old file is not in use (normally the next MIMI start).
    Returns the path that was written.
    """
    log("  ANALYZE + VACUUM INTO final file ...")
    conn.execute("ANALYZE")
    conn.commit()
    final_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = final_path.with_name(final_path.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    conn.execute("VACUUM INTO ?", (str(tmp),))
    conn.close()
    build_path.unlink(missing_ok=True)
    for attempt in range(3):
        try:
            os.replace(tmp, final_path)
            final_path.with_name(final_path.name + ".new").unlink(missing_ok=True)  # superseded
            log(f"  wrote {final_path} ({fmt_bytes(final_path.stat().st_size)})")
            return final_path
        except PermissionError:
            time.sleep(1 + attempt)
    pending = final_path.with_name(final_path.name + ".new")
    os.replace(tmp, pending)
    log(f"  NOTE: {final_path.name} is in use (is MIMI running?). The new database was saved as {pending}")
    log(f"        ({fmt_bytes(pending.stat().st_size)}) and will be installed the next time MIMI starts.")
    return pending


# --------------------------------------------------------------------------
# Downloading (resumable, with optional MD5 verification)
# --------------------------------------------------------------------------


class DownloadError(RuntimeError):
    pass


def _request(url: str, method: str = "GET", headers: dict[str, str] | None = None) -> urllib.request.Request:
    h = {"User-Agent": USER_AGENT}
    if headers:
        h.update(headers)
    return urllib.request.Request(url, method=method, headers=h)


def fetch_text(url: str, timeout: float = 60) -> str:
    with urllib.request.urlopen(_request(url), timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def remote_info(url: str) -> tuple[int | None, str | None]:
    """(Content-Length, Last-Modified) of a URL via HEAD."""
    try:
        with urllib.request.urlopen(_request(url, "HEAD"), timeout=60) as r:
            size = r.headers.get("Content-Length")
            return (int(size) if size else None), r.headers.get("Last-Modified")
    except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
        raise DownloadError(f"cannot reach {url}: {e}") from e


def file_md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(url: str, dest: Path, md5: str | None = None) -> dict[str, object]:
    """Download ``url`` to ``dest`` unless an identical-size copy is already there.

    Partial data is kept in ``<dest>.part`` and resumed with HTTP Range requests.
    Returns a small provenance record (url, size, last_modified).
    """
    size, modified = remote_info(url)
    info = {"url": url, "size": size, "last_modified": modified}
    if dest.exists() and size is not None and dest.stat().st_size == size:
        log(f"  {dest.name}: already downloaded ({fmt_bytes(size)})")
        return info
    part = dest.with_name(dest.name + ".part")
    failures = 0
    while True:
        have = part.stat().st_size if part.exists() else 0
        if size is not None and have > size:
            part.unlink()
            have = 0
        if size is not None and have == size:
            break
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with urllib.request.urlopen(_request(url, headers=headers), timeout=60) as r:
                if have and r.status != 206:  # server ignored the Range header: start over
                    have = 0
                if have:
                    log(f"  {dest.name}: resuming at {fmt_bytes(have)}")
                else:
                    log(f"  {dest.name}: downloading {fmt_bytes(size) if size else '(unknown size)'} from {url}")
                with open(part, "ab" if have else "wb") as out:
                    _copy_with_progress(r, out, have, size, dest.name)
            if size is None:
                break
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            failures += 1
            if failures > 8:
                raise DownloadError(f"giving up on {url}: {e}") from e
            log(f"  {dest.name}: interrupted ({e}); retrying in {5 * failures}s")
            time.sleep(5 * failures)
    if md5:
        log(f"  {dest.name}: verifying MD5 ...")
        got = file_md5(part)
        if got != md5:
            part.unlink()
            raise DownloadError(f"MD5 mismatch for {dest.name}: got {got}, expected {md5} (partial file deleted)")
    os.replace(part, dest)
    return info


def _copy_with_progress(src, out, have: int, total: int | None, label: str) -> None:
    done, last, t_start = have, time.monotonic(), time.monotonic()
    while True:
        block = src.read(1 << 20)
        if not block:
            break
        out.write(block)
        done += len(block)
        now = time.monotonic()
        if now - last >= 5:
            rate = (done - have) / max(now - t_start, 1e-6)
            pct = f" ({100 * done / total:.0f}%)" if total else ""
            log(f"    {label}: {fmt_bytes(done)}{pct} at {fmt_bytes(rate)}/s")
            last = now


# --------------------------------------------------------------------------
# Streaming reader for MySQL / MariaDB dump files
# --------------------------------------------------------------------------
#
# Wikimedia's table dumps are gzipped mysqldump/mariadb-dump output:
#
#     CREATE TABLE `page` ( `page_id` int(8) ..., ... );
#     INSERT INTO `page` VALUES (10,0,'AccessibleComputing',1,...),(12,0,'Anarchism',...);
#
# Older dumps put a whole multi-row INSERT on one (very long) line; newer ones put
# one tuple per line. Values are integers, decimals, NULL or single-quoted strings
# with backslash escapes (\\ \' \" \n \r \t \0 \Z). Raw newlines never appear
# inside a value, so a tuple never spans lines, but titles freely contain commas,
# quotes and parentheses. Naive splitting on "),(" is therefore wrong.
#
# Fast path: one compiled regex matches an entire tuple, with exactly one
# alternative per column (a quoted string or a bare token) and capture groups
# only for the wanted columns. Matches must tile the line: only commas or
# whitespace may sit between consecutive tuples, and only "," or ";" may follow
# the last one. If anything else appears, the fast path has lost alignment, and
# the line is re-parsed by an exact token-level tokenizer (slow, but it never
# guesses). The fallback count is reported.

_SQL_STR = rb"'(?:[^'\\]++|\\.)*+'"  # quoted string; possessive = no backtracking
_SQL_BARE = rb"[^,'()]*+"  # number, NULL, 0x... literal
_SQL_TOKEN = re.compile(rb"\s++|" + _SQL_STR + rb"|[(),;]|[^,'()\s;]++|(.)", re.S)
_SQL_ESCAPES = {b"0": b"\x00", b"b": b"\x08", b"n": b"\n", b"r": b"\r", b"t": b"\t", b"Z": b"\x1a"}
_SQL_ESCAPE_RE = re.compile(rb"\\(.)", re.S)


def sql_bytes(raw: bytes) -> bytes | None:
    """Decode one raw SQL value: NULL -> None, 'quoted' -> unescaped bytes, else as-is."""
    if raw == b"NULL":
        return None
    if raw[:1] == b"'":
        s = raw[1:-1]
        if b"\\" in s:
            s = _SQL_ESCAPE_RE.sub(lambda m: _SQL_ESCAPES.get(m.group(1), m.group(1)), s)
        return s
    return raw


def sql_text(raw: bytes) -> str | None:
    b = sql_bytes(raw)
    return None if b is None else b.decode("utf-8", "replace")


def sql_int(raw: bytes) -> int | None:
    b = sql_bytes(raw)
    return None if b is None or b == b"" else int(b)


def sql_float(raw: bytes) -> float | None:
    b = sql_bytes(raw)
    return None if b is None or b == b"" else float(b)


class SqlDumpReader:
    """Iterate rows of one table in a gzipped SQL dump, yielding raw field bytes."""

    def __init__(self, path: Path, table: str) -> None:
        self.path = path
        self.table = table
        self.columns: list[str] = []
        self.rows_read = 0
        self.fallback_lines = 0
        self._fh: gzip.GzipFile | None = None
        self._raw = None

    def progress(self) -> float:
        """Fraction of the compressed file consumed so far (0..1)."""
        try:
            return self._raw.tell() / max(self.path.stat().st_size, 1)
        except Exception:
            return 0.0

    def rows(self, wanted: Sequence[str]) -> Iterator[tuple[bytes, ...]]:
        """Yield tuples of raw values (see ``sql_*`` helpers) for ``wanted`` columns, in that order."""
        # BufferedReader on top of GzipFile gives C-speed line splitting.
        with open(self.path, "rb") as raw, io.BufferedReader(gzip.GzipFile(fileobj=raw), 1 << 20) as fh:
            self._raw = raw
            self.columns = self._read_schema(fh)
            missing = [c for c in wanted if c not in self.columns]
            if missing:
                raise ValueError(f"{self.path.name}: table `{self.table}` has no column(s) {missing}; has {self.columns}")
            idx = [self.columns.index(c) for c in wanted]
            ordered = sorted(idx)
            positions = [ordered.index(i) for i in idx]
            reorder: Callable | None = None
            if idx != ordered:
                reorder = (lambda r: (r[positions[0]],)) if len(idx) == 1 else operator.itemgetter(*positions)
            n = len(self.columns)
            parts = [(rb"(" if i in idx else rb"(?:") + _SQL_STR + rb"|" + _SQL_BARE + rb")" for i in range(n)]
            tuple_re = re.compile(rb"\(" + rb",".join(parts) + rb"\)")
            insert_prefix = b"INSERT INTO `" + self.table.encode() + b"` VALUES"
            in_insert = False
            for line in fh:
                if line.startswith(b"("):
                    if not in_insert:
                        continue
                    pos = 0
                elif line.startswith(insert_prefix):
                    in_insert, pos = True, len(insert_prefix)
                else:
                    in_insert = False
                    continue
                rows = self._parse_fast(line, pos, tuple_re)
                if rows is None:
                    rows = self._parse_exact(line, pos, ordered)
                self.rows_read += len(rows)
                if reorder is None:
                    yield from rows
                else:
                    for r in rows:
                        yield reorder(r)
                if line.rstrip().endswith(b";"):
                    in_insert = False

    def _read_schema(self, fh: Iterable[bytes]) -> list[str]:
        """Consume lines through the CREATE TABLE statement and return column names."""
        start = b"CREATE TABLE `" + self.table.encode() + b"`"
        cols: list[str] = []
        inside = False
        for line in fh:
            if not inside:
                inside = line.startswith(start)
                continue
            s = line.strip()
            if s.startswith(b"`"):
                cols.append(s[1 : s.index(b"`", 1)].decode())
            elif s.startswith(b")"):
                return cols
        raise ValueError(f"{self.path.name}: no CREATE TABLE `{self.table}` statement found")

    @staticmethod
    def _parse_fast(line: bytes, pos: int, tuple_re: re.Pattern) -> list[tuple[bytes, ...]] | None:
        rows = []
        expect = pos
        for m in tuple_re.finditer(line, pos):
            s = m.start()
            if s != expect and line[expect:s].strip(b" \t\r\n,"):
                return None  # lost alignment: something unparsed between tuples
            rows.append(m.groups())
            expect = m.end()
        if line[expect:].strip(b" \t\r\n,;"):
            return None  # trailing unparsed text
        return rows

    def _parse_exact(self, line: bytes, pos: int, ordered: list[int]) -> list[tuple[bytes, ...]]:
        """Token-by-token parse of a VALUES list (reference implementation, slow)."""
        self.fallback_lines += 1
        rows: list[tuple[bytes, ...]] = []
        fields: list[bytes] | None = None
        for m in _SQL_TOKEN.finditer(line, pos):
            if m.group(1) is not None:
                raise ValueError(f"{self.path.name}: unexpected byte {m.group(1)!r} at offset {m.start()}")
            tok = m.group()
            if tok[:1].isspace():
                continue
            if tok == b"(":
                if fields is not None:
                    raise ValueError(f"{self.path.name}: nested '(' at offset {m.start()}")
                fields = []
            elif tok == b")":
                if fields is None or len(fields) != len(self.columns):
                    raise ValueError(f"{self.path.name}: bad tuple ending at offset {m.start()}: {fields!r}")
                rows.append(tuple(fields[i] for i in ordered))
                fields = None
            elif tok == b",":
                continue
            elif tok == b";":
                break
            elif fields is None:
                raise ValueError(f"{self.path.name}: value outside a tuple at offset {m.start()}")
            else:
                fields.append(tok)
        if fields is not None:
            raise ValueError(f"{self.path.name}: unterminated tuple: {line[pos:pos + 200]!r}")
        return rows


# --------------------------------------------------------------------------
# GeoNames -> places.sqlite
# --------------------------------------------------------------------------

PLACES_SCHEMA = f"""
CREATE TABLE places (
    id          INTEGER PRIMARY KEY,  -- GeoNames geonameid
    name        TEXT NOT NULL,
    asciiname   TEXT,
    lat         REAL NOT NULL,
    lon         REAL NOT NULL,
    fclass      TEXT,                 -- A H L P R S T U V (see geonames.org/export/codes.html)
    fcode       TEXT,                 -- e.g. PPL, PRK, LK, HSTS
    fdesc       TEXT,                 -- human label from featureCodes_en.txt, e.g. 'park'
    country     TEXT,                 -- ISO 3166-1 alpha-2
    admin1      TEXT,                 -- state / province name, e.g. 'Kentucky'
    population  INTEGER,
    elevation   INTEGER               -- metres (surveyed elevation, else DEM)
);
CREATE TABLE admin1 (
    country TEXT NOT NULL,
    code    TEXT NOT NULL,            -- GeoNames admin1 code ('KY' for US, '08' for Ontario)
    name    TEXT NOT NULL,
    PRIMARY KEY (country, code)
) WITHOUT ROWID;
CREATE VIRTUAL TABLE places_rtree USING rtree(id, minlat, maxlat, minlon, maxlon);
CREATE VIRTUAL TABLE places_fts USING fts5(
    name, asciiname, content='places', content_rowid='id', columnsize=0, tokenize='{FTS_TOKENIZER}'
);
"""


def load_feature_codes(path: Path) -> dict[str, str]:
    """'L.PRK' -> 'park' from featureCodes_en.txt."""
    codes = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2 and "." in parts[0]:
                codes[parts[0]] = parts[1].strip()
    return codes


def load_admin1(path: Path, countries: set[str]) -> list[tuple[str, str, str]]:
    """[(country, code, name)] from admin1CodesASCII.txt, restricted to ``countries``."""
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2 and "." in parts[0]:
                cc, code = parts[0].split(".", 1)
                if cc in countries:
                    rows.append((cc, code, parts[1].strip()))
    return rows


def iter_geonames(zip_path: Path, cc: str) -> Iterator[list[str]]:
    """Yield the 19 tab-separated fields of each line of <CC>.txt inside <CC>.zip.
    (GeoNames files are not CSV-quoted; names may contain '"' characters.)"""
    with zipfile.ZipFile(zip_path) as zf, zf.open(f"{cc}.txt") as fh:
        for line in io.TextIOWrapper(fh, encoding="utf-8", newline="\n"):
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) >= 17:
                yield fields


def build_places(args: argparse.Namespace) -> dict[str, object]:
    countries = [c.strip().upper() for c in args.countries.split(",") if c.strip()]
    work: Path = args.work_dir
    log(f"== places.sqlite: GeoNames {', '.join(countries)}")

    # -- 1. inputs
    names = ["admin1CodesASCII.txt", "featureCodes_en.txt"] + [f"{cc}.zip" for cc in countries]
    provenance: dict[str, object] = {}
    for name in names:
        dest = work / name
        if args.skip_download:
            if not dest.exists():
                raise SystemExit(f"--skip-download: {dest} is missing")
            provenance[name] = {"file": name, "size": dest.stat().st_size}
        else:
            provenance[name] = download(f"{GEONAMES_BASE}/{name}", dest)

    fdesc = load_feature_codes(work / "featureCodes_en.txt")
    admin1_rows = load_admin1(work / "admin1CodesASCII.txt", set(countries))
    admin1 = {(cc, code): name for cc, code, name in admin1_rows}

    # -- 2. load rows
    build_path = work / "places.build.sqlite"
    conn = open_build_db(build_path)
    conn.executescript(PLACES_SCHEMA)
    conn.executemany("INSERT INTO admin1 VALUES (?, ?, ?)", admin1_rows)

    kept = dropped = bad = 0
    dropped_by_code: dict[str, int] = {}
    batch: list[tuple] = []
    insert = "INSERT OR REPLACE INTO places VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
    for cc in countries:
        log(f"  reading {cc}.zip ...")
        for f in iter_geonames(work / f"{cc}.zip", cc):
            fclass, fcode = f[6].strip(), f[7].strip()
            key = f"{fclass}.{fcode}"
            if key in DROP_FCODES:
                dropped += 1
                dropped_by_code[key] = dropped_by_code.get(key, 0) + 1
                continue
            try:
                gid, lat, lon = int(f[0]), float(f[4]), float(f[5])
            except ValueError:
                bad += 1
                continue
            name = f[1].strip()
            if not name or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                bad += 1
                continue
            if fcode:
                desc = fdesc.get(key)
            else:
                desc = "locale" if fclass == "S" else None
            elev = f[15].strip()
            dem = f[16].strip()
            elevation = int(float(elev)) if elev else (int(float(dem)) if dem and dem != "-9999" else None)
            batch.append((
                gid, name, f[2].strip() or name, lat, lon,
                fclass or None, fcode or None, desc,
                f[8].strip() or cc, admin1.get((f[8].strip() or cc, f[10].strip())),
                int(f[14]) if f[14].strip() else 0, elevation,
            ))
            if len(batch) >= 50_000:
                conn.executemany(insert, batch)
                kept += len(batch)
                batch.clear()
        conn.executemany(insert, batch)
        kept += len(batch)
        batch.clear()
        log(f"    {kept:,} rows so far")
    conn.commit()
    log(f"  loaded {kept:,} places (dropped {dropped:,} noise rows: {dropped_by_code}; skipped {bad} malformed)")

    # -- 3. indexes
    log("  building indexes ...")
    conn.execute("CREATE INDEX idx_places_fcode ON places(fcode)")
    conn.execute("CREATE INDEX idx_places_fclass_pop ON places(fclass, population)")
    log("  building R-tree (Hilbert-order insertion) ...")
    conn.execute(
        "INSERT INTO places_rtree (id, minlat, maxlat, minlon, maxlon) "
        "SELECT id, lat, lat, lon, lon FROM places ORDER BY hilbert(lat, lon)"
    )
    conn.commit()
    log("  building FTS5 name index ...")
    conn.execute("INSERT INTO places_fts (places_fts, rank) VALUES ('hashsize', 67108864)")
    conn.execute("INSERT INTO places_fts (places_fts) VALUES ('rebuild')")
    conn.execute("INSERT INTO places_fts (places_fts) VALUES ('optimize')")
    conn.commit()

    # -- 4. sanity checks, then meta
    verify_places(conn, countries)
    by_class = dict(conn.execute("SELECT coalesce(fclass, '?'), count(*) FROM places GROUP BY 1 ORDER BY 1").fetchall())
    stats = {
        "places": kept,
        "by_class": by_class,
        "dropped_noise": dropped_by_code,
        "skipped_malformed": bad,
    }
    write_meta(conn, {
        "name": "MIMI places (GeoNames)",
        "schema_version": str(SCHEMA_VERSION),
        "source": "GeoNames geographical database, https://www.geonames.org/ (export/dump)",
        "source_files": provenance,
        "license": "CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)",
        "attribution": PLACES_ATTRIBUTION,
        "countries": ",".join(countries),
        "build_date": utc_now_iso(),
        "builder": "scripts/build_geodata.py",
        "row_count": str(kept),
        "row_counts_by_class": by_class,
        "dropped_fcodes": DROP_FCODES,
        "dropped_row_counts": dropped_by_code,
        "notes": "elevation = GeoNames elevation, else DEM; admin1 = human-readable name; "
                 "fdesc = featureCodes_en label ('locale' for class S without code)",
    })
    conn.commit()
    stats["file"] = str(finalize_db(conn, build_path, args.maps_dir / "places.sqlite"))
    return stats


def verify_places(conn: sqlite3.Connection, countries: list[str]) -> None:
    """Fail loudly if well-known features are missing or mangled."""
    checks = [
        ("US", "Washington", "PPLC", 38.895, -77.036, "District of Columbia"),
        ("US", "Mammoth Cave National Park", "PRK", 37.19, -86.10, "Kentucky"),
        ("CA", "Toronto", "PPLA", 43.706, -79.399, "Ontario"),
        ("CA", "CN Tower", "TOWR", 43.642, -79.387, "Ontario"),
    ]
    for cc, name, fcode, lat, lon, adm in checks:
        if cc not in countries:
            continue
        row = conn.execute(
            "SELECT p.lat, p.lon, p.admin1 FROM places_fts f JOIN places p ON p.id = f.rowid "
            "WHERE places_fts MATCH ? AND p.name = ? AND p.fcode = ?",
            ('"' + name.replace('"', "") + '"', name, fcode),
        ).fetchone()
        if not row or abs(row[0] - lat) > 0.05 or abs(row[1] - lon) > 0.05 or row[2] != adm:
            raise SystemExit(f"verification failed for {name} ({fcode}): got {row}")
    n = conn.execute(
        "SELECT count(*) FROM places_rtree WHERE minlat >= 38.8 AND maxlat <= 39.0 AND minlon >= -77.1 AND maxlon <= -76.9"
    ).fetchone()[0]
    if "US" in countries and n < 100:
        raise SystemExit(f"verification failed: only {n} places in the Washington DC R-tree box")
    log("  verification passed (FTS, R-tree, admin1 names)")


# --------------------------------------------------------------------------
# Wikipedia geotags -> geowiki.sqlite
# --------------------------------------------------------------------------

GEOWIKI_SCHEMA = f"""
CREATE TABLE geo (
    page_id   INTEGER PRIMARY KEY,   -- Wikipedia page id
    title     TEXT NOT NULL,         -- with spaces: 'Statue of Liberty'
    path      TEXT NOT NULL,         -- URL / Kiwix path: 'Statue_of_Liberty'
    lat       REAL NOT NULL,
    lon       REAL NOT NULL,
    type      TEXT,                  -- {{{{coord}}}} type: landmark, city, mountain, edu, ...
    dim       INTEGER,               -- approximate object size in metres
    country   TEXT,                  -- ISO 3166-1 alpha-2, when tagged
    region    TEXT,                  -- ISO 3166-2 subdivision suffix, when tagged
    page_len  INTEGER                -- article length in bytes (notability hint)
);
CREATE VIRTUAL TABLE geo_rtree USING rtree(id, minlat, maxlat, minlon, maxlon);
CREATE VIRTUAL TABLE geo_fts USING fts5(
    title, content='geo', content_rowid='page_id', columnsize=0, tokenize='{FTS_TOKENIZER}'
);
"""

_TYPE_CLEAN = re.compile(r"[\s(:].*$", re.S)


def normalize_wiki_type(raw: bytes) -> str | None:
    t = sql_text(raw)
    if not t:
        return None
    t = _TYPE_CLEAN.sub("", t.strip().lower())
    return t or None


def latest_wiki_dump_date() -> str:
    """Newest dump run for which both the page and geo_tags tables are published."""
    dates = []
    for table in ("page", "geo_tags"):
        url = f"{WIKI_OFFICIAL}/{WIKI_NAME}/latest/{WIKI_NAME}-latest-{table}.sql.gz-rss.xml"
        m = re.search(rf"/{WIKI_NAME}/(\d{{8}})", fetch_text(url))
        if not m:
            raise DownloadError(f"cannot find a dump date in {url}")
        dates.append(m.group(1))
    return min(dates)


def official_md5s(date: str) -> dict[str, str]:
    url = f"{WIKI_OFFICIAL}/{WIKI_NAME}/{date}/{WIKI_NAME}-{date}-md5sums.txt"
    try:
        sums = {}
        for line in fetch_text(url).splitlines():
            parts = line.split()
            if len(parts) == 2:
                sums[parts[1]] = parts[0]
        return sums
    except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
        log(f"  warning: could not fetch {url} ({e}); downloads will not be MD5-verified")
        return {}


def local_wiki_dump(work: Path, date: str | None) -> str:
    """Pick the dump date of already-downloaded files (for --skip-download)."""
    def have(d: str) -> bool:
        return all((work / f"{WIKI_NAME}-{d}-{t}.sql.gz").exists() for t in ("page", "geo_tags"))

    if date:
        if not have(date):
            raise SystemExit(f"--skip-download: dump files for {date} not found in {work}")
        return date
    found = sorted(
        {m.group(1) for p in work.glob(f"{WIKI_NAME}-*-page.sql.gz") if (m := re.search(r"-(\d{8})-", p.name))},
        reverse=True,
    )
    for d in found:
        if have(d):
            return d
    raise SystemExit(f"--skip-download: no complete {WIKI_NAME} page + geo_tags dump pair in {work}")


def build_geowiki(args: argparse.Namespace) -> dict[str, object]:
    work: Path = args.work_dir
    log(f"== geowiki.sqlite: {WIKI_NAME} geotags (global)")

    # -- 1. inputs (same dump run for both tables)
    provenance: dict[str, object] = {}
    if args.skip_download:
        date = local_wiki_dump(work, args.wiki_dump)
    else:
        date = args.wiki_dump or latest_wiki_dump_date()
        log(f"  using dump {WIKI_NAME}-{date} (mirror: {args.wiki_mirror})")
        md5s = official_md5s(date)
        for table in ("geo_tags", "page"):
            name = f"{WIKI_NAME}-{date}-{table}.sql.gz"
            url = f"{args.wiki_mirror.rstrip('/')}/{WIKI_NAME}/{date}/{name}"
            provenance[name] = download(url, work / name, md5=md5s.get(name))
    geo_path = work / f"{WIKI_NAME}-{date}-geo_tags.sql.gz"
    page_path = work / f"{WIKI_NAME}-{date}-page.sql.gz"
    for p in (geo_path, page_path):
        provenance.setdefault(p.name, {"file": p.name, "size": p.stat().st_size})

    build_path = work / "geowiki.build.sqlite"
    conn = open_build_db(build_path)
    conn.executescript(GEOWIKI_SCHEMA)
    conn.execute(
        "CREATE TABLE gt_stage (page_id INTEGER PRIMARY KEY, lat REAL, lon REAL, type TEXT, "
        "dim INTEGER, country TEXT, region TEXT)"
    )
    conn.execute("CREATE TABLE title_stage (page_id INTEGER PRIMARY KEY, title TEXT, len INTEGER)")

    # -- 2. geo_tags: primary coordinates on Earth
    log(f"  parsing {geo_path.name} ...")
    reader = SqlDumpReader(geo_path, "geo_tags")
    cols = ["gt_page_id", "gt_globe", "gt_primary", "gt_lat", "gt_lon", "gt_dim", "gt_type", "gt_country", "gt_region"]
    batch: list[tuple] = []
    n_primary = n_bad = 0
    max_pid = 0
    stage_sql = "INSERT OR IGNORE INTO gt_stage VALUES (?,?,?,?,?,?,?)"
    for pid, globe, primary, lat, lon, dim, typ, country, region in reader.rows(cols):
        if primary != b"1":
            continue
        g = sql_bytes(globe)
        if g is None or g.lower() != b"earth":
            continue
        la, lo = sql_float(lat), sql_float(lon)
        if la is None or lo is None or not (-90 <= la <= 90 and -180 <= lo <= 180):
            n_bad += 1
            continue
        page_id = int(pid)
        max_pid = max(max_pid, page_id)
        c, r = sql_text(country), sql_text(region)
        batch.append((page_id, la, lo, normalize_wiki_type(typ), sql_int(dim), (c or "").upper() or None, (r or "").upper() or None))
        n_primary += 1
        if len(batch) >= 50_000:
            conn.executemany(stage_sql, batch)
            batch.clear()
    conn.executemany(stage_sql, batch)
    batch.clear()
    conn.commit()
    n_stage = conn.execute("SELECT count(*) FROM gt_stage").fetchone()[0]
    log(f"  {reader.rows_read:,} geotag rows; {n_primary:,} primary on earth ({n_stage:,} distinct pages, "
        f"{n_bad} with invalid coordinates); fallback-parsed lines: {reader.fallback_lines}")

    # Membership bitmap of geotagged page ids: 1 bit per id (~10 MB for enwiki).
    bitmap = bytearray((max_pid >> 3) + 1)
    for (pid,) in conn.execute("SELECT page_id FROM gt_stage"):
        bitmap[pid >> 3] |= 1 << (pid & 7)
    nbits = len(bitmap) * 8

    # -- 3. page table: titles of geotagged, non-redirect articles (namespace 0)
    log(f"  parsing {page_path.name} (streaming ~{fmt_bytes(page_path.stat().st_size)} compressed) ...")
    reader = SqlDumpReader(page_path, "page")
    cols = ["page_id", "page_namespace", "page_title", "page_is_redirect", "page_len"]
    title_sql = "INSERT OR IGNORE INTO title_stage VALUES (?,?,?)"
    n_match = 0
    next_report = time.monotonic() + 15
    for pid, ns, title, redirect, plen in reader.rows(cols):
        if ns != b"0" or redirect != b"0":
            continue
        i = int(pid)
        if i >= nbits or not bitmap[i >> 3] & (1 << (i & 7)):
            continue
        batch.append((i, sql_text(title), sql_int(plen)))
        n_match += 1
        if len(batch) >= 50_000:
            conn.executemany(title_sql, batch)
            batch.clear()
            if time.monotonic() >= next_report:
                log(f"    {100 * reader.progress():4.1f}%  {reader.rows_read:,} page rows, {n_match:,} geotagged articles")
                next_report = time.monotonic() + 15
    conn.executemany(title_sql, batch)
    batch.clear()
    conn.commit()
    log(f"  {reader.rows_read:,} page rows; {n_match:,} geotagged articles; fallback-parsed lines: {reader.fallback_lines}")

    # -- 4. join into the final table
    log("  joining geotags with titles ...")
    conn.execute(
        "INSERT INTO geo (page_id, title, path, lat, lon, type, dim, country, region, page_len) "
        "SELECT g.page_id, replace(t.title, '_', ' '), t.title, g.lat, g.lon, g.type, g.dim, g.country, g.region, t.len "
        "FROM gt_stage g JOIN title_stage t ON t.page_id = g.page_id ORDER BY g.page_id"
    )
    n_geo = conn.execute("SELECT count(*) FROM geo").fetchone()[0]
    conn.execute("DROP TABLE gt_stage")
    conn.execute("DROP TABLE title_stage")
    conn.commit()
    log(f"  {n_geo:,} articles with coordinates ({n_stage - n_geo:,} geotagged pages skipped: "
        f"not in the article namespace, or redirects)")

    # -- 5. indexes
    log("  building indexes, R-tree and FTS5 title index ...")
    conn.execute("CREATE UNIQUE INDEX idx_geo_path ON geo(path)")
    conn.execute("CREATE INDEX idx_geo_type ON geo(type)")
    conn.execute(
        "INSERT INTO geo_rtree (id, minlat, maxlat, minlon, maxlon) "
        "SELECT page_id, lat, lat, lon, lon FROM geo ORDER BY hilbert(lat, lon)"
    )
    conn.execute("INSERT INTO geo_fts (geo_fts, rank) VALUES ('hashsize', 67108864)")
    conn.execute("INSERT INTO geo_fts (geo_fts) VALUES ('rebuild')")
    conn.execute("INSERT INTO geo_fts (geo_fts) VALUES ('optimize')")
    conn.commit()

    verify_geowiki(conn)
    types = dict(conn.execute(
        "SELECT coalesce(type, '(none)'), count(*) FROM geo GROUP BY 1 ORDER BY 2 DESC LIMIT 25"
    ).fetchall())
    stats = {"articles": n_geo, "geotags_primary_earth": n_stage, "top_types": types}
    write_meta(conn, {
        "name": "MIMI geowiki (English Wikipedia geotags)",
        "schema_version": str(SCHEMA_VERSION),
        "source": f"Wikimedia dumps {WIKI_NAME}-{date}: geo_tags + page tables, https://dumps.wikimedia.org/",
        "source_files": provenance,
        "dump_date": date,
        "license": "CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)",
        "attribution": WIKI_ATTRIBUTION,
        "build_date": utc_now_iso(),
        "builder": "scripts/build_geodata.py",
        "row_count": str(n_geo),
        "geotagged_pages_primary_earth": str(n_stage),
        "type_counts_top25": types,
        "filters": "gt_globe='earth' AND gt_primary=1; page_namespace=0 AND page_is_redirect=0",
        "notes": "path = title with underscores (Wikipedia URL / Kiwix article path); "
                 "page_len = article length in bytes",
    })
    conn.commit()
    stats["file"] = str(finalize_db(conn, build_path, args.maps_dir / "geowiki.sqlite"))
    return stats


def verify_geowiki(conn: sqlite3.Connection) -> None:
    """Spot-check known articles, including titles with commas, apostrophes and parentheses."""
    checks = [
        ("Statue of Liberty", 40.6892, -74.0445),
        ("Mammoth Cave National Park", 37.187, -86.100),
        ("CN Tower", 43.6426, -79.3871),
        ("Washington, D.C.", 38.9, -77.03),
        ("St. John's, Newfoundland and Labrador", 47.56, -52.71),
        ("Mount Rainier", 46.85, -121.76),
    ]
    for title, lat, lon in checks:
        row = conn.execute("SELECT lat, lon, path FROM geo WHERE path = ?", (title.replace(" ", "_"),)).fetchone()
        if not row or abs(row[0] - lat) > 0.2 or abs(row[1] - lon) > 0.2:
            raise SystemExit(f"verification failed for {title!r}: got {row}")
        hits = conn.execute(
            "SELECT count(*) FROM geo_fts WHERE geo_fts MATCH ? AND rowid IN (SELECT page_id FROM geo WHERE path = ?)",
            ('"' + title.replace('"', "") + '"', row[2]),
        ).fetchone()[0]
        if hits != 1:
            raise SystemExit(f"verification failed: FTS does not find {title!r}")
    n = conn.execute(
        "SELECT count(*) FROM geo_rtree WHERE minlat >= 40.6 AND maxlat <= 40.8 AND minlon >= -74.1 AND maxlon <= -73.9"
    ).fetchone()[0]
    if n < 500:
        raise SystemExit(f"verification failed: only {n} articles in the Manhattan R-tree box")
    log("  verification passed (titles with punctuation, FTS, R-tree)")


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def remove_downloads(work: Path, patterns: Sequence[str]) -> None:
    freed = 0
    for pat in patterns:
        for p in work.glob(pat):
            freed += p.stat().st_size
            p.unlink()
    if freed:
        log(f"  deleted downloaded files ({fmt_bytes(freed)})")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=("places", "geowiki"), help="build just one of the two databases")
    ap.add_argument("--skip-download", action="store_true", help="use files already in the work dir; no network")
    ap.add_argument("--keep-downloads", action="store_true", help="do not delete downloaded source files after building")
    ap.add_argument("--countries", default="US,CA", help="GeoNames country codes, comma-separated (default: US,CA)")
    ap.add_argument("--wiki-mirror", default=WIKI_OFFICIAL,
                    help="base URL of a Wikimedia dumps mirror, e.g. https://mirror.accum.se/mirror/wikimedia.org/dumps "
                         "(dump date and MD5 sums still come from dumps.wikimedia.org)")
    ap.add_argument("--wiki-dump", metavar="YYYYMMDD", help="use this dump run instead of the latest")
    ap.add_argument("--maps-dir", type=Path, default=DEFAULT_MAPS_DIR, help=f"output directory (default: {DEFAULT_MAPS_DIR})")
    ap.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR, help=f"download/scratch directory (default: {DEFAULT_WORK_DIR})")
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    args = parse_args(argv)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    args.maps_dir.mkdir(parents=True, exist_ok=True)
    log(f"repository root: {ROOT}")
    summary: dict[str, object] = {}
    try:
        if args.only in (None, "places"):
            summary["places"] = build_places(args)
            if not args.keep_downloads:
                countries = [c.strip().upper() for c in args.countries.split(",") if c.strip()]
                remove_downloads(args.work_dir, ["admin1CodesASCII.txt", "featureCodes_en.txt"] + [f"{c}.zip" for c in countries])
        if args.only in (None, "geowiki"):
            summary["geowiki"] = build_geowiki(args)
            if not args.keep_downloads:
                remove_downloads(args.work_dir, [f"{WIKI_NAME}-*-geo_tags.sql.gz", f"{WIKI_NAME}-*-page.sql.gz"])
    except DownloadError as e:
        log(f"ERROR: {e}")
        return 2
    for name, stats in summary.items():
        path = Path(stats.pop("file"))
        log(f"{path.name}: {fmt_bytes(path.stat().st_size)}  {json.dumps(stats, ensure_ascii=False)}")
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
