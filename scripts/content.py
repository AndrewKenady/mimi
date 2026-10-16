#!/usr/bin/env python3
"""Mimi's content manager: see, add and remove models, books and maps.

    python scripts/content.py list                     # every pack, its size, and whether you have it
    python scripts/content.py status                   # what's installed, disk use, free space
    python scripts/content.py regions                  # named map regions and their sizes
    python scripts/content.py add wikipedia-full       # add packs ...
    python scripts/content.py add lite --region uk     # ... or a whole tier, for a map region
    python scripts/content.py add map-region --bbox -111.1,40.9,-104.0,45.1
    python scripts/content.py remove ted               # delete a pack's files
    python scripts/content.py verify                   # re-check installed files against their hashes

Before downloading, `add` totals what's missing (minus anything already partly
downloaded), compares it with the free space on the content drive, and stops if
it won't fit. Interrupted downloads resume when you run the same command again.
Content lives in the Mimi folder, or wherever MIMI_CONTENT points (Docker: /data).
Restart Mimi (or use Settings → Restart services) to pick up new books and maps.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch
from fetch import GB, content_root, fmt_size, say

HEADROOM = 2 * GB  # keep this much free for Mimi's own data, logs and temp files


def free_bytes(path: Path) -> int:
    p = path
    while not p.exists() and p.parent != p:
        p = p.parent
    return shutil.disk_usage(p).free


def pack_state(pid: str, region: dict) -> tuple[str, int | None]:
    """('installed' | 'partial' | '', bytes it takes) for one pack."""
    if fetch.pack_problem(pid, region):
        return "n/a", None
    items = [i for i in fetch.pack_items(pid, region) if not i.temporary]
    done = [i.installed() for i in items]
    size = None if any(i.size is None for i in items) else sum(i.size or 0 for i in items)
    if all(done):
        return "installed", size
    if any(done) or any(i.partial_bytes() for i in items):
        return "partial", size
    return "", size


def tiers_with(pid: str) -> list[str]:
    return [t for t in fetch.tier_names() if pid in fetch.load_tier(t)["packs"]]


def expand(names: list[str]) -> tuple[list[str], dict | None]:
    """Pack ids from pack and tier names (in order); the tier, if exactly one was named."""
    packs, tiers = fetch.all_packs(), set(fetch.tier_names())
    out: list[str] = []
    tier = None
    for n in names:
        if n in tiers:
            tier = fetch.load_tier(n)
            out += [p for p in tier["packs"] if p not in out]
        elif n in packs:
            if n not in out:
                out.append(n)
        else:
            raise SystemExit(f"No pack or tier called {n!r}. See: python scripts/content.py list")
    return out, tier


def region_from(args, tier: dict | None = None) -> dict:
    return fetch.resolve_region(getattr(args, "region", None), getattr(args, "bbox", None), fetch.load_state(), tier)


# --------------------------------------------------------------------------- commands
def cmd_list(args) -> int:
    region = region_from(args)
    say(f"Map region: {region['title']}   (content in {content_root()})\n")
    say(f"  {'pack':<20} {'size':>9}  {'status':<10} {'in tier':<14} description")
    for group in ("models", "zim", "maps", "geodata", "routing", "addresses"):
        for pid, p in fetch.all_packs().items():
            if p["group"] != group:
                continue
            status, size = pack_state(pid, region)
            tiers = ",".join(tiers_with(pid)[:1]) or "-"
            say(f"  {pid:<20} {fmt_size(size) if size else '?':>9}  {status:<10} {tiers:<14} {p['title']}")
    say("\nAdd with: python scripts/content.py add <pack>   (a tier name adds all of its packs)")
    return 0


def cmd_regions(args) -> int:
    R = fetch.regions()
    say(f"  {'region':<12} {'map z13':>9} {'map z14':>9} {'routing':>9}  addresses  title")
    for name, r in R["regions"].items():
        mm = r.get("map_mb", {})
        say(f"  {name:<12} {fmt_size(mm['13'] * 1e6) if '13' in mm else '?':>9} {fmt_size(mm['14'] * 1e6) if '14' in mm else '?':>9} "
            f"{'~' + fmt_size(r['routing_mb'] * 1e6) if r.get('routing_mb') else '-':>9}  {'yes' if r.get('addresses') else '-':<9}  {r['title']}")
    say("\nOr any area: --bbox west,south,east,north (maps only; sizes are measured before downloading).")
    return 0


def cmd_status(args) -> int:
    state = fetch.load_state()
    region = region_from(args)
    root = content_root()
    say(f"Content folder: {root}")
    say(f"Map region:     {region['title']}")
    used = 0
    for d in ("models", "zim", "maps"):
        p = root / d
        n = sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0
        used += n
        say(f"  {d + '/':<8} {fmt_size(n):>10}")
    say(f"  {'total':<8} {fmt_size(used):>10}    free: {fmt_size(free_bytes(root))}")
    say("\nInstalled packs:")
    any_ = False
    for pid, p in fetch.all_packs().items():
        status, size = pack_state(pid, region)
        if status in ("installed", "partial"):
            any_ = True
            say(f"  {'✓' if status == 'installed' else '…'} {pid:<20} {p['title']}" + ("  (partly downloaded: run add again to finish)" if status == "partial" else ""))
    if not any_:
        say("  none yet. Start with: python scripts/content.py add lite")
    if state.get("added"):
        say(f"\nAdded with this tool: {', '.join(state['added'])}")
    return 0


def cmd_add(args) -> int:
    pids, tier = expand(args.names)
    region = region_from(args, tier)
    skipped = []
    for pid in list(pids):
        why = fetch.pack_problem(pid, region)
        if why:
            pids.remove(pid)
            skipped.append(f"{pid}: {why}")
    if args.skip:
        pids = [p for p in pids if p not in args.skip]
    items = fetch.plan(pids, region)
    built = {i.pack for i in items if i.kind == "build" and i.installed()}
    todo = [i for i in items if not i.installed() and not (i.temporary and i.pack in built)]

    say(f"Content folder: {content_root()}")
    say(f"Map region:     {region['title']}")
    for s in skipped:
        say(f"  - skipping {s}")
    if not todo:
        say("Everything asked for is already installed.")
        _remember(pids, region, args.dry_run)
        return 0
    need, unknown = 0, []
    say("\nTo download or build:")
    for it in todo:
        if it.size is None and it.kind in ("world", "tiles"):
            it.measure()  # a custom --bbox: ask pmtiles
        remaining = None if it.size is None else max(0, it.size - it.partial_bytes())
        if remaining is None:
            unknown.append(it.label)
        else:
            need += remaining
        extra = f"  ({'; '.join(it.notes)})" if it.notes else ""
        say(f"  {it.pack:<20} {fmt_size(remaining) if remaining is not None else '?':>9}  {it.label}{extra}")
    free = free_bytes(content_root())
    say(f"\nTotal: {fmt_size(need)}{' + items of unknown size' if unknown else ''}   free: {fmt_size(free)}")
    conflicts = [c for c in (i.conflict() for i in todo) if c]
    for c in conflicts:
        say(f"Note: this {c}.")
    if need + HEADROOM > free and not args.force:
        say(f"\nNot enough space: this needs {fmt_size(need)} plus {fmt_size(HEADROOM)} to spare, and {fmt_size(free)} is free "
            f"on the drive holding {content_root()}.\nFree some space, remove packs (content.py remove ...), set MIMI_CONTENT to a bigger "
            f"drive, or pass --force to try anyway.")
        if not args.dry_run:
            return 2
    if args.dry_run:
        say("\n(dry run: nothing downloaded)")
        fetch.run(todo, dry=True)
        return 0
    if (conflicts or need > 20 * GB) and not args.yes and sys.stdin.isatty():
        if input("Continue? [Y/n] ").strip().lower() not in ("", "y", "yes"):
            return 1
    errors = fetch.run(todo)
    _remember(pids, region, False)
    if errors:
        say("\nSome packs didn't finish (run the same command again to resume):\n  " + "\n  ".join(errors))
        return 1
    say("\nDone. Restart Mimi (Settings → Restart services) to load new books and maps.")
    return 0


def _remember(pids: list[str], region: dict, dry: bool) -> None:
    if dry:
        return
    state = fetch.load_state()
    state["region"] = region
    state["added"] = list(dict.fromkeys((state.get("added") or []) + pids))
    fetch.save_state(state)


def removal_targets(pid: str, region: dict) -> list[Path]:
    out: list[Path] = []
    spec_remove = []
    for it in fetch.pack_items(pid, region):
        spec_remove += it.spec.get("remove") or []
        if it.temporary:
            out += [p.with_name(p.name + ".part") for p in it.targets()] + it.targets()
            continue
        if it.kind == "build":
            out += [Path(str(p)) for p in it.targets()]
        elif it.kind == "zim":
            out += it.targets() + sorted((content_root() / "zim").glob(f"{it.spec['name']}_*.zim.part"))
        else:
            out += it.targets() + [p.with_name(p.name + ".part") for p in it.targets()]
    out += [content_root() / r for r in spec_remove]
    return [p for p in dict.fromkeys(out) if p.exists()]


def cmd_remove(args) -> int:
    pids, _ = expand(args.names)
    region = region_from(args)
    targets = [t for pid in pids for t in removal_targets(pid, region)]
    if not targets:
        say("Nothing to remove.")
        return 0
    total = sum((sum(f.stat().st_size for f in t.rglob("*") if f.is_file()) if t.is_dir() else t.stat().st_size) for t in targets)
    say("Will delete:")
    for t in targets:
        say(f"  {fetch._rel(t)}")
    say(f"Frees {fmt_size(total)}.")
    if not args.yes:
        if not sys.stdin.isatty():
            say("Pass --yes to confirm.")
            return 1
        if input("Delete these files? [y/N] ").strip().lower() not in ("y", "yes"):
            return 1
    for t in targets:
        shutil.rmtree(t) if t.is_dir() else t.unlink()
    state = fetch.load_state()
    state["added"] = [p for p in state.get("added") or [] if p not in pids]
    fetch.save_state(state)
    say("Removed. Restart Mimi to stop serving them.")
    return 0


def cmd_verify(args) -> int:
    region = region_from(args)
    pids = expand(args.names)[0] if args.names else list(fetch.all_packs())
    bad = 0
    for pid in pids:
        if fetch.pack_problem(pid, region):
            continue
        for it in fetch.pack_items(pid, region):
            if it.temporary or not it.installed():
                continue
            try:
                if it.kind == "file" and it.spec.get("sha256"):
                    fetch.verify_file(it.path(it.spec["path"]), it.spec["sha256"], it.spec.get("size"))
                elif it.kind in ("world", "tiles"):
                    exe = fetch.tool("pmtiles")
                    if exe:
                        r = subprocess.run([str(exe), "verify", str(it.targets()[0])], capture_output=True, text=True)
                        if r.returncode:
                            raise fetch.IntegrityError((r.stdout + r.stderr).strip()[-200:])
                elif it.kind == "zim" and args.zim:
                    href = fetch.kiwix_latest().get(it.spec["name"])
                    for f in it.targets():
                        if href and href.rsplit("/", 1)[-1][: -len(".meta4")] == f.name:
                            meta = fetch.parse_metalink(fetch.fetch_bytes(href))
                            fetch.verify_file(f, meta["sha256"], meta["size"])
                        else:
                            say(f"  ? {f.name}: not the catalog's current release, can't look up its hash")
                            continue
                else:
                    continue
                say(f"  ✓ {it.label}")
            except (fetch.DownloadError, OSError) as e:
                bad += 1
                say(f"  ✗ {it.label}: {e}")
    say("All checked files are intact." if not bad else f"{bad} file(s) failed. Remove and re-add their packs.")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="content", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def region_opts(p):
        p.add_argument("--region", help="map region (see `regions`)")
        p.add_argument("--bbox", help="custom map area: west,south,east,north")

    region_opts(sub.add_parser("list", help="every pack and whether it's installed"))
    region_opts(sub.add_parser("status", help="what's installed and how much space it takes"))
    sub.add_parser("regions", help="named map regions")
    a = sub.add_parser("add", help="download packs or a whole tier")
    a.add_argument("names", nargs="+", metavar="PACK|TIER")
    region_opts(a)
    a.add_argument("--skip", nargs="*", default=[], metavar="PACK", help="leave these packs out (e.g. routing addresses)")
    a.add_argument("--yes", "-y", action="store_true", help="don't ask")
    a.add_argument("--dry-run", action="store_true", help="show the plan and the space check only")
    a.add_argument("--force", action="store_true", help="download even if the space check fails")
    r = sub.add_parser("remove", help="delete packs")
    r.add_argument("names", nargs="+", metavar="PACK")
    region_opts(r)
    r.add_argument("--yes", "-y", action="store_true")
    v = sub.add_parser("verify", help="re-check installed files against their published hashes")
    v.add_argument("names", nargs="*", metavar="PACK")
    region_opts(v)
    v.add_argument("--zim", action="store_true", help="also hash ZIM files (slow; needs the internet for their hashes)")
    args = ap.parse_args(fetch.bbox_argv(argv))
    return {"list": cmd_list, "status": cmd_status, "regions": cmd_regions, "add": cmd_add, "remove": cmd_remove, "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
