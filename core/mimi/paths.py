"""Filesystem layout of a Mimi tree.

A Mimi tree is both the git repository and the portable install: source code
lives next to (git-ignored) runtimes and content. Every path is resolved
relative to the tree root so the whole folder can move between drives or run
from a USB stick.

    <root>/
      core/  ui/  shell/  config/  scripts/  manifests/   (source, committed)
      bin/<platform>/  python/                             (runtimes; platform = win-x64,
                                                            linux-x64, linux-arm64, macos-arm64)
      models/  zim/  maps/                                 (content)
      data/  logs/                                         (personal / runtime)

Environment overrides (all optional; a plain checkout needs none of them):

    MIMI_HOME      the tree root (default: the folder this file lives in, two levels up)
    MIMI_CONTENT   where models/, zim/ and maps/ live, e.g. a big external drive or the
                   /data volume in Docker (default: the tree root)
    MIMI_DATA      personal data: accounts, chats, uploads (default: <root>/data)
    MIMI_LOGS      log folder (default: <root>/logs)
"""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path


def default_root() -> Path:
    env = os.environ.get("MIMI_HOME")
    if env:
        return Path(env).resolve()
    # core/mimi/paths.py -> core/mimi -> core -> <root>
    return Path(__file__).resolve().parents[2]


# Content folders: tree-relative paths starting with one of these (as stored in
# config/models.json) resolve under the content root, which may be elsewhere.
CONTENT_DIRS = ("models", "zim", "maps")


def platform_key(system: str | None = None, machine: str | None = None) -> str:
    """The bin/ folder name for this OS and CPU: win-x64, linux-x64, linux-arm64, macos-arm64, ...

    Must match scripts/fetch.py:platform_key and the keys in manifests/runtimes.json.
    """
    system = (system or sys.platform).lower()
    machine = (machine or platform.machine() or "").lower()
    os_name = "win" if system.startswith("win") else ("macos" if system == "darwin" else "linux")
    arch = "arm64" if machine in ("arm64", "aarch64", "armv8", "armv8l") else "x64"
    return f"{os_name}-{arch}"


@dataclass
class Paths:
    root: Path = field(default_factory=default_root)
    data_override: Path | None = None

    def __post_init__(self) -> None:
        self.root = Path(self.root).resolve()
        for d in (self.data, self.logs, self.uploads, self.library, self.notes, self.certs):
            d.mkdir(parents=True, exist_ok=True)

    # --- source / config -------------------------------------------------
    @property
    def portable(self) -> bool:
        """True for a drive made by scripts/make_drive.py (it leaves a portable.json marker)."""
        return (self.root / "portable.json").exists()

    @property
    def config(self) -> Path:
        return self.root / "config"

    @property
    def ui_build(self) -> Path:
        return self.root / "ui" / "build"

    # --- runtimes --------------------------------------------------------
    @property
    def bin(self) -> Path:
        return self.root / "bin" / platform_key()

    def exe(self, *parts: str) -> Path:
        p = self.bin.joinpath(*parts)
        if sys.platform == "win32" and p.suffix == "":
            p = p.with_suffix(".exe")
        return p

    # --- content ---------------------------------------------------------
    @property
    def content(self) -> Path:
        env = os.environ.get("MIMI_CONTENT")
        return Path(env).resolve() if env else self.root

    @property
    def models(self) -> Path:
        return self.content / "models"

    @property
    def zim(self) -> Path:
        return self.content / "zim"

    @property
    def maps(self) -> Path:
        return self.content / "maps"

    # --- personal / runtime ----------------------------------------------
    @property
    def data(self) -> Path:
        if self.data_override:
            return Path(self.data_override)
        env = os.environ.get("MIMI_DATA")  # alternate profile, e.g. for demos and tests
        return Path(env) if env else self.root / "data"

    @property
    def db_file(self) -> Path:
        return self.data / "mimi.db"

    @property
    def logs(self) -> Path:
        env = os.environ.get("MIMI_LOGS")
        return Path(env) if env else self.root / "logs"

    @property
    def uploads(self) -> Path:
        return self.data / "uploads"

    @property
    def library(self) -> Path:
        return self.data / "library"

    @property
    def notes(self) -> Path:
        return self.data / "notes"

    @property
    def certs(self) -> Path:
        return self.data / "certs"

    def rel(self, p: str | Path) -> Path:
        """Resolve a tree-relative path (as stored in config files).

        models/..., zim/... and maps/... resolve under the content root (see MIMI_CONTENT).
        """
        p = Path(p)
        if p.is_absolute():
            return p
        if p.parts and p.parts[0] in CONTENT_DIRS:
            return self.content / p
        return self.root / p

    def inside(self, p: str | Path) -> bool:
        try:
            Path(p).resolve().relative_to(self.root)
            return True
        except ValueError:
            return False
