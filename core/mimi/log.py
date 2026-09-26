"""Logging: one rotating file per component under <root>/logs, plus console."""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

_CONFIGURED = False


def setup_logging(logs_dir: Path, level: int = logging.INFO) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    logs_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(level)
    fh = logging.handlers.RotatingFileHandler(logs_dir / "core.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if sys.stderr is not None:  # pythonw has no console
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        root.addHandler(sh)
    for noisy in ("httpx", "httpcore", "uvicorn.access", "zeroconf", "faster_whisper", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True


def get(name: str) -> logging.Logger:
    return logging.getLogger(f"mimi.{name}")
