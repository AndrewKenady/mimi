"""Copy this MIMI install to a USB drive (or any folder) as a portable edition.

    python\\python.exe scripts\\make_drive.py E:\\ --edition standard
    python\\python.exe scripts\\make_drive.py E:\\MIMI --edition lite --map-bbox -111.1,40.9,-104.0,45.1
    python\\python.exe scripts\\make_drive.py F:\\ --edition full --dry-run

Editions (see docs/PLAN.md, section 11.3):
  lite      Qwen3.5-4B, Whisper small, the practical references (medicine, repair, travel,
            survival), and optionally a map region you choose. Fits a 64 GB drive.
  standard  The reference device's models, every installed book that fits, full maps and
            routing. Books are dropped largest-first if the drive is too small.
  full      Everything installed here.

The copy is restartable (robocopy): run the same command again to resume. Your personal
data (data/: accounts, chats, memories) is left behind unless --include-my-data is given.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GB = 1024**3

CODE = ["core", "config", "scripts", "manifests", "docs", "tools", "shell", "LICENSE", "README.md"]
EXCLUDE_DIRS = ["__pycache__", ".pytest_cache", "node_modules", ".svelte-kit", "obj", "bin\\Debug", "tests"]

MODELS = {
    "lite": ["qwen3.5-4b", "bge-m3", "whisper/small", "tts"],
    "standard": ["gemma-4-12b", "qwen3.5-9b", "qwen3.5-4b", "bge-m3", "whisper/small", "whisper/turbo", "tts"],
}
# Book name prefixes for the lite edition, in priority order.
LITE_BOOKS = ["mdwiki", "zimgit", "ifixit", "wikivoyage", "wikipedia_en_top", "wikipedia_en_100", "outdoors.stackexchange",
              "mechanics.stackexchange", "diy.stackexchange", "cooking.stackexchange"]
# Never dropped to make room: the practical references are the point of a field drive.
ESSENTIAL = ["mdwiki", "zimgit", "ifixit", "wikivoyage"]
# When a drive is too small, drop these first (largest, least essential), then everything else largest-first.
DROP_FIRST = ["ted_", "gutenberg_", "superuser", "electronics.stackexchange", "physics.stackexchange", "wiktionary", "wikipedia_en_all"]


# --------------------------------------------------------------------------- helpers
def size_of(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    total = 0
    for dirpath, dirnames, filenames in os.walk(p):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for f in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def filesystem(target: Path) -> str:
    anchor = Path(target.anchor or str(target))
    buf = ctypes.create_unicode_buffer(64)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(str(anchor), None, 0, None, None, None, buf, 64) if os.name == "nt" else 0
    return buf.value if ok else "unknown"


def free_bytes(target: Path) -> int:
    p = target
    while not p.exists():
        if p.parent == p:
            raise SystemExit(f"Drive {target.anchor or target} not found. Plug the drive in, or check the letter.")
        p = p.parent
    return shutil.disk_usage(p).free


def gb(n: int) -> str:
    return f"{n / GB:,.1f} GB"


def robocopy(src: Path, dst: Path, files: list[str] | None = None, exclude_dirs: list[str] | None = None, dry: bool = False) -> None:
    """Copy a directory tree (or named files from it). Never deletes anything at the target."""
    cmd = ["robocopy", str(src), str(dst)] + (files or []) + ([] if files else ["/E"]) + ["/R:2", "/W:2", "/MT:8", "/J", "/NP", "/NDL", "/NFL", "/NJH"]
    if exclude_dirs:
        cmd += ["/XD", *exclude_dirs]
    cmd += ["/XF", "*.aria2", "*.part", "*.tmp", "*.pyc"]
    if dry:
        print("   would run:", " ".join(cmd))
        return
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode >= 8:  # robocopy: 0-7 are success codes
        raise SystemExit(f"robocopy failed ({r.returncode}) copying {src}:\n{r.stdout[-1500:]}\n{r.stderr[-500:]}")


# --------------------------------------------------------------------------- planning
def plan(args) -> tuple[list[tuple[Path, Path, list[str] | None]], int, list[str]]:
    """Return (copy jobs, total bytes, notes)."""
    jobs: list[tuple[Path, Path, list[str] | None]] = []
    notes: list[str] = []
    dst = Path(args.target)

    def add(rel: str, files: list[str] | None = None) -> int:
        src = ROOT / rel
        if not src.exists():
            return 0
        if src.is_file():
            jobs.append((src.parent, dst / Path(rel).parent, [src.name]))
            return src.stat().st_size
        jobs.append((src, dst / rel, files))
        return sum(size_of(src / f) for f in files) if files else size_of(src)

    total = 0
    # Runtimes, code and the built app
    for rel in CODE + ["python", "bin", "ui/build"]:
        total += add(rel)
    shell_files = [p.name for p in ROOT.glob("*") if p.is_file() and (p.suffix.lower() in (".exe", ".dll") or p.name == "MIMI.exe.config")]
    if shell_files:
        jobs.append((ROOT, dst, shell_files))
        total += sum((ROOT / f).stat().st_size for f in shell_files)
    else:
        notes.append("MIMI.exe isn't built yet (run shell\\build.ps1); the drive will need python\\python.exe -m mimi serve instead.")

    # Models
    wanted = None if args.edition == "full" else MODELS[args.edition]
    for d in sorted((ROOT / "models").glob("*/*")) + sorted((ROOT / "models").glob("tts")):
        rel = d.relative_to(ROOT / "models").as_posix()
        name = rel.split("/", 1)[1] if rel.startswith("llm/") else rel
        if d.is_dir() and (wanted is None or name in wanted or rel in wanted):
            total += add(f"models/{rel}")

    # Maps
    maps = ROOT / "maps"
    if args.edition != "lite" or args.map_bbox:
        for f in ("places.sqlite", "geowiki.sqlite", "tiles.json"):
            total += add(f"maps/{f}")
        total += add("maps/assets")
        if args.map_bbox:
            jobs.append((Path("pmtiles-extract"), dst / "maps", [args.map_bbox]))
            notes.append(f"Map tiles: extracting region {args.map_bbox} (size known after extraction; usually 0.3-3 GB per state).")
        elif (maps / "tiles.pmtiles").exists():
            total += add("maps/tiles.pmtiles")
        if not args.no_routing and args.edition != "lite":
            if (maps / "routing" / "config.json").exists():
                total += add("maps/routing")
            else:
                notes.append("Routing tiles aren't built yet, so the drive won't have driving directions (scripts\\build_routing.py).")
    else:
        for f in ("places.sqlite", "geowiki.sqlite"):
            total += add(f"maps/{f}")
        notes.append("Lite edition: no map tiles unless you pass --map-bbox (nearby places and 'where am I' still work).")

    # Books, fitted to the drive
    books = sorted(p for p in (ROOT / "zim").glob("*.zim"))
    if args.edition == "lite":
        books = [b for b in books if any(b.name.startswith(p) for p in LITE_BOOKS)]
    # A re-run resumes: what's already on the target counts as available space.
    room = args.max_gb * GB if args.max_gb else free_bytes(dst) + (size_of(dst) if dst.exists() else 0)
    budget = room - total - 2 * GB  # keep 2 GB headroom for data/
    chosen = list(books)
    size = {b: b.stat().st_size for b in chosen}
    dropped: list[Path] = []

    def rank(b: Path) -> tuple:
        pri = next((i for i, p in enumerate(DROP_FIRST) if b.name.startswith(p)), len(DROP_FIRST))
        return (pri, -size[b])

    while sum(size[b] for b in chosen) > budget and args.edition != "full":
        droppable = [b for b in chosen if not any(b.name.startswith(p) for p in ESSENTIAL)]
        if not droppable:
            break  # the space check in main() explains that the drive is too small
        victim = min(droppable, key=rank)
        chosen.remove(victim)
        dropped.append(victim)
    # Second pass: put back whatever still fits, most important first (e.g. once Wikipedia
    # is out, the smaller shelves dropped before it usually fit again).
    for b in reversed(dropped):
        if sum(size[x] for x in chosen) + size[b] <= budget:
            chosen.append(b)
    for b in dropped:
        if b not in chosen:
            notes.append(f"Left out {b.name} ({gb(size[b])}) to fit the drive.")
            if b.name.startswith("wikipedia_en_all_maxi"):
                notes.append("Tip: Wikipedia without pictures (wikipedia_en_all_nopic, ~50 GB) fits a 128 GB drive; add it to the "
                             "manifest's zim names and run scripts\\fetch.py.")
    if chosen:
        jobs.append((ROOT / "zim", dst / "zim", [b.name for b in chosen]))
        total += sum(size[b] for b in chosen)
    if args.include_my_data:
        total += add("data")
        notes.append("Including your personal data (accounts, chats, memories). Anyone with the drive can read it.")
    return jobs, total, notes


# --------------------------------------------------------------------------- main
def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="drive or folder, e.g. E:\\ or E:\\MIMI")
    ap.add_argument("--edition", choices=["lite", "standard", "full"], default="standard")
    ap.add_argument("--map-bbox", help="copy only this map region: west,south,east,north (degrees)")
    ap.add_argument("--no-routing", action="store_true", help="leave out the driving-directions graph")
    ap.add_argument("--include-my-data", action="store_true", help="also copy data/ (accounts, chats, memories)")
    ap.add_argument("--max-gb", type=float, help="size budget instead of the drive's free space")
    ap.add_argument("--dry-run", action="store_true", help="show the plan without copying")
    args = ap.parse_args()

    dst = Path(args.target)
    free_bytes(dst)  # fails early if the drive isn't there
    if dst.resolve() == ROOT or ROOT in dst.resolve().parents:
        raise SystemExit("The target must be outside this MIMI folder.")
    fs = filesystem(dst)
    if fs.upper().startswith("FAT") and fs.upper() != "EXFAT":
        raise SystemExit(f"{dst.anchor} is formatted {fs}, which can't hold files over 4 GB (models, Wikipedia). Reformat it as exFAT or NTFS.")

    jobs, total, notes = plan(args)
    free = free_bytes(dst) + (size_of(dst) if dst.exists() else 0)
    print(f"MIMI {args.edition} edition -> {dst}  ({fs}, {gb(free)} free)")
    print(f"   to copy: {gb(total)} in {len(jobs)} parts")
    for n in notes:
        print("   note:", n)
    if total > free:
        raise SystemExit(f"Not enough space: need {gb(total)}, have {gb(free)}. Try --edition lite, or --max-gb.")
    if args.dry_run:
        for src, d, files in jobs:
            print(f"   {src} -> {d}" + (f"  [{len(files)} file(s)]" if files else ""))
        return

    t0 = time.time()
    for i, (src, d, files) in enumerate(jobs, 1):
        if str(src) == "pmtiles-extract":
            out = d / "tiles.pmtiles"
            d.mkdir(parents=True, exist_ok=True)
            print(f"[{i}/{len(jobs)}] extracting map region {files[0]} ...", flush=True)
            subprocess.run([str(ROOT / "bin/win-x64/pmtiles.exe"), "extract", str(ROOT / "maps/tiles.pmtiles"), str(out),
                            f"--bbox={files[0]}"], check=True)
            continue
        label = src.relative_to(ROOT) if src != ROOT else ", ".join(files or [])[:70]
        print(f"[{i}/{len(jobs)}] {label} ...", flush=True)
        robocopy(src, d, files, EXCLUDE_DIRS if files is None else None)

    (dst / "data").mkdir(parents=True, exist_ok=True)
    (dst / "logs").mkdir(parents=True, exist_ok=True)
    (dst / "portable.json").write_text(json.dumps({
        "edition": args.edition, "created": time.strftime("%Y-%m-%d %H:%M"), "source": str(ROOT),
        "note": "Run MIMI.exe from this drive. Settings and chats are stored in data\\ on the drive.",
    }, indent=2), encoding="utf-8")
    print(f"Done in {(time.time() - t0) / 60:.0f} min. Plug the drive into any Windows 10/11 PC and run {dst / 'MIMI.exe'}.")


if __name__ == "__main__":
    main()
