"""Build Mimi's offline routing graph (Valhalla tiles) from OpenStreetMap extracts.

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


# Ways nobody routes along, dropped by default ("lean"): they are ~20% of US/Canada road
# nodes, and Valhalla's scratch space grows ~13x the input (US + Canada full: ~50 GB).
SKIP_SERVICE = {"driveway", "parking_aisle", "drive-through", "emergency_access"}
GOOD_TRACKS = {"grade1", "grade2"}


def keep_lean(tags) -> bool:
    h = tags.get("highway")
    if h == "service" and tags.get("service") in SKIP_SERVICE:
        return False
    if h == "track":
        # named or numbered tracks (forest roads) and well-graded ones stay; farm/field tracks go
        return bool(tags.get("name") or tags.get("ref") or tags.get("tracktype") in GOOD_TRACKS)
    return True


def lean_roads(src: Path) -> Path:
    """Drop driveways, parking aisles, drive-throughs and unnamed rough tracks.

    Streams the file and simply omits those ways. Their nodes stay in the output, but
    Valhalla ignores nodes no kept way uses, and its scratch space grows with way-node
    references, so the saving is the same. (osmium's BackReferenceWriter would drop the
    orphan nodes too, but it tracks every referenced id in memory and runs out on a
    US + Canada extract.)
    """
    import osmium

    dst = src.with_name(src.name.replace(".osm.pbf", ".lean.osm.pbf"))
    if dst.exists():
        print(f"✓ {dst.name} already made")
        return dst
    t0 = time.time()
    last = t0
    n = kept = dropped = 0
    tmp = dst.with_suffix(".tmp.pbf")
    with osmium.SimpleWriter(str(tmp), overwrite=True) as writer:
        for obj in osmium.FileProcessor(str(src)):
            n += 1
            if obj.is_way() and not keep_lean(obj.tags):
                dropped += 1
                continue
            if obj.is_way():
                kept += 1
            writer.add(obj)
            if n % 5_000_000 == 0 and time.time() - last > 30:
                last = time.time()
                print(f"  … {n / 1e6:.0f}M objects, {kept:,} ways kept, {dropped:,} dropped ({n / (last - t0) / 1e3:.0f}k/s)", flush=True)
    tmp.replace(dst)
    print(f"✓ {dst.name}: kept {kept:,}, dropped {dropped:,} ways in {int(time.time() - t0)} s "
          f"({dst.stat().st_size / 1e9:.1f} GB, was {src.stat().st_size / 1e9:.1f} GB)")
    return dst


def merge_pbfs(files: list[Path]) -> Path:
    """Stream-merge sorted extracts into one file, dropping the duplicates they share.

    Neighbouring extracts (US and Canada) both contain the roads that cross the border.
    Valhalla builds from several files badly: North America built that way can crash
    with "Exceeding kMaxLinkEdges in ReclassifyLinks" (valhalla#3908, #3925), and the
    advice is to merge first. pyosmium's MergeInputReader holds everything in memory,
    so this is a two-pointer merge over (type, id) instead.
    """
    import osmium

    dst = files[0].with_name("merged-" + "-".join(f.name.split(".")[0] for f in files) + ".osm.pbf")
    if dst.exists():
        print(f"✓ {dst.name} already merged")
        return dst
    t0 = time.time()
    tmp = dst.with_suffix(".tmp.pbf")
    order = {"n": 0, "w": 1, "r": 2}
    iters = [iter(osmium.FileProcessor(str(f))) for f in files]
    heads = [next(it, None) for it in iters]
    last = [(-1, -1)] * len(files)
    written = dupes = 0
    with osmium.SimpleWriter(str(tmp), overwrite=True) as w:
        while True:
            keys = [(order[o.type_str()], o.id) if o is not None else None for o in heads]
            live = [k for k in keys if k is not None]
            if not live:
                break
            k = min(live)
            first = True
            for i, ki in enumerate(keys):
                if ki != k:
                    continue
                if ki < last[i]:
                    raise SystemExit(f"{files[i].name} isn't sorted by type and id; can't merge it in one pass")
                last[i] = ki
                if first:
                    w.add(heads[i])
                    written += 1
                    first = False
                else:
                    dupes += 1
                heads[i] = next(iters[i], None)
    tmp.replace(dst)
    print(f"✓ merged {len(files)} extracts into {dst.name}: {written:,} objects, {dupes:,} border duplicates dropped, "
          f"{int(time.time() - t0)} s ({dst.stat().st_size / 1e9:.1f} GB)")
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
    ap.add_argument("--full-roads", action="store_true", help="keep driveways, parking aisles and unnamed tracks (much more scratch space)")
    ap.add_argument("--work", help="folder for the build's scratch files (default: next to --out); e.g. a roomier drive")
    args = ap.parse_args()

    out = Path(args.out)
    work = (Path(args.work) / (out.name + ".building")) if args.work else out.with_name(out.name + ".building")
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
    if len(pbfs) > 1:
        merged = merge_pbfs(pbfs)
        if not args.keep:
            for p in pbfs:
                if p not in raw or not args.pbf:  # never delete a file the user pointed at directly
                    p.unlink(missing_ok=True)
        pbfs = [merged]
    if not args.full_roads:
        lean = [lean_roads(p) for p in pbfs]
        if not args.keep:
            for p in pbfs:
                if p not in raw or not args.pbf:
                    p.unlink(missing_ok=True)
        pbfs = lean

    # Valhalla's scratch files peak at ~13x the input (ways.bin + way_nodes.bin + a sorted copy).
    shutil.rmtree(work, ignore_errors=True)
    # (lean files keep their orphan nodes, so per byte they carry ~25% fewer way-node references)
    need = sum((10 if ".lean." in p.name else 13) * p.stat().st_size for p in pbfs)
    work.parent.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(work.parent).free
    if free < need:
        sys.exit(f"not enough disk space for the tile build: need ~{need / 1e9:.0f} GB free at {work.parent}, have {free / 1e9:.0f} GB. "
                 f"Free some space, or pass --work <folder on a roomier drive>.")
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
    shutil.move(str(work), str(out))  # works across drives when --work is elsewhere
    print(f"✓ routing ready in {out} ({size / 1e9:.1f} GB, {meta['build_seconds'] // 60} min)")
    if not args.keep:
        for p in pbfs + raw:
            p.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
