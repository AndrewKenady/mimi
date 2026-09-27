"""Community tools: drop-in Python modules in <root>/tools/ that the assistant can call.

A plugin is one ``.py`` file (or a folder with ``__init__.py``) that defines::

    NAME = "sun_times"                       # unique, [a-z0-9_]
    DESCRIPTION = "When the sun rises and sets at the current location."
    PARAMETERS = {"type": "object", "properties": {...}, "required": [...]}   # JSON schema
    LABEL = "Checked sunrise and sunset"     # optional, shown in the chat
    NEEDS = ["location"]                     # optional: only offered when these are available

    def run(args: dict, ctx) -> str | dict:  # may also be ``async def``
        ...

``ctx`` gives read-only context: ``user_name``, ``units`` ("imperial"/"metric"), ``location``
(``{"lat", "lon", "name"}`` or None), ``now`` (aware datetime), ``data_dir`` (a private
folder for the plugin) and ``find_place(name)``, which looks a place up on the offline map
and returns ``{"lat", "lon", "name"}`` or None. A dict result may carry ``text`` (for the model), ``label`` and ``data``.

Plugins run with the same rights as Mimi itself, so none is offered to the model until the
owner turns it on in Settings -> Tools.
"""

from __future__ import annotations

import asyncio
import importlib.util
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import log

L = log.get("plugins")
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


@dataclass
class PluginContext:
    user_name: str
    units: str
    location: dict | None
    now: datetime
    data_dir: Path
    find_place: Callable[[str], dict | None] = lambda name: None


@dataclass
class Plugin:
    name: str
    file: Path
    description: str = ""
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})
    label: str = ""
    needs: list[str] = field(default_factory=list)
    module: Any = None
    error: str = ""

    def info(self) -> dict:
        return {"name": self.name, "file": self.file.name, "description": self.description,
                "needs": self.needs, "error": self.error, "builtin": False}


def _load_one(path: Path, taken: set[str]) -> Plugin:
    target = path / "__init__.py" if path.is_dir() else path
    stem = path.stem if path.is_file() else path.name
    p = Plugin(name=stem, file=path)
    try:
        spec = importlib.util.spec_from_file_location(f"mimi_tools.{stem}", target)
        if not spec or not spec.loader:
            raise ImportError("not a Python module")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        name = getattr(mod, "NAME", stem)
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise ValueError(f"NAME {name!r} must be lowercase letters, digits and underscores")
        if name in taken:
            raise ValueError(f"the name {name!r} is already used by another tool")
        if not callable(getattr(mod, "run", None)):
            raise ValueError("the module has no run(args, ctx) function")
        params = getattr(mod, "PARAMETERS", None) or {"type": "object", "properties": {}}
        if not isinstance(params, dict) or params.get("type") != "object":
            raise ValueError("PARAMETERS must be a JSON schema object")
        p.name = name
        p.description = str(getattr(mod, "DESCRIPTION", "")).strip() or f"Community tool {name}."
        p.parameters = params
        p.label = str(getattr(mod, "LABEL", "") or "")
        p.needs = [str(x) for x in getattr(mod, "NEEDS", []) or []]
        p.module = mod
    except Exception as e:  # a broken plugin is reported in Settings, never fatal
        p.error = f"{type(e).__name__}: {e}"
        L.warning("tool plugin %s failed to load: %s", path.name, p.error)
    return p


def discover(folder: Path, taken: set[str]) -> list[Plugin]:
    """Import every plugin in ``folder``. ``taken`` holds names already in use (the built-ins)."""
    out: list[Plugin] = []
    if not folder.is_dir():
        return out
    names = set(taken)
    for path in sorted(folder.iterdir()):
        if path.name.startswith(("_", ".")):
            continue
        if not (path.suffix == ".py" or (path.is_dir() and (path / "__init__.py").exists())):
            continue
        p = _load_one(path, names)
        if not p.error:
            names.add(p.name)
        out.append(p)
    if out:
        L.info("tool plugins: %s", ", ".join(p.name + (" (error)" if p.error else "") for p in out))
    return out


async def call(p: Plugin, args: dict, ctx: PluginContext) -> dict:
    """Run a plugin and normalise its result to {text, label, data}."""
    ctx.data_dir.mkdir(parents=True, exist_ok=True)
    fn = p.module.run
    if asyncio.iscoroutinefunction(fn):
        res = await fn(args, ctx)
    else:
        res = await asyncio.to_thread(fn, args, ctx)
    if isinstance(res, dict):
        return {"text": str(res.get("text", "")), "label": str(res.get("label") or p.label or f"Used {p.name}"),
                "data": res.get("data") or {}}
    return {"text": str(res), "label": p.label or f"Used {p.name}", "data": {}}
