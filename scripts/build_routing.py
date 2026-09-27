"""Build MIMI's offline routing graph (Valhalla tiles) from OpenStreetMap extracts.

    python scripts/build_routing.py                       # US + Canada (default)
    python scripts/build_routing.py --regions us/wyoming  # a single state, for testing
    python scripts/build_routing.py --skip-download

Data: OpenStreetMap contributors (ODbL) via Geofabrik extracts. Engine: Valhalla
(MIT) from the `pyvalhalla` wheel. Output: maps/routing/{tiles/, config.json,
meta.json}. The downloaded .osm.pbf files are deleted afterwards unless --keep.

Rough cost on an 8-core Ryzen 7840U: a US state takes under a minute; US + Canada
(~19 GB of PBF) takes a few hours and needs ~20 GB of free disk for the tiles.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEOFABRIK = "https://download.geofabrik.de/north-america/{}-latest.osm.pbf"


def valhalla_dirs() -> tuple[Path, Path]:
    import valhalla

    pkg = Path(valhalla.__file__).parent
    libs = pkg.parent / "pyvalhalla.libs"
    return pkg, libs


def download(regions: list[str], dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    aria2 = ROOT / "bin" / "win-x64" / "aria2c.exe"
    files = []
    for r in regions:
        url = GEOFABRIK.format(r)
        out = dest / Path(url).name
        files.append(out)
        if out.exists() and not out.with_name(out.name + ".aria2").exists():
            print(f"✓ {out.name} already downloaded")
            continue
        print(f"↓ {url}")
        if aria2.exists():
            subprocess.run([str(aria2), "-x8", "-s8", "-k8M", "--continue=true", "--max-tries=0", "--retry-wait=15",
                            "--file-allocation=none", "-q", "-d", str(dest), "-o", out.name, url], check=True)
        else:
            import urllib.request

            urllib.request.urlretrieve(url, out)
    return files


DRIVABLE = {
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link",
    "tertiary", "tertiary_link", "unclassified", "residential", "living_street", "service", "road", "track",
}


def roads_only(src: Path) -> Path:
    """Keep only drivable roads, ferries and turn restrictions (plus the nodes they use).

    Raw extracts are mostly buildings, land use and addresses. Dropping them cuts
    the build's temporary disk use (≈5× the input) by roughly two thirds.
    """
    import osmium

    dst = src.with_name(src.name.replace(".osm.pbf", ".roads.osm.pbf"))
    if dst.exists():
        print(f"✓ {dst.name} already filtered")
        return dst
    t0 = time.time()
    kept = 0
    tmp = dst.with_suffix(".tmp.pbf")
    with osmium.BackReferenceWriter(str(tmp), ref_src=str(src), overwrite=True) as writer:
        fp = osmium.FileProcessor(str(src), osmium.osm.WAY | osmium.osm.RELATION).with_filter(osmium.filter.KeyFilter("highway", "route", "type"))
        for obj in fp:
            t = obj.tags
            if obj.is_way():
                if t.get("highway") in DRIVABLE or t.get("route") == "ferry":
                    writer.add(obj)
                    kept += 1
            elif t.get("type") in ("restriction", "restriction:motorcar"):
                writer.add(obj)
                kept += 1
    tmp.replace(dst)
    print(f"✓ {dst.name}: kept {kept:,} ways/relations in {int(time.time() - t0)} s ({dst.stat().st_size / 1e9:.1f} GB, was {src.stat().st_size / 1e9:.1f} GB)")
    return dst


def main() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--regions", nargs="+", default=["us", "canada"], help="Geofabrik north-america paths, e.g. us canada us/wyoming")
    ap.add_argument("--out", default=str(ROOT / "maps" / "routing"))
    ap.add_argument("--concurrency", type=int, default=max(2, (os.cpu_count() or 4) // 2))
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--keep", action="store_true", help="keep the downloaded .osm.pbf files")
    ap.add_argument("--pbf", nargs="*", help="use these local .osm.pbf files instead of downloading")
    ap.add_argument("--no-filter", action="store_true", help="build from the raw extracts (needs ~5x their size in temp space)")
    args = ap.parse_args()

    out = Path(args.out)
    work = out.with_name(out.name + ".building")
    dl = ROOT / ".tools" / "dl" / "osm"
    pkg, libs = valhalla_dirs()
    env = dict(os.environ, PATH=f"{libs}{os.pathsep}{os.environ.get('PATH', '')}")

    if args.pbf:
        raw = [Path(p) for p in args.pbf]
    elif args.skip_download:
        raw = [dl / Path(GEOFABRIK.format(r)).name for r in args.regions]
    else:
        raw = download(args.regions, dl)
    missing = [p for p in raw if not p.exists()]
    if missing:
        sys.exit(f"missing extracts: {', '.join(p.name for p in missing)}")
    pbfs = raw if args.no_filter else [roads_only(p) for p in raw]
    if not args.keep and not args.no_filter:
        for p in raw:  # free the space before the (disk-hungry) tile build
            p.unlink(missing_ok=True)

    shutil.rmtree(work, ignore_errors=True)
    (work / "tiles").mkdir(parents=True)
    cfg_json = subprocess.run([sys.executable, str(pkg / "valhalla_build_config.py"), "--mjolnir-tile-dir", str(work / "tiles"),
                               "--mjolnir-tile-extract", str(work / "tiles.tar"), "--mjolnir-concurrency", str(args.concurrency)],
                              check=True, capture_output=True, text=True).stdout
    (work / "config.json").write_text(cfg_json, "utf-8")

    t0 = time.time()
    print(f"⚙ building routing tiles from {', '.join(p.name for p in pbfs)} (concurrency {args.concurrency}) …")
    with open(ROOT / "logs" / "valhalla-build.log", "w", encoding="utf-8") as log:
        rc = subprocess.run([str(pkg / "bin" / "valhalla_build_tiles.exe"), "-c", str(work / "config.json"), *map(str, pbfs)],
                            env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    if rc != 0:
        sys.exit(f"valhalla_build_tiles failed (exit {rc}); see logs/valhalla-build.log")
    size = sum(f.stat().st_size for f in (work / "tiles").rglob("*") if f.is_file())
    meta = {"region": " + ".join(r.split("/")[-1].title() if r != "us" else "United States" for r in args.regions),
            "built": time.strftime("%Y-%m-%d"), "source": "OpenStreetMap via Geofabrik (ODbL)", "tiles_bytes": size,
            "build_seconds": int(time.time() - t0)}
    (work / "meta.json").write_text(json.dumps(meta, indent=1), "utf-8")
    shutil.rmtree(out, ignore_errors=True)
    work.rename(out)
    print(f"✓ routing ready in {out} ({size / 1e9:.1f} GB, {meta['build_seconds'] // 60} min)")
    if not args.keep:
        for p in pbfs + raw:
            p.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
