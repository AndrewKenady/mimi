"""Filesystem layout of a MIMI tree.

A MIMI tree is both the git repository and the portable install: source code
lives next to (git-ignored) runtimes and content. Every path is resolved
relative to the tree root so the whole folder can move between drives or run
from a USB stick.

    <root>/
      core/  ui/  shell/  config/  scripts/  manifests/   (source, committed)
      bin/win-x64/  python/                                (runtimes)
      models/  zim/  maps/                                 (content)
      data/  logs/                                         (personal / runtime)
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


def default_root() -> Path:
    env = os.environ.get("MIMI_HOME")
    if env:
        return Path(env).resolve()
    # core/mimi/paths.py -> core/mimi -> core -> <root>
    return Path(__file__).resolve().parents[2]


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
    def config(self) -> Path:
        return self.root / "config"

    @property
    def ui_build(self) -> Path:
        return self.root / "ui" / "build"

    # --- runtimes --------------------------------------------------------
    @property
    def bin(self) -> Path:
        plat = "win-x64" if sys.platform == "win32" else ("macos-arm64" if sys.platform == "darwin" else "linux-x64")
        return self.root / "bin" / plat

    def exe(self, *parts: str) -> Path:
        p = self.bin.joinpath(*parts)
        if sys.platform == "win32" and p.suffix == "":
            p = p.with_suffix(".exe")
        return p

    # --- content ---------------------------------------------------------
    @property
    def models(self) -> Path:
        return self.root / "models"

    @property
    def zim(self) -> Path:
        return self.root / "zim"

    @property
    def maps(self) -> Path:
        return self.root / "maps"

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
        return self.root / "logs"

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
        """Resolve a tree-relative path (as stored in config files)."""
        p = Path(p)
        return p if p.is_absolute() else self.root / p

    def inside(self, p: str | Path) -> bool:
        try:
            Path(p).resolve().relative_to(self.root)
            return True
        except ValueError:
            return False
