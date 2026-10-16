#!/usr/bin/env python3
"""Install Mimi from this folder on Linux or macOS (Windows: scripts/setup.ps1).

    python3 scripts/install.py                              # Lite tier (~15 GB + a map region)
    python3 scripts/install.py --tier standard --region us-canada
    python3 scripts/install.py --tier lite --region uk
    python3 scripts/install.py --tier none                  # code + engines only; add content later
    python3 scripts/install.py --dry-run                    # show the plan and the space check

Most people run scripts/install.sh instead, which fetches uv (a Python manager),
gets Python 3.12 with it and then runs this file. Steps, each safe to re-run:

  1. Python environment   <root>/python, a virtualenv with Mimi Core and its packages
  2. Engines              llama.cpp, kiwix-serve, pmtiles for this OS (scripts/fetch.py)
  3. App UI               ui/build (Node 20+; a pinned, checksummed Node is fetched if missing)
  4. Content              the tier's packs (scripts/content.py add <tier>), after a space check

Then start Mimi with  <root>/python/bin/mimi serve  and open http://localhost:7600.
Stdlib only, so it runs on any Python 3.11+.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch  # noqa: E402
from fetch import ROOT, say  # noqa: E402

PYTHON = "3.12"
# Packages Core needs beyond core/pyproject.toml: Valhalla (directions) and osmium (map builds).
EXTRAS = ["pyvalhalla>=3.9,<4", "osmium>=4,<5"]
NODE = {  # pinned Node.js LTS for building the UI when the system has no Node 20+
    "version": "v22.23.3",
    "linux-x64": ("node-v22.23.3-linux-x64.tar.xz", "df450af89261115ef9f9e3830c3eeb2cc9213b63c720b1af623cb5dcbe2e02de"),
    "linux-arm64": ("node-v22.23.3-linux-arm64.tar.xz", "a44aeb94849a299b22df10b9e622ec2f605c2183501bc40590705131de7c740f"),
    "macos-arm64": ("node-v22.23.3-darwin-arm64.tar.gz", "23b25245dcfb9af7262f8ff142e9e2e0af025368117329e7a7458a51e5922f53"),
    "win-x64": ("node-v22.23.3-win-x64.zip", "2b0ff57b049cda1bbcea2240eec20467018713c1efe1f7360c2681859b90ed71"),
}
VENV = ROOT / "python"


def step(title: str) -> None:
    say(f"\n== {title}")


def run(cmd: list, dry: bool, **kw) -> None:
    say("   $ " + " ".join(str(c) for c in cmd))
    if not dry:
        subprocess.run([str(c) for c in cmd], check=True, **kw)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


# --------------------------------------------------------------------------- 1. Python
def find_uv(explicit: str | None) -> str | None:
    for c in (explicit, os.environ.get("MIMI_UV"), str(ROOT / ".tools" / "uv" / "uv"), shutil.which("uv")):
        if c and Path(c).exists():
            return c
    return None


def python_env(args) -> None:
    step("1. Python environment")
    if os.name == "nt":
        say("   On Windows the portable Python comes from scripts/setup.ps1; skipping.")
        return
    uv = find_uv(args.uv)
    py = venv_python()
    env = dict(os.environ)
    if uv:
        env.update(UV_PYTHON_INSTALL_DIR=str(ROOT / ".tools" / "pythons"), UV_CACHE_DIR=str(ROOT / ".tools" / "uv-cache"))
        if not py.exists():
            run([uv, "venv", "--python", PYTHON, VENV], args.dry_run, env=env)
        run([uv, "pip", "install", "--python", py, "-r", ROOT / "core" / "pyproject.toml", *EXTRAS], args.dry_run, env=env)
    else:
        if sys.version_info < (3, 11):
            raise SystemExit("Mimi needs Python 3.11+ (3.12 recommended). Run scripts/install.sh, which fetches one for you.")
        extras = EXTRAS if sys.version_info >= (3, 12) else EXTRAS[1:]
        if sys.version_info < (3, 12):
            say("   note: offline directions (pyvalhalla) need Python 3.12+; skipping them. scripts/install.sh gets 3.12.")
        if not py.exists():
            run([sys.executable, "-m", "venv", VENV], args.dry_run)
        run([py, "-m", "pip", "install", "--upgrade", "pip"], args.dry_run)
        reqs = ROOT / ".tools" / "core-requirements.txt"
        if not args.dry_run:  # pip can't read dependencies from pyproject.toml without building the project
            import tomllib

            reqs.parent.mkdir(parents=True, exist_ok=True)
            reqs.write_text("\n".join(tomllib.loads((ROOT / "core" / "pyproject.toml").read_text("utf-8"))["project"]["dependencies"]))
        run([py, "-m", "pip", "install", "-r", reqs, *extras], args.dry_run)
    link_core(args.dry_run)
    write_launcher(args.dry_run)


def link_core(dry: bool) -> None:
    """Make `import mimi` find core/ (what an editable install does, without building a package)."""
    if dry:
        say("   + mimi-core.pth -> core/")
        return
    site = subprocess.run([str(venv_python()), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                          capture_output=True, text=True, check=True).stdout.strip()
    (Path(site) / "mimi-core.pth").write_text(str(ROOT / "core") + "\n", "utf-8")
    say(f"   + {Path(site) / 'mimi-core.pth'} -> core/")


def write_launcher(dry: bool) -> None:
    """python/bin/mimi: `mimi serve`, `mimi content add ...`, remembering MIMI_CONTENT if one was used."""
    launcher = VENV / "bin" / "mimi"
    content = os.environ.get("MIMI_CONTENT")
    body = "#!/bin/sh\n# Written by scripts/install.py\n"
    if content:
        body += f'export MIMI_CONTENT="${{MIMI_CONTENT:-{content}}}"\n'
    body += f'exec "{venv_python()}" -m mimi "$@"\n'
    say(f"   launcher: {launcher}")
    if not dry:
        launcher.parent.mkdir(parents=True, exist_ok=True)
        launcher.write_text(body, "utf-8")
        launcher.chmod(0o755)


# --------------------------------------------------------------------------- 2. engines
def engines(args) -> None:
    step(f"2. Engines for {args.platform or fetch.platform_key()}")
    fetch.install_runtimes(args.platform, dry=args.dry_run)


# --------------------------------------------------------------------------- 3. UI
def node_bin(dry: bool) -> Path | None:
    """A Node 20+ to build the UI with: the system's, or a pinned download in .tools/."""
    node = shutil.which("node")
    if node and shutil.which("npm"):
        try:
            v = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
            if int(v.lstrip("v").split(".")[0]) >= 20:
                return Path(node).parent
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    plat = fetch.platform_key()
    if plat not in NODE:
        return None
    name, sha = NODE[plat]
    folder = ROOT / ".tools" / name.split(".tar")[0].removesuffix(".zip")
    bindir = folder if plat.startswith("win") else folder / "bin"
    if (bindir / ("node.exe" if plat.startswith("win") else "node")).exists():
        return bindir
    archive = fetch.cache_dir() / "node" / name
    fetch.download(f"https://nodejs.org/dist/{NODE['version']}/{name}", archive, sha256=sha, dry=dry, label=f"Node.js {NODE['version']}")
    if dry:
        return bindir
    fetch.extract_tree(archive, folder, strip_root=True)
    archive.unlink(missing_ok=True)
    return bindir


def build_ui(args) -> None:
    step("3. App UI")
    ui = ROOT / "ui"
    if (ui / "build" / "index.html").exists() and not args.rebuild_ui:
        say("   ✓ ui/build (pass --rebuild-ui to build it again)")
        return
    if args.no_ui:
        say("   skipped (--no-ui): Core will show a placeholder page until the UI is built.")
        return
    nb = node_bin(args.dry_run)
    if not nb:
        say("   ! No Node.js 20+ found and none published for this platform; install Node 20+ and re-run.")
        return
    env = dict(os.environ, PATH=f"{nb}{os.pathsep}{os.environ.get('PATH', '')}")
    npm = str(nb / ("npm.cmd" if os.name == "nt" else "npm")) if (nb / "npm").exists() or (nb / "npm.cmd").exists() else "npm"
    try:
        run([npm, "ci", "--no-audit", "--no-fund"], args.dry_run, cwd=ui, env=env)
        run([npm, "run", "build"], args.dry_run, cwd=ui, env=env)
    except (subprocess.CalledProcessError, OSError) as e:
        say(f"   ! The UI build failed ({e}). Core still runs; fix the error above and re-run with --rebuild-ui.")


# --------------------------------------------------------------------------- 4. content
def content(args) -> int:
    step(f"4. Content: {args.tier}")
    if args.tier == "none":
        say("   skipped. Add content any time:  python3 scripts/content.py add lite")
        return 0
    import content as cm

    argv = ["add", args.tier, "--yes"]
    if args.region:
        argv += ["--region", args.region]
    if args.bbox:
        argv += [f"--bbox={args.bbox}"]
    skip = [p for p, off in (("routing", args.no_routing), ("addresses", args.no_addresses)) if off]
    if skip:
        argv += ["--skip", *skip]
    if args.dry_run:
        argv.append("--dry-run")
    if args.force:
        argv.append("--force")
    return cm.main(argv)


def desktop_entry(dry: bool) -> None:
    """A menu entry (Linux desktops, Steam Deck desktop mode) that starts Mimi and opens it."""
    if not sys.platform.startswith("linux"):
        return
    apps = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications"
    script = VENV / "bin" / "mimi-desktop"
    say(f"   desktop entry: {apps / 'mimi.desktop'}")
    if dry:
        return
    script.write_text(f"""#!/bin/sh
# Start Mimi Core if it isn't running, then open it in the browser. Written by scripts/install.py.
if ! curl -fsS http://127.0.0.1:7600/api/health >/dev/null 2>&1; then
  nohup "{VENV / 'bin' / 'mimi'}" serve >/dev/null 2>&1 &
  i=0; while [ $i -lt 60 ] && ! curl -fsS http://127.0.0.1:7600/api/health >/dev/null 2>&1; do sleep 0.5; i=$((i+1)); done
fi
exec xdg-open http://localhost:7600
""", "utf-8")
    script.chmod(0o755)
    apps.mkdir(parents=True, exist_ok=True)
    icon = ROOT / "ui" / "static" / "icon-512.png"
    (apps / "mimi.desktop").write_text(f"""[Desktop Entry]
Type=Application
Name=Mimi
Comment=Offline AI field station
Exec={script}
Icon={icon if icon.exists() else 'applications-science'}
Terminal=false
Categories=Education;Science;
""", "utf-8")


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tier", default="lite", choices=[*fetch.tier_names(), "none"], help="content to download (default: lite)")
    ap.add_argument("--region", help="map region (python3 scripts/content.py regions); default: the tier's")
    ap.add_argument("--bbox", help="custom map area west,south,east,north instead of --region")
    ap.add_argument("--no-routing", action="store_true", help="skip the offline-directions build (standard tier)")
    ap.add_argument("--no-addresses", action="store_true", help="skip the street-address build (standard tier)")
    ap.add_argument("--no-ui", action="store_true", help="don't build the app UI")
    ap.add_argument("--rebuild-ui", action="store_true", help="build the UI even if ui/build exists")
    ap.add_argument("--skip-python", action="store_true", help="don't create/update the Python environment")
    ap.add_argument("--desktop", action="store_true", help="add a Mimi entry to the desktop's app menu (Linux)")
    ap.add_argument("--platform", help="engines for another platform key (e.g. linux-arm64)")
    ap.add_argument("--uv", help="path to uv (scripts/install.sh passes it)")
    ap.add_argument("--force", action="store_true", help="download content even if the space check fails")
    ap.add_argument("--dry-run", action="store_true", help="show what would happen; download nothing")
    args = ap.parse_args(fetch.bbox_argv(argv))

    say(f"Mimi installer: {ROOT}  ({fetch.platform_key()}, Python {sys.version.split()[0]})")
    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11 or newer is required.")
    try:
        if not args.skip_python:
            python_env(args)
        engines(args)
        build_ui(args)
        if args.desktop:
            desktop_entry(args.dry_run)
        rc = content(args)
    except subprocess.CalledProcessError as e:
        say(f"\n✗ {' '.join(map(str, e.cmd))} failed (exit {e.returncode}). Fix the error above and run the installer again; "
            "finished steps are skipped.")
        return 1
    except fetch.DownloadError as e:
        say(f"\n✗ {e}\nRun the installer again to retry; finished downloads are kept and partial ones resume.")
        return 1
    if args.dry_run:
        say("\n(dry run: nothing was changed)")
        return rc
    mimi = VENV / "bin" / "mimi" if os.name != "nt" else "python\\python.exe -m mimi"
    say(f"""
Mimi is installed{'' if rc == 0 else ' (some content is still missing: run the same command again to resume)'}.

  Start it:     {mimi} serve
  Then open:    http://localhost:7600
  Content:      python3 scripts/content.py list | status | add <pack> | remove <pack>
  Docs:         docs/INSTALL.md
""")
    return rc


if __name__ == "__main__":
    sys.exit(main())
