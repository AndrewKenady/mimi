#!/usr/bin/env python3
"""Download Mimi's engines, models, offline library and maps, and verify every byte.

    python scripts/fetch.py --only runtimes            # llama.cpp, kiwix-serve, pmtiles for this OS
    python scripts/fetch.py --tier lite                # a whole tier (manifests/lite.json)
    python scripts/fetch.py                            # the standard tier (manifests/standard.json)
    python scripts/fetch.py --only models zim          # just some groups of the tier
    python scripts/fetch.py --tier lite --region uk    # map region (manifests/regions.json)
    python scripts/fetch.py --dry-run                  # show what would be downloaded
    python scripts/fetch.py --hash URL [URL ...]       # maintainers: print size + sha256 for a manifest

Groups: runtimes, models, zim, maps, geodata, routing, addresses. For day-to-day
content changes use scripts/content.py (list / status / add / remove), which adds
size and free-space checks on top of this.

Integrity. Engines, models and other static files are pinned (release tags, Hugging
Face commit revisions) and carry a sha256 in the manifest. ZIM files resolve to the
newest release of each book in the Kiwix catalog and are checked against the
sha-256 in Kiwix's metalink. Every download goes to <name>.part first, resumes with
an HTTP Range request if it was interrupted, is verified, and only then renamed to
its final name - so a file under its final name is always complete.

Uses aria2c (multi-connection, multi-mirror) when it is installed or bundled, and
Python's own HTTP client otherwise. Stdlib only: runs on any Python 3.11+.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "manifests"
USER_AGENT = "Mimi-installer/1 (+https://github.com/AndrewKenady/mimi)"
KIWIX_CATALOG = "https://library.kiwix.org/catalog/v2/entries?count=-1"
PROTOMAPS_BUILDS = "https://build-metadata.protomaps.dev/builds.json"
PROTOMAPS_BASE = "https://build.protomaps.com/"
# Pinned planet build (Protomaps keeps the last build of every schema version). If it is
# ever pruned, the newest build is used instead, with a warning.
PROTOMAPS_BUILD = "20260811.pmtiles"
GROUPS = ("runtimes", "models", "zim", "maps", "geodata", "routing", "addresses")
CHUNK = 1 << 20
MB = 1_000_000
GB = 1_000_000_000


class DownloadError(Exception):
    """The file could not be fetched from any source."""


class IntegrityError(DownloadError):
    """The file arrived, but its size or hash is wrong (it has been deleted)."""


# --------------------------------------------------------------------------- places
def content_root() -> Path:
    """Where models/, zim/ and maps/ live: MIMI_CONTENT, else the Mimi folder (see core/mimi/paths.py)."""
    env = os.environ.get("MIMI_CONTENT")
    return Path(env).resolve() if env else ROOT


def cache_dir() -> Path:
    """Downloads that are only inputs (archives, OSM extracts): on the content drive, it has the room."""
    return content_root() / ".tools" / "dl"


def state_file() -> Path:
    return content_root() / ".tools" / "content.json"


def load_state() -> dict:
    try:
        return json.loads(state_file().read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    f = state_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), "utf-8")
    os.replace(tmp, f)


def platform_key(system: str | None = None, machine: str | None = None) -> str:
    """win-x64, linux-x64, linux-arm64, macos-arm64 (same rule as core/mimi/paths.py:platform_key)."""
    system = (system or sys.platform).lower()
    machine = (machine or platform.machine() or "").lower()
    os_name = "win" if system.startswith("win") else ("macos" if system == "darwin" else "linux")
    arch = "arm64" if machine in ("arm64", "aarch64", "armv8", "armv8l") else "x64"
    return f"{os_name}-{arch}"


def bin_dir(plat: str | None = None) -> Path:
    return ROOT / "bin" / (plat or platform_key())


def tool(name: str, plat: str | None = None) -> Path | None:
    """A bundled tool (bin/<platform>/<name>) or one on PATH."""
    plat = plat or platform_key()
    exe = name + (".exe" if plat.startswith("win") else "")
    p = bin_dir(plat) / exe
    if p.exists():
        return p
    found = shutil.which(name)
    return Path(found) if found else None


def mimi_python() -> str:
    """The Python Mimi runs with (it has osmium/pyvalhalla for the map builds), else this one."""
    for p in (ROOT / "python" / "bin" / "python", ROOT / "python" / "python.exe", ROOT / "python" / "Scripts" / "python.exe"):
        if p.exists():
            return str(p)
    return sys.executable


def fmt_size(n: float | None) -> str:
    if n is None:
        return "size unknown"
    if n >= GB:
        return f"{n / GB:,.1f} GB"
    if n >= MB:
        return f"{n / MB:,.0f} MB"
    return f"{n / 1000:,.0f} kB"


def say(*a: object) -> None:
    print(*a, flush=True)


# --------------------------------------------------------------------------- downloading
def _open(url: str, start: int = 0, timeout: float = 60):
    headers = {"User-Agent": USER_AGENT}
    if start:
        headers["Range"] = f"bytes={start}-"
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout)


def fetch_bytes(url: str, timeout: float = 120) -> bytes:
    with _open(url, timeout=timeout) as r:
        return r.read()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(CHUNK * 4):
            h.update(b)
    return h.hexdigest()


def verify_file(path: Path, sha256: str | None, size: int | None) -> None:
    """Raise IntegrityError if `path` isn't exactly the file the manifest describes."""
    actual = path.stat().st_size
    if size is not None and actual != size:
        raise IntegrityError(f"{path.name}: expected {size:,} bytes, got {actual:,}")
    if sha256:
        if actual > 2 * GB:
            say(f"    verifying {path.name} ({fmt_size(actual)}) …")
        got = sha256_file(path)
        if got.lower() != sha256.lower():
            raise IntegrityError(f"{path.name}: sha256 mismatch (expected {sha256}, got {got})")


class _Progress:
    def __init__(self, total: int | None, have: int):
        self.total, self.start_have, self.t0, self.last = total, have, time.time(), 0.0
        self.tty = sys.stdout.isatty()

    def update(self, have: int, final: bool = False) -> None:
        now = time.time()
        if not final and now - self.last < (0.5 if self.tty else 30):
            return
        self.last = now
        rate = (have - self.start_have) / max(now - self.t0, 1e-6)
        pct = f" {100 * have / self.total:5.1f}%" if self.total else ""
        line = f"    {fmt_size(have)}{' / ' + fmt_size(self.total) if self.total else ''}{pct}  {rate / MB:6.1f} MB/s"
        if self.tty:
            sys.stdout.write("\r" + line + ("\n" if final else ""))
            sys.stdout.flush()
        elif not final:
            say(line)


def _http_resume(url: str, part: Path, size: int | None) -> None:
    """Fetch url into `part`, continuing from whatever part already holds."""
    ctl = part.with_name(part.name + ".aria2")
    if ctl.exists():  # aria2 writes segments out of order: the length says nothing, start over
        part.unlink(missing_ok=True)
        ctl.unlink()
    have = part.stat().st_size if part.exists() else 0
    if size is not None and have > size:
        part.unlink()
        have = 0
    if size is not None and have == size:
        return
    try:
        r = _open(url, start=have)
    except urllib.error.HTTPError as e:
        if e.code != 416 or not have:
            raise
        if size is None:
            return  # the server says we already have it all; the hash check decides
        part.unlink()
        have = 0
        r = _open(url)
    with r:
        if have and r.status == 206:
            m = re.match(r"bytes (\d+)-", r.headers.get("Content-Range", ""))
            if not m or int(m.group(1)) != have:
                raise DownloadError(f"server answered the wrong range ({r.headers.get('Content-Range')})")
            mode = "ab"
        else:
            have, mode = 0, "wb"  # no Range support (or a fresh start): from the beginning
        length = r.headers.get("Content-Length")
        expected = have + int(length) if length and length.isdigit() else size
        prog = _Progress(size or expected, have)
        with open(part, mode) as f:
            while True:
                chunk = r.read(CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                have += len(chunk)
                prog.update(have)
        prog.update(have, final=True)
    if expected is not None and have < expected:
        raise DownloadError(f"connection closed after {have:,} of {expected:,} bytes")


def find_aria2() -> Path | None:
    if os.environ.get("MIMI_NO_ARIA2"):
        return None
    return tool("aria2c")


def _aria2(aria2: Path, urls: list[str], part: Path, sha256: str | None) -> None:
    cmd = [str(aria2), "-x8", "-s8", "-k4M", "--continue=true", "--max-tries=10", "--retry-wait=15", "--file-allocation=none",
           "--auto-file-renaming=false", "--allow-overwrite=false", "--console-log-level=warn", "--summary-interval=30",
           "-d", str(part.parent), "-o", part.name]
    if sha256:
        cmd.append(f"--checksum=sha-256={sha256}")
    ca = os.environ.get("SSL_CERT_FILE")
    if ca:
        cmd.append(f"--ca-certificate={ca}")
    subprocess.run(cmd + urls, check=True)
    part.with_name(part.name + ".aria2").unlink(missing_ok=True)


def download(url: str, dest: Path, *, sha256: str | None = None, size: int | None = None, mirrors: list[str] | tuple = (),
             dry: bool = False, retries: int = 4, label: str | None = None) -> bool:
    """Download url to dest, atomically and verified. Returns True if dest is in place (or would be, when dry).

    An existing dest is trusted only if its size matches the manifest; a file left
    truncated by an older Mimi (which wrote straight to the final name) is resumed.
    """
    dest = Path(dest)
    part = dest.with_name(dest.name + ".part")
    shown = label or _rel(dest)
    ctl = dest.with_name(dest.name + ".aria2")
    if dest.exists() and ctl.exists() and not dry:
        # An older Mimi's interrupted aria2 download: only aria2 can finish that (sparse) file.
        if find_aria2() and not part.exists():
            dest.replace(part)
            ctl.replace(part.with_name(part.name + ".aria2"))
        else:
            dest.unlink()
            ctl.unlink()
    if dest.exists():
        have = dest.stat().st_size
        if (size is None and have > 0) or have == size:
            say(f"  ✓ {shown}")
            return True
        if size is not None and 0 < have < size and not part.exists():
            say(f"  ! {shown} is incomplete ({fmt_size(have)} of {fmt_size(size)}); resuming")
            if not dry:
                dest.replace(part)
        elif not dry:
            say(f"  ! {shown} has the wrong size; downloading it again")
            dest.unlink()
    resumed = part.stat().st_size if part.exists() else 0
    say(f"  ↓ {shown}  ({fmt_size(size)}{', resuming at ' + fmt_size(resumed) if resumed else ''})")
    if dry:
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    sources = [url, *[m for m in mirrors if m != url]]
    errors: list[str] = []
    aria2 = find_aria2()
    done = False
    if aria2 and (size is None or size > 16 * MB):
        try:
            _aria2(aria2, sources[:8], part, sha256)
            done = True
        except (subprocess.CalledProcessError, OSError) as e:
            errors.append(f"aria2c: {e}")
    if not done:
        for attempt in range(retries + 1):
            src = sources[attempt % len(sources)]
            try:
                _http_resume(src, part, size)
                done = True
                break
            except (urllib.error.URLError, OSError, http.client.HTTPException, DownloadError) as e:
                errors.append(f"{src}: {e}")
                if isinstance(e, urllib.error.HTTPError) and e.code in (403, 404, 410) and len(sources) == 1:
                    break
                time.sleep(min(30, 2 ** attempt))
    if not done:
        raise DownloadError(f"could not download {shown}:\n    " + "\n    ".join(errors[-4:]))
    try:
        verify_file(part, sha256, size)
    except IntegrityError:
        part.unlink(missing_ok=True)
        raise
    os.replace(part, dest)
    return True


def _rel(p: Path) -> str:
    for base in (content_root(), ROOT):
        try:
            return Path(p).resolve().relative_to(base).as_posix()
        except ValueError:
            continue
    return str(p)


# --------------------------------------------------------------------------- archives
def _safe_parts(name: str) -> list[str] | None:
    p = PurePosixPath(name.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts:
        return None
    return [x for x in p.parts if x not in ("", ".")]


def _members(archive: Path):
    """Yield (parts, kind, data_fn, mode, linkname) for each archive member; kind: file, dir, symlink."""
    name = archive.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                parts = _safe_parts(info.filename)
                if parts is None:
                    raise DownloadError(f"unsafe path in {archive.name}: {info.filename}")
                mode = (info.external_attr >> 16) & 0o777
                yield parts, ("dir" if info.is_dir() else "file"), (lambda i=info: zf.read(i)), mode, None
    elif name.endswith((".tar.gz", ".tgz", ".tar.xz", ".tar")):
        with tarfile.open(archive) as tf:
            for m in tf:
                parts = _safe_parts(m.name)
                if parts is None:
                    raise DownloadError(f"unsafe path in {archive.name}: {m.name}")
                if m.isdir():
                    yield parts, "dir", None, m.mode, None
                elif m.issym():
                    yield parts, "symlink", None, m.mode, m.linkname
                elif m.isfile():
                    yield parts, "file", (lambda m=m: tf.extractfile(m).read()), m.mode, None  # type: ignore[union-attr]
                elif m.islnk():
                    target = _safe_parts(m.linkname)
                    yield parts, "hardlink", None, m.mode, "/".join(target or [])
    else:
        raise DownloadError(f"don't know how to unpack {archive.name}")


def _write(out: Path, data: bytes, mode: int) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    if os.name != "nt":
        if not mode:  # zip without unix modes: executables have no extension; libraries need +x too
            mode = 0o755 if (out.suffix == "" or ".so" in out.suffixes or out.suffix == ".dylib") else 0o644
        os.chmod(out, mode | 0o600)


def extract_tree(archive: Path, dest: Path, strip_root: bool = False, only: list[str] | None = None) -> None:
    """Unpack `archive` into a fresh `dest` (atomically replacing any old one).

    strip_root drops the archive's single top folder; `only` keeps members whose path
    (after stripping) starts with one of these prefixes.
    """
    tmp = dest.with_name(f".{dest.name}.unpacking")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    links: list[tuple[Path, str, str]] = []
    for parts, kind, data, mode, link in _members(archive):
        if strip_root:
            parts = parts[1:]
        if not parts:
            continue
        rel = "/".join(parts)
        if only and not any(rel.startswith(o) for o in only):
            continue
        out = tmp.joinpath(*parts)
        if kind == "dir":
            out.mkdir(parents=True, exist_ok=True)
        elif kind == "file":
            _write(out, data(), mode)
        elif kind in ("symlink", "hardlink"):
            links.append((out, kind, link or ""))
    for out, kind, link in links:
        if kind == "symlink":
            target = (out.parent / link).resolve()
            if not str(target).startswith(str(tmp.resolve())) or os.name == "nt":
                continue  # never point outside the tree (and Windows needs no .so links)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.unlink(missing_ok=True)
            os.symlink(link, out)
        else:
            src_parts = link.split("/")[1:] if strip_root else link.split("/")
            src = tmp.joinpath(*src_parts)
            if src.exists():
                shutil.copy2(src, out)
    old = dest.with_name(f".{dest.name}.old")
    shutil.rmtree(old, ignore_errors=True)
    if dest.exists():
        dest.rename(old)
    tmp.rename(dest)
    shutil.rmtree(old, ignore_errors=True)


def extract_files(archive: Path, mapping: dict[str, Path]) -> None:
    """Pull single files out of an archive: {member basename: output path}."""
    wanted = dict(mapping)
    for parts, kind, data, mode, _ in _members(archive):
        if kind != "file" or not parts or parts[-1] not in wanted:
            continue
        out = wanted.pop(parts[-1])
        tmp = out.with_name(out.name + ".tmp")
        _write(tmp, data(), (mode or 0) | 0o755)  # these are always programs
        os.replace(tmp, out)
    if wanted:
        raise DownloadError(f"{archive.name} has no {', '.join(wanted)}")


# --------------------------------------------------------------------------- runtimes
def runtimes_for(plat: str) -> list[dict]:
    m = json.loads((MANIFESTS / "runtimes.json").read_text("utf-8"))
    if plat not in m["platforms"]:
        raise SystemExit(f"No Mimi engines are published for {plat} yet (have: {', '.join(m['platforms'])}).")
    return m["platforms"][plat]


def runtime_targets(r: dict) -> list[Path]:
    return [ROOT / r["unzip_to"]] if r.get("unzip_to") else [ROOT / o for o in r["extract"].values()]


def install_runtimes(plat: str | None = None, dry: bool = False, force: bool = False) -> None:
    plat = plat or platform_key()
    stamps_file = bin_dir(plat) / ".installed.json"
    try:
        stamps = json.loads(stamps_file.read_text("utf-8"))
    except (OSError, ValueError):
        stamps = {}
    used: set[Path] = set()
    for r in runtimes_for(plat):
        targets = runtime_targets(r)
        present = all(t.exists() for t in targets)
        stamp = stamps.get(r["id"])
        if present and not force and (stamp == r["sha256"] or stamp is None):
            # An unstamped engine was installed by an older setup; keep it (see --force).
            say(f"  ✓ {r['id']}" + ("" if stamp else " (installed earlier; --force re-installs and verifies it)"))
            continue
        archive = cache_dir() / "runtimes" / r["url"].rsplit("/", 1)[-1]
        download(r["url"], archive, sha256=r["sha256"], size=r.get("size"), dry=dry, label=f"{r['id']}: {archive.name}")
        if dry:
            continue
        if r.get("unzip_to"):
            extract_tree(archive, ROOT / r["unzip_to"], strip_root=bool(r.get("strip_root")))
        else:
            extract_files(archive, {k: ROOT / v for k, v in r["extract"].items()})
        stamps[r["id"]] = r["sha256"]
        stamps_file.parent.mkdir(parents=True, exist_ok=True)
        stamps_file.write_text(json.dumps(stamps, indent=1), "utf-8")
        used.add(archive)
        say(f"  ✓ {r['id']} → {', '.join(_rel(t) for t in targets)}")
    for a in used:
        a.unlink(missing_ok=True)


# --------------------------------------------------------------------------- manifests
def load_json(name: str) -> dict:
    return json.loads((MANIFESTS / name).read_text("utf-8"))


def tier_names() -> list[str]:
    return sorted(p.stem for p in MANIFESTS.glob("*.json") if "packs" in json.loads(p.read_text("utf-8")) and p.stem != "packs")


def load_tier(name_or_path: str) -> dict:
    """A tier manifest with `extends` resolved: {'edition', 'title', 'region', 'packs': [...]}."""
    p = Path(name_or_path)
    if not p.suffix:
        p = MANIFESTS / f"{name_or_path}.json"
    if not p.exists():
        raise SystemExit(f"No tier called {name_or_path!r} (have: {', '.join(tier_names())}).")
    m = json.loads(p.read_text("utf-8"))
    if "packs" not in m:
        raise SystemExit(f"{p.name} is not a tier manifest (it has no 'packs' list).")
    packs: list[str] = []
    if m.get("extends"):
        base = load_tier(m["extends"])
        packs += base["packs"]
        m.setdefault("region", base.get("region"))
    packs += [x for x in m["packs"] if x not in packs]
    return {**m, "packs": packs}


def all_packs() -> dict[str, dict]:
    return load_json("packs.json")["packs"]


def regions() -> dict:
    return load_json("regions.json")


def resolve_region(name: str | None = None, bbox: str | list | None = None, state: dict | None = None, tier: dict | None = None) -> dict:
    """The map region as a dict with at least name, title, bbox."""
    R = regions()
    if bbox:
        b = [float(x) for x in (bbox.split(",") if isinstance(bbox, str) else bbox)]
        if len(b) != 4 or not (-180 <= b[0] < b[2] <= 180 and -90 <= b[1] < b[3] <= 90):
            raise SystemExit("--bbox needs west,south,east,north in degrees, e.g. -111.1,40.9,-104.0,45.1")
        return {"name": name or "custom", "title": f"Custom area {','.join(str(x) for x in b)}", "bbox": b,
                "countries": [], "geofabrik": [], "map_mb": {}, "custom": True}
    state = state or {}
    if not name and state.get("region"):
        saved = state["region"]
        if saved.get("custom"):
            return saved
        name = saved.get("name")
    name = name or (tier or {}).get("region") or R["default"]
    if name not in R["regions"]:
        raise SystemExit(f"Unknown region {name!r}. Choose one of: {', '.join(R['regions'])} - or pass --bbox W,S,E,N.")
    return {"name": name, **R["regions"][name]}


# --------------------------------------------------------------------------- content items
_catalog: dict[str, str] | None = None


def kiwix_latest() -> dict[str, str]:
    """{book name: metalink URL of its newest file} from the Kiwix catalog (fetched once per run)."""
    global _catalog
    if _catalog is None:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        latest: dict[str, str] = {}
        for e in ET.fromstring(fetch_bytes(KIWIX_CATALOG, timeout=300)).findall("a:entry", ns):
            for link in e.findall("a:link", ns):
                href = link.get("href") or ""
                if "acquisition" in (link.get("rel") or "") and href.endswith(".zim.meta4"):
                    fname = href.rsplit("/", 1)[-1][: -len(".meta4")]
                    base = re.sub(r"_\d{4}-\d{2}\.zim$", "", fname)
                    if base not in latest or fname > latest[base].rsplit("/", 1)[-1]:
                        latest[base] = href
        _catalog = latest
    return _catalog


def parse_metalink(xml: bytes) -> dict:
    """name, size, sha256 and mirror URLs (by priority) from a Metalink 4 document."""
    ns = {"m": "urn:ietf:params:xml:ns:metalink"}
    f = ET.fromstring(xml).find("m:file", ns)
    if f is None:
        raise DownloadError("metalink has no file")
    size = f.findtext("m:size", namespaces=ns)
    sha = next((h.text for h in f.findall("m:hash", ns) if (h.get("type") or "").lower() in ("sha-256", "sha256")), None)
    urls = sorted(f.findall("m:url", ns), key=lambda u: int(u.get("priority") or 999))
    return {"name": f.get("name"), "size": int(size) if size else None, "sha256": sha, "urls": [u.text.strip() for u in urls if u.text]}


def protomaps_source() -> str:
    builds = json.loads(fetch_bytes(PROTOMAPS_BUILDS))
    keys = [b["key"] for b in builds]
    if PROTOMAPS_BUILD in keys:
        return PROTOMAPS_BASE + PROTOMAPS_BUILD
    say(f"  ! Protomaps build {PROTOMAPS_BUILD} is no longer published; using the newest, {keys[-1]}")
    return PROTOMAPS_BASE + keys[-1]


@dataclass
class Item:
    """One thing a pack puts on disk."""

    pack: str
    group: str
    spec: dict
    region: dict
    size: int | None = None  # bytes it will take (download or build output)
    exact: bool = False  # size is known exactly (pinned file)
    temporary: bool = False  # an input deleted after its pack is built
    label: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def kind(self) -> str:
        return self.spec["type"]

    # -- where things go -------------------------------------------------------
    def path(self, rel: str) -> Path:
        return content_root() / rel

    def targets(self) -> list[Path]:
        k, s, c = self.kind, self.spec, content_root()
        if k == "file":
            return [self.path(s["path"])]
        if k == "zim":
            return sorted(p for p in (c / "zim").glob(f"{s['name']}_*.zim") if re.fullmatch(re.escape(s["name"]) + r"_\d{4}-\d{2}\.zim", p.name))
        if k == "archive":
            return [self.path(s["path"])]
        if k == "world":
            return [c / "maps" / "world.pmtiles", c / "maps" / "world.json"]
        if k == "tiles":
            return [c / "maps" / "tiles.pmtiles", c / "maps" / "tiles.json"]
        if k == "build":
            return [self.path(o) for o in s["outputs"]]
        raise ValueError(k)

    def installed(self) -> bool:
        k, s = self.kind, self.spec
        if k == "file":
            p = self.path(s["path"])
            return p.exists() and (s.get("size") is None or p.stat().st_size == s["size"])
        if k == "zim":
            return bool(self.targets())
        if k == "archive":
            return all((self.path(s["path"]) / d).exists() for d in s.get("subdirs") or [""])
        if k == "world":
            f = content_root() / "maps" / "world.pmtiles"
            meta = _read_json(content_root() / "maps" / "world.json")
            # world.pmtiles from before world.json existed was always zoom 0-11
            return f.exists() and int(meta.get("maxzoom", 11)) >= s["maxzoom"]
        if k == "tiles":
            f = content_root() / "maps" / "tiles.pmtiles"
            meta = _read_json(content_root() / "maps" / "tiles.json")
            if not f.exists():
                return False
            same_area = meta.get("region") == self.region["name"] if meta.get("region") else _same_bbox(meta.get("bounds"), self.region["bbox"])
            return same_area and int(meta.get("maxzoom", 0)) >= s["maxzoom"]
        if k == "build":
            return all(self.path(o).exists() for o in s["outputs"])
        return False

    def conflict(self) -> str | None:
        """A different map region is installed; adding this one replaces it."""
        if self.kind != "tiles":
            return None
        meta = _read_json(content_root() / "maps" / "tiles.json")
        if (content_root() / "maps" / "tiles.pmtiles").exists() and meta and not self.installed():
            have = meta.get("region") or ("bbox " + ",".join(map(str, meta.get("bounds") or [])))
            if have != self.region["name"]:
                return f"replaces the installed map region ({have}) with {self.region['name']}"
        return None

    def partial_bytes(self) -> int:
        """Bytes already downloaded towards this item (resumable .part files)."""
        n = 0
        for t in self.targets() if self.kind != "zim" else []:
            part = t.with_name(t.name + ".part")
            if part.exists():
                n += part.stat().st_size
        if self.kind == "zim":
            n += sum(p.stat().st_size for p in (content_root() / "zim").glob(f"{self.spec['name']}_*.zim.part"))
        return n

    # -- getting it ------------------------------------------------------------
    def fetch(self, dry: bool) -> None:
        getattr(self, f"_fetch_{self.kind}")(dry)

    def _fetch_file(self, dry: bool) -> None:
        s = self.spec
        download(s["url"], self.path(s["path"]), sha256=s.get("sha256"), size=s.get("size"), dry=dry)

    def _fetch_zim(self, dry: bool) -> None:
        name = self.spec["name"]
        have = self.targets()
        if dry:
            say(f"  ✓ {have[-1].name}" if have else f"  ↓ {name} (newest from the Kiwix catalog, ~{fmt_size(self.size)})")
            return
        try:
            href = kiwix_latest().get(name)
        except (urllib.error.URLError, OSError, ET.ParseError) as e:
            if have:  # offline: keep what's there
                say(f"  ✓ {have[-1].name} (couldn't reach the Kiwix catalog to check it: {e})")
                return
            raise DownloadError(f"couldn't read the Kiwix catalog: {e}") from e
        if not href:
            if have:
                say(f"  ✓ {have[-1].name} (no longer in the Kiwix catalog)")
                return
            raise DownloadError(f"{name} is not in the Kiwix catalog any more; pick another book in manifests/packs.json")
        fname = href.rsplit("/", 1)[-1][: -len(".meta4")]
        if have and fname not in {p.name for p in have}:
            say(f"  ✓ {have[-1].name} (newer: {fname}; updating books is not automatic yet)")
            return
        meta = parse_metalink(fetch_bytes(href))
        if not meta["sha256"]:
            raise IntegrityError(f"Kiwix's metalink for {name} has no sha-256 to check the download against")
        # Also re-checks a same-named file by size, so one an older Mimi left truncated gets finished.
        download(href[: -len(".meta4")], content_root() / "zim" / meta["name"], sha256=meta["sha256"], size=meta["size"], mirrors=meta["urls"])

    def _fetch_archive(self, dry: bool) -> None:
        s = self.spec
        if self.installed():
            say(f"  ✓ {s['path']}")
            return
        archive = cache_dir() / "archives" / s["url"].rsplit("/", 1)[-1]
        download(s["url"], archive, sha256=s.get("sha256"), size=s.get("size"), dry=dry, label=f"{s['path']} ({archive.name})")
        if dry:
            return
        extract_tree(archive, self.path(s["path"]), strip_root=True, only=s.get("subdirs"))
        archive.unlink(missing_ok=True)

    def _pmtiles(self) -> Path:
        exe = tool("pmtiles")
        if not exe:
            raise DownloadError("pmtiles isn't installed; run: python scripts/fetch.py --only runtimes")
        return exe

    def _extract_map(self, out: Path, args: list[str], meta_file: Path, meta: dict, dry: bool) -> None:
        if dry:
            return
        exe = self._pmtiles()
        src = protomaps_source()
        part = out.with_name(out.name + ".part")
        out.parent.mkdir(parents=True, exist_ok=True)
        part.unlink(missing_ok=True)  # pmtiles extract can't resume; start clean
        subprocess.run([str(exe), "extract", src, str(part), *args, "--download-threads=8"], check=True)
        r = subprocess.run([str(exe), "verify", str(part)], capture_output=True, text=True)
        if r.returncode != 0:
            part.unlink(missing_ok=True)
            raise IntegrityError(f"{out.name}: the extracted map failed `pmtiles verify`: {(r.stdout + r.stderr).strip()[-300:]}")
        os.replace(part, out)
        meta_file.write_text(json.dumps({**meta, "source": f"Protomaps {src.rsplit('/', 1)[-1].split('.')[0]}"}), "utf-8")

    def map_args(self) -> list[str]:
        if self.kind == "world":
            return [f"--maxzoom={self.spec['maxzoom']}"]
        return [f"--bbox={','.join(str(x) for x in self.region['bbox'])}", f"--maxzoom={self.spec['maxzoom']}"]

    def measure(self) -> int | None:
        """Ask pmtiles how big this map extract will be (a few seconds, no download)."""
        exe = tool("pmtiles")
        if not exe or self.kind not in ("world", "tiles"):
            return None
        try:
            r = subprocess.run([str(exe), "extract", protomaps_source(), os.devnull, *self.map_args(), "--dry-run"],
                               capture_output=True, text=True, timeout=300)
        except (OSError, subprocess.SubprocessError, urllib.error.URLError):
            return None
        m = re.search(r"archive size of ([\d.]+)\s*(B|kB|KB|MB|GB|TB)", r.stdout + r.stderr)
        if not m:
            return None
        self.size = int(float(m.group(1)) * {"B": 1, "kB": 1e3, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}[m.group(2)])
        return self.size

    def _fetch_world(self, dry: bool) -> None:
        z = self.spec["maxzoom"]
        if self.installed():
            say(f"  ✓ maps/world.pmtiles (zoom 0-{z}+)")
            return
        say(f"  ↓ maps/world.pmtiles: the whole planet, zoom 0-{z} (~{fmt_size(self.size)})")
        c = content_root() / "maps"
        self._extract_map(c / "world.pmtiles", self.map_args(), c / "world.json", {"maxzoom": z}, dry)

    def _fetch_tiles(self, dry: bool) -> None:
        z, reg = self.spec["maxzoom"], self.region
        if self.installed():
            say(f"  ✓ maps/tiles.pmtiles ({reg['title']}, zoom 0-{z}+)")
            return
        say(f"  ↓ maps/tiles.pmtiles: {reg['title']}, zoom 0-{z} (~{fmt_size(self.size)})")
        c = content_root() / "maps"
        self._extract_map(c / "tiles.pmtiles", self.map_args(), c / "tiles.json",
                          {"bounds": reg["bbox"], "maxzoom": z, "region": reg["name"], "title": reg["title"]}, dry)

    def build_args(self) -> list[str]:
        reg, c = self.region, content_root()
        out: list[str] = []
        for a in self.spec["args"]:
            if a == "{geofabrik}":
                out += reg.get("geofabrik") or []
            elif a == "{inputs}":  # the pack's downloaded inputs, as --flag path pairs
                for it in pack_items(self.pack, reg):
                    if it.kind == "file" and it.spec.get("arg"):
                        out += [it.spec["arg"], str(it.path(it.spec["path"]))]
            else:
                out.append(a.replace("{countries}", ",".join(reg.get("countries") or [])).replace("{maps}", str(c / "maps"))
                           .replace("{cache}", str(cache_dir())).replace("{content}", str(c)))
        return out

    def _fetch_build(self, dry: bool) -> None:
        s = self.spec
        if self.installed():
            say(f"  ✓ {', '.join(s['outputs'])}")
            return
        cmd = [mimi_python(), str(ROOT / s["script"]), *self.build_args()]
        say(f"  ⚙ {' '.join(s['outputs'])}: {Path(s['script']).name} {' '.join(cmd[2:])}")
        if dry:
            return
        env = dict(os.environ, PYTHONUTF8="1")
        subprocess.run(cmd, check=True, cwd=str(ROOT), env=env)


def _read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _same_bbox(a, b) -> bool:
    return bool(a and b) and all(abs(float(x) - float(y)) < 1e-6 for x, y in zip(a, b))


def pack_items(pack_id: str, region: dict) -> list[Item]:
    packs = all_packs()
    if pack_id not in packs:
        raise SystemExit(f"Unknown pack {pack_id!r}. See: python scripts/content.py list")
    p = packs[pack_id]
    countries = set(region.get("countries") or [])
    items: list[Item] = []
    for s in p["items"]:
        if s.get("countries") and not countries.intersection(s["countries"]):
            continue
        it = Item(pack=pack_id, group=p["group"], spec=s, region=region, temporary=bool(s.get("temporary")))
        k = s["type"]
        if k == "file":
            it.size, it.exact, it.label = s.get("size"), s.get("size") is not None, s["path"]
        elif k == "zim":
            it.size, it.label = int(s["size_mb"] * MB), s["name"]
        elif k == "archive":
            it.size, it.label = int(s.get("size_mb", 0) * MB), s["path"]
        elif k == "world":
            wmb = regions().get("world_mb", {}).get(str(s["maxzoom"]))
            it.size, it.label = (int(wmb * MB) if wmb else None), f"world map, zoom 0-{s['maxzoom']}"
        elif k == "tiles":
            mb = (region.get("map_mb") or {}).get(str(s["maxzoom"]))
            it.size, it.label = (int(mb * MB) if mb else None), f"{region['title']} map, zoom 0-{s['maxzoom']}"
        elif k == "build":
            mb = s.get("size_mb")
            if isinstance(mb, str):
                mb = region.get(mb)
            it.size = int(mb * MB) if mb else None
            it.label = ", ".join(s["outputs"])
            if s.get("download_mb"):
                it.notes.append(f"downloads ~{fmt_size(s['download_mb'] * MB)} of source data")
        items.append(it)
    return items


def pack_problem(pack_id: str, region: dict) -> str | None:
    """Why a pack can't be installed for this region (None if it can)."""
    p = all_packs()[pack_id]
    if p.get("requires_region") and not region.get(p["requires_region"]):
        return f"{p['title']} is only available for regions with that data (US and Canada)"
    if pack_id == "routing" and not region.get("geofabrik"):
        return "routing needs OpenStreetMap extracts for the region (named regions only, or pass --geofabrik)"
    if pack_id == "places" and not region.get("countries"):
        return "the places database needs country codes for the region (named regions only, or pass --countries)"
    return None


def plan(pack_ids: list[str], region: dict, groups: list[str] | None = None) -> list[Item]:
    """Every item of these packs, de-duplicated: the most detailed world/region map wins."""
    items: list[Item] = []
    for pid in pack_ids:
        for it in pack_items(pid, region):
            if groups and it.group not in groups:
                continue
            items.append(it)
    out: list[Item] = []
    for kind in ("world", "tiles"):
        same = [i for i in items if i.kind == kind]
        if len(same) > 1:
            best = max(same, key=lambda i: i.spec["maxzoom"])
            items = [i for i in items if i.kind != kind or i is best]
    seen: set = set()
    for it in items:
        key = (it.kind, json.dumps(it.spec, sort_keys=True))
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


def run(items: list[Item], dry: bool = False) -> list[str]:
    """Fetch/build everything in order; returns error messages (one per failed pack)."""
    errors: list[str] = []
    failed: set[str] = set()
    by_pack: dict[str, list[Item]] = {}
    for it in items:
        by_pack.setdefault(it.pack, []).append(it)
    current = None
    for it in items:
        if it.pack in failed:
            continue
        if it.pack != current:
            current = it.pack
            say(f"[{it.pack}] {all_packs()[it.pack]['title']}")
        try:
            if it.kind == "build":
                it.fetch(dry)
                if not dry:
                    for t in by_pack[it.pack]:  # the build's inputs aren't needed any more
                        if t.temporary:
                            for p in t.targets():
                                p.unlink(missing_ok=True)
            elif it.temporary and all(i.installed() for i in by_pack[it.pack] if i.kind == "build"):
                continue  # its pack is built already: don't fetch the inputs again
            else:
                it.fetch(dry)
        except (DownloadError, subprocess.CalledProcessError, OSError) as e:
            failed.add(it.pack)
            errors.append(f"{it.pack}: {e}")
            say(f"  ✗ {e}")
    return errors


# --------------------------------------------------------------------------- CLI
def bbox_argv(argv: list[str] | None) -> list[str]:
    """Let `--bbox -111.1,40.9,-104.0,45.1` through argparse (a leading minus looks like an option)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    out: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--bbox" and i + 1 < len(argv):
            out.append(f"--bbox={argv[i + 1]}")
            i += 2
            continue
        out.append(argv[i])
        i += 1
    return out


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tier", help="lite or standard (default: standard)")
    ap.add_argument("--manifest", help="path to a tier manifest (instead of --tier)")
    ap.add_argument("--only", nargs="*", choices=GROUPS, help="just these groups")
    ap.add_argument("--region", help="map region, see manifests/regions.json")
    ap.add_argument("--bbox", help="custom map area west,south,east,north (instead of --region)")
    ap.add_argument("--platform", help="engines for this platform instead of this machine's (e.g. linux-arm64)")
    ap.add_argument("--force", action="store_true", help="re-install engines even if present")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--hash", nargs="+", metavar="URL", help="print size and sha256 of these URLs (for manifest maintainers)")
    args = ap.parse_args(bbox_argv(argv))

    if args.hash:
        for url in args.hash:
            h, n = hashlib.sha256(), 0
            with _open(url, timeout=300) as r:
                while b := r.read(CHUNK):
                    h.update(b)
                    n += len(b)
            say(json.dumps({"url": url, "size": n, "sha256": h.hexdigest()}))
        return 0

    groups = args.only or list(GROUPS)
    errors: list[str] = []
    if "runtimes" in groups:
        say(f"[runtimes] engines for {args.platform or platform_key()}")
        try:
            install_runtimes(args.platform, dry=args.dry_run, force=args.force)
        except DownloadError as e:
            errors.append(f"runtimes: {e}")
            say(f"  ✗ {e}")
    content_groups = [g for g in groups if g != "runtimes"]
    if content_groups:
        tier = load_tier(args.manifest or args.tier or "standard")
        state = load_state()
        region = resolve_region(args.region, args.bbox, state, tier)
        packs = [p for p in tier["packs"] if not pack_problem(p, region)]
        errors += run(plan(packs, region, content_groups), dry=args.dry_run)
        if not args.dry_run:
            state["region"] = region
            save_state(state)
    if errors:
        say("\nSome downloads failed (run the same command again to resume):\n  " + "\n  ".join(errors))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
