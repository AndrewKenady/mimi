"""Download Mimi's runtimes, models, offline library and maps from a manifest.

    python scripts/fetch.py                     # everything in manifests/standard.json
    python scripts/fetch.py --only models zim   # just some groups
    python scripts/fetch.py --dry-run           # show what would be downloaded

Uses the bundled aria2c (multi-connection, resumable, metalink-aware) when present.
Content comes from its original publishers: GitHub releases, Hugging Face, the
Kiwix library and Protomaps. Re-running is safe: finished files are skipped and
interrupted downloads resume.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARIA2 = ROOT / "bin" / "win-x64" / "aria2c.exe"
DL = ROOT / ".tools" / "dl"


def get(url: str, dest: Path, dry: bool) -> None:
    if dest.exists() and not dest.with_name(dest.name + ".aria2").exists() and dest.stat().st_size > 0:
        print(f"  ✓ {dest.relative_to(ROOT)}")
        return
    print(f"  ↓ {url}")
    if dry:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if ARIA2.exists():
        subprocess.run([str(ARIA2), "-x8", "-s8", "-k4M", "--continue=true", "--max-tries=0", "--retry-wait=15", "--file-allocation=none",
                        "--auto-file-renaming=false", "--follow-metalink=mem", "-q", "-d", str(dest.parent), "-o", dest.name, url], check=True)
    else:
        with urllib.request.urlopen(url) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)


def runtimes(m: dict, dry: bool) -> None:
    for r in m["runtimes"]:
        target = ROOT / (r.get("unzip_to") or next(iter(r["extract"].values())))
        if target.exists():
            print(f"  ✓ {r['id']}")
            continue
        z = DL / f"{r['id']}.zip"
        get(r["url"], z, dry)
        if dry:
            continue
        with zipfile.ZipFile(z) as zf:
            if "extract" in r:
                for member, out in r["extract"].items():
                    name = next(n for n in zf.namelist() if n.endswith(member))
                    (ROOT / out).parent.mkdir(parents=True, exist_ok=True)
                    (ROOT / out).write_bytes(zf.read(name))
            else:
                dest = ROOT / r["unzip_to"]
                dest.mkdir(parents=True, exist_ok=True)
                for info in zf.infolist():
                    name = info.filename.split("/", 1)[1] if r.get("strip_root") and "/" in info.filename else info.filename
                    if not name or info.is_dir():
                        continue
                    (dest / name).parent.mkdir(parents=True, exist_ok=True)
                    (dest / name).write_bytes(zf.read(info))


def models(m: dict, dry: bool) -> None:
    for item in m["models"]:
        if "hf_repo" in item:
            for f in item["files"]:
                get(f"https://huggingface.co/{item['hf_repo']}/resolve/main/{f}", ROOT / item["path"] / f, dry)
        else:
            get(item["url"], ROOT / item["path"], dry)


def zims(m: dict, dry: bool) -> None:
    cat = urllib.request.urlopen("https://library.kiwix.org/catalog/v2/entries?count=-1").read()
    ns = {"a": "http://www.w3.org/2005/Atom"}
    latest: dict[str, str] = {}
    for e in ET.fromstring(cat).findall("a:entry", ns):
        for link in e.findall("a:link", ns):
            href = link.get("href") or ""
            if "acquisition" in (link.get("rel") or "") and href.endswith(".zim.meta4"):
                fname = href.rsplit("/", 1)[-1][: -len(".meta4")]
                base = re.sub(r"_\d{4}-\d{2}\.zim$", "", fname)
                if base not in latest or fname > latest[base].rsplit("/", 1)[-1]:
                    latest[base] = href
    zdir = ROOT / m["zim"]["dir"]
    for name, _size in m["zim"]["names"]:
        href = latest.get(name)
        if not href:
            print(f"  ? {name} not in the Kiwix catalog")
            continue
        fname = href.rsplit("/", 1)[-1][: -len(".meta4")]
        get(href, zdir / fname, dry)


def maps(m: dict, dry: bool) -> None:
    t = m["maps"]["tiles"]
    dest = ROOT / t["path"]
    if dest.exists():
        print(f"  ✓ {t['path']}")
    else:
        builds = json.loads(urllib.request.urlopen("https://build-metadata.protomaps.dev/builds.json").read())
        key = builds[-1]["key"]
        bbox = ",".join(str(x) for x in t["bbox"])
        print(f"  ↓ Protomaps {key} → {t['path']} (bbox {bbox}, z0-{t['maxzoom']})")
        if not dry:
            part = dest.with_suffix(".pmtiles.part")
            subprocess.run([str(ROOT / "bin" / "win-x64" / "pmtiles.exe"), "extract", f"https://build.protomaps.com/{key}", str(part),
                            f"--bbox={bbox}", f"--maxzoom={t['maxzoom']}", "--download-threads=8"], check=True)
            part.replace(dest)
            (dest.parent / "tiles.json").write_text(json.dumps({"source": f"Protomaps {key}", "bounds": t["bbox"], "maxzoom": t["maxzoom"]}), "utf-8")
    w = m["maps"].get("world")
    if w:
        wdest = ROOT / w["path"]
        if wdest.exists():
            print(f"  ✓ {w['path']}")
        else:
            builds = json.loads(urllib.request.urlopen("https://build-metadata.protomaps.dev/builds.json").read())
            key = builds[-1]["key"]
            print(f"  ↓ Protomaps {key} → {w['path']} (whole planet, z0-{w['maxzoom']})")
            if not dry:
                part = wdest.with_suffix(".pmtiles.part")
                subprocess.run([str(ROOT / "bin" / "win-x64" / "pmtiles.exe"), "extract", f"https://build.protomaps.com/{key}", str(part),
                                f"--maxzoom={w['maxzoom']}", "--download-threads=8"], check=True)
                part.replace(wdest)
    a = m["maps"]["assets"]
    if not (ROOT / a["path"] / "fonts").exists():
        z = DL / "basemaps-assets.zip"
        get(a["url"], z, dry)
        if not dry:
            with zipfile.ZipFile(z) as zf:
                for info in zf.infolist():
                    parts = info.filename.split("/", 1)
                    if len(parts) == 2 and parts[1].startswith(("fonts/", "sprites/")) and not info.is_dir():
                        out = ROOT / a["path"] / parts[1]
                        out.parent.mkdir(parents=True, exist_ok=True)
                        out.write_bytes(zf.read(info))
    print("  → then run scripts/build_geodata.py and scripts/build_routing.py")


def addresses(m: dict, dry: bool) -> None:
    for f in m["maps"]["addresses"]["files"]:
        get(f["url"], ROOT / f["path"], dry)
    print("  → then run scripts/build_addresses.py")


def main() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default=str(ROOT / "manifests" / "standard.json"))
    ap.add_argument("--only", nargs="*", choices=["runtimes", "models", "zim", "maps", "addresses"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    m = json.loads(Path(args.manifest).read_text("utf-8"))
    DL.mkdir(parents=True, exist_ok=True)
    for group, fn in (("runtimes", runtimes), ("models", models), ("zim", zims), ("maps", maps), ("addresses", addresses)):
        if args.only and group not in args.only:
            continue
        print(f"[{group}]")
        fn(m, args.dry_run)


if __name__ == "__main__":
    main()
