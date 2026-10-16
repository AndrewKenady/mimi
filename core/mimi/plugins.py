"""Community tools: drop-in Python modules in <root>/tools/ that the assistant can call.

A plugin is one ``.py`` file (or a folder with ``__init__.py``) with a manifest of plain
top-level literals and a ``run`` function (full guide: tools/README.md)::

    MIMI_API = 1                             # plugin API version (see API_VERSION)
    NAME = "sun_times"                       # unique, [a-z][a-z0-9_]
    DESCRIPTION = "When the sun rises and sets at the current location."
    PARAMETERS = {"type": "object", "properties": {...}, "required": [...]}   # JSON schema
    LABEL = "Checked sunrise and sunset"     # optional, shown in the chat
    NEEDS = ["location"]                     # optional: only offered when these are available
    USES = ["location", "places"]            # optional: context the tool may read (least privilege)
    SIDE_EFFECTS = False                     # required in API 1: does it change anything?
    TIMEOUT = 20                             # optional, seconds (at most 45)

    def run(args: dict, ctx) -> str | dict:  # may also be ``async def``
        ...

How Mimi treats a plugin:

* **Discovery never runs plugin code.** The manifest is read with ``ast`` (literals only), so a
  file sitting in tools/ does nothing until the owner enables it in Settings -> Tools.
* **Arguments are validated** against PARAMETERS (a small JSON-schema subset, see
  ``validate_args``) before the plugin sees them; unknown keys are dropped.
* **Each enabled plugin runs in its own worker process** (multiprocessing "spawn"), started on
  first use. A call that runs past its timeout gets the process killed, so a hung plugin can't
  leak threads or wedge Core; the next call starts a fresh worker. This is isolation for
  robustness, **not a sandbox**: plugin code runs with the user's rights, which is why only
  the owner can enable it.
* ``ctx`` is a ``PluginContext``: ``user_name``, ``units``, ``now`` and a private ``data_dir``
  always; ``location`` only when USES/NEEDS include "location"; ``find_place(name)`` (an offline
  map lookup, answered by Core over the worker pipe) only when USES includes "places".
  Plugins written before MIMI_API existed get everything, and count as having side effects.
* SIDE_EFFECTS feeds the prompt-injection policy in tools.py: a side-effecting tool called
  after the model has read untrusted content needs the user's own message to ask for it.
"""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import multiprocessing as mp
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import log

L = log.get("plugins")
API_VERSION = 1
SUPPORTED_APIS = (1,)
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
MAX_TIMEOUT = 45.0
MAX_SOURCE_BYTES = 1_000_000
MAX_TEXT = 20_000
KNOWN_NEEDS = ("location", "vision")
KNOWN_USES = ("location", "places")
MANIFEST = ("MIMI_API", "NAME", "DESCRIPTION", "PARAMETERS", "LABEL", "NEEDS", "USES", "SIDE_EFFECTS", "TIMEOUT")


class PluginError(Exception):
    pass


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
    uses: list[str] = field(default_factory=list)
    side_effects: bool = True
    timeout: float = MAX_TIMEOUT
    api: int = 0  # 0 = written before MIMI_API (legacy contract)
    error: str = ""

    def info(self) -> dict:
        return {"name": self.name, "file": self.file.name, "description": self.description, "needs": self.needs,
                "uses": self.uses, "side_effects": self.side_effects, "api": self.api, "error": self.error, "builtin": False}


# --------------------------------------------------------------------------- manifest (static)
def _source_file(path: Path) -> Path:
    return path / "__init__.py" if path.is_dir() else path


def read_manifest(path: Path) -> tuple[dict, bool]:
    """Top-level manifest literals and whether a top-level ``run`` exists, without importing."""
    src = _source_file(path)
    if src.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("the file is too large to be a tool")
    tree = ast.parse(src.read_bytes(), filename=str(src))
    found: dict[str, Any] = {}
    has_run = False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run":
            has_run = True
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        for t in targets:
            if isinstance(t, ast.Name) and t.id in MANIFEST:
                try:
                    found[t.id] = ast.literal_eval(value)
                except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                    raise ValueError(f"{t.id} must be a plain literal (Mimi reads it without running the file)") from None
    return found, has_run


def _load_one(path: Path, taken: set[str]) -> Plugin:
    stem = path.stem if path.is_file() else path.name
    p = Plugin(name=stem, file=path)
    try:
        m, has_run = read_manifest(path)
        api = m.get("MIMI_API", 0)
        if api != 0 and api not in SUPPORTED_APIS:
            raise ValueError(f"MIMI_API {api!r} isn't supported by this Mimi (supported: {', '.join(map(str, SUPPORTED_APIS))})")
        name = m.get("NAME", stem)
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise ValueError(f"NAME {name!r} must be lowercase letters, digits and underscores")
        if name in taken:
            raise ValueError(f"the name {name!r} is already used by another tool")
        if not has_run:
            raise ValueError("the module has no run(args, ctx) function")
        params = m.get("PARAMETERS") or {"type": "object", "properties": {}}
        problem = schema_problem(params)
        if problem:
            raise ValueError(f"PARAMETERS: {problem}")
        needs = m.get("NEEDS") or []
        uses = m.get("USES")
        if not isinstance(needs, list) or any(x not in KNOWN_NEEDS for x in needs):
            raise ValueError(f"NEEDS may only list {', '.join(KNOWN_NEEDS)}")
        if api == 0:  # legacy: full context, unknown effects
            uses, side = list(KNOWN_USES), True
        else:
            if uses is not None and (not isinstance(uses, list) or any(x not in KNOWN_USES for x in uses)):
                raise ValueError(f"USES may only list {', '.join(KNOWN_USES)}")
            if not isinstance(m.get("SIDE_EFFECTS"), bool):
                raise ValueError("SIDE_EFFECTS = True or False is required (does the tool change anything?)")
            side = m["SIDE_EFFECTS"]
            uses = list(dict.fromkeys([*(uses or []), *(["location"] if "location" in needs else [])]))
        timeout = m.get("TIMEOUT", MAX_TIMEOUT)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= MAX_TIMEOUT:
            raise ValueError(f"TIMEOUT must be between 1 and {MAX_TIMEOUT:g} seconds")
        p.name, p.api, p.parameters, p.needs, p.uses, p.side_effects, p.timeout = name, api, params, list(needs), uses, side, float(timeout)
        p.description = str(m.get("DESCRIPTION", "")).strip()[:1024] or f"Community tool {name}."
        p.label = str(m.get("LABEL", "") or "")[:80]
    except Exception as e:  # a broken plugin is reported in Settings, never fatal
        p.error = f"{type(e).__name__}: {e}"
        L.warning("tool plugin %s can't be used: %s", path.name, p.error)
    return p


def discover(folder: Path, taken: set[str]) -> list[Plugin]:
    """Read every plugin manifest in ``folder`` (no plugin code runs). ``taken`` holds names
    already in use (the built-ins)."""
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


# --------------------------------------------------------------------------- argument validation
_TYPES = ("object", "array", "string", "number", "integer", "boolean", "null")
_KEYWORDS = {"type", "properties", "required", "enum", "items", "description", "default", "title", "minimum", "maximum",
             "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength", "pattern", "minItems", "maxItems",
             "additionalProperties", "examples", "format"}


def schema_problem(schema: Any, path: str = "", depth: int = 0) -> str | None:
    """Why a PARAMETERS schema can't be used (None when it's fine). Mimi supports the subset
    in _KEYWORDS; anything else would be silently unenforced, so it's refused up front."""
    if depth > 8:
        return "nested too deeply"
    if not isinstance(schema, dict):
        return f"{path or 'the schema'} must be an object"
    if depth == 0 and schema.get("type") != "object":
        return 'the top level must be {"type": "object", ...}'
    unknown = set(schema) - _KEYWORDS
    if unknown:
        return f"{path or 'the schema'} uses unsupported keywords: {', '.join(sorted(unknown))}"
    t = schema.get("type")
    for ty in (t if isinstance(t, list) else [t] if t else []):
        if ty not in _TYPES:
            return f"{path or 'the schema'} has an unknown type {ty!r}"
    if "properties" in schema:
        if not isinstance(schema["properties"], dict):
            return f"{path}.properties must be an object"
        for k, sub in schema["properties"].items():
            pr = schema_problem(sub, f"{path}.{k}" if path else k, depth + 1)
            if pr:
                return pr
    if "items" in schema:
        pr = schema_problem(schema["items"], f"{path}[]", depth + 1)
        if pr:
            return pr
    if "required" in schema and not (isinstance(schema["required"], list) and all(isinstance(x, str) for x in schema["required"])):
        return f"{path or 'the schema'}: required must be a list of names"
    if "enum" in schema and not isinstance(schema["enum"], list):
        return f"{path or 'the schema'}: enum must be a list"
    if "pattern" in schema:
        try:
            re.compile(schema["pattern"])
        except (re.error, TypeError):
            return f"{path or 'the schema'}: pattern isn't a valid regular expression"
    return None


def _is(v: Any, ty: str) -> bool:
    return {"object": isinstance(v, dict), "array": isinstance(v, list), "string": isinstance(v, str),
            "number": isinstance(v, (int, float)) and not isinstance(v, bool),
            "integer": isinstance(v, int) and not isinstance(v, bool),
            "boolean": isinstance(v, bool), "null": v is None}.get(ty, False)


def _coerce(v: Any, types: list[str]) -> Any:
    """Small models often quote numbers or booleans; accept the obvious readings."""
    if any(_is(v, t) for t in types):
        return v
    for t in types:
        if t in ("number", "integer") and isinstance(v, str):
            s = v.strip().replace("_", "")
            try:
                f = float(s)
            except ValueError:
                continue
            if t == "integer" and f.is_integer():
                return int(f)
            if t == "number" and f == f and abs(f) != float("inf"):
                return int(f) if re.fullmatch(r"-?\d+", s) else f
        if t == "integer" and isinstance(v, float) and v.is_integer():
            return int(v)
        if t == "boolean" and isinstance(v, str) and v.strip().lower() in ("true", "false", "yes", "no"):
            return v.strip().lower() in ("true", "yes")
        if t == "string" and isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(v)
    return v


def _check(schema: dict, v: Any, path: str, errors: list[str], lenient: bool, depth: int = 0) -> Any:
    where = path or "arguments"
    if depth > 10:
        errors.append(f"{where} is nested too deeply")
        return v
    t = schema.get("type")
    types = t if isinstance(t, list) else [t] if t else []
    if types:
        v = _coerce(v, types)
        if not any(_is(v, ty) for ty in types):
            errors.append(f"{where} should be {' or '.join(types)}, not {type(v).__name__}")
            return v
    if "enum" in schema and v not in schema["enum"]:
        match = [e for e in schema["enum"] if isinstance(e, str) and isinstance(v, str) and e.lower() == v.strip().lower()]
        if match:
            v = match[0]
        else:
            errors.append(f"{where} must be one of {', '.join(map(str, schema['enum']))}")
            return v
    if isinstance(v, str):
        if len(v) < schema.get("minLength", 0):
            errors.append(f"{where} is too short")
        if "maxLength" in schema and len(v) > schema["maxLength"]:
            errors.append(f"{where} is longer than {schema['maxLength']} characters")
        if "pattern" in schema and not re.search(schema["pattern"], v):
            errors.append(f"{where} doesn't match the expected format")
    elif _is(v, "number"):
        if "minimum" in schema and v < schema["minimum"] or "exclusiveMinimum" in schema and v <= schema["exclusiveMinimum"]:
            errors.append(f"{where} is too small")
        if "maximum" in schema and v > schema["maximum"] or "exclusiveMaximum" in schema and v >= schema["exclusiveMaximum"]:
            errors.append(f"{where} is too large")
    elif isinstance(v, list):
        if len(v) < schema.get("minItems", 0) or ("maxItems" in schema and len(v) > schema["maxItems"]):
            errors.append(f"{where} has the wrong number of items")
        if isinstance(schema.get("items"), dict):
            v = [_check(schema["items"], x, f"{where}[{i}]", errors, lenient, depth + 1) for i, x in enumerate(v)]
    elif isinstance(v, dict):
        props = schema.get("properties") or {}
        required = schema.get("required") or []
        extra = schema.get("additionalProperties", False)
        out = {}
        for k, x in v.items():
            sub = props.get(k)
            if x is None and k not in required and not (sub and "null" in (sub.get("type") if isinstance(sub.get("type"), list) else [sub.get("type")])):
                continue  # {"origin": null} means "not given"
            if sub is None:
                if extra is True:
                    out[k] = x
                elif isinstance(extra, dict):
                    out[k] = _check(extra, x, f"{path}.{k}" if path else k, errors, lenient, depth + 1)
                continue  # unknown keys are dropped
            sub_errors: list[str] = []
            val = _check(sub, x, f"{path}.{k}" if path else k, sub_errors, lenient, depth + 1)
            if sub_errors and lenient and k not in required:
                continue  # built-in tools fall back to their default for a bad optional argument
            errors.extend(sub_errors)
            out[k] = val
        for k in required:
            if k not in out and not lenient:  # built-ins have their own fallbacks (e.g. the user's question)
                errors.append(f"missing required argument '{k}'")
        v = out
    return v


def validate_args(schema: dict, args: Any, *, lenient: bool = False) -> tuple[dict, list[str]]:
    """Check (and lightly coerce) tool arguments against a JSON schema subset.

    Returns (clean_args, errors). Unknown keys are dropped; numeric/boolean strings are
    converted. ``lenient`` (used for built-in tools) drops invalid optional arguments
    instead of failing."""
    if not isinstance(args, dict):
        return {}, ["arguments must be a JSON object"]
    errors: list[str] = []
    clean = _check(schema or {"type": "object"}, args, "", errors, lenient)
    return (clean if isinstance(clean, dict) else {}), errors


# --------------------------------------------------------------------------- worker processes
def _import_plugin(file: str, module_name: str):
    path = Path(file)
    target = _source_file(path)
    spec = importlib.util.spec_from_file_location(module_name, target,
                                                  submodule_search_locations=[str(path)] if path.is_dir() else None)
    if not spec or not spec.loader:
        raise ImportError("not a Python module")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    if not callable(getattr(mod, "run", None)):
        raise ImportError("the module has no run(args, ctx) function")
    return mod


def _jsonable(x: Any) -> Any:
    try:
        return json.loads(json.dumps(x, default=str))
    except (TypeError, ValueError):
        return {}


def _normalise(res: Any) -> dict:
    if isinstance(res, dict):
        data = _jsonable(res.get("data") or {})
        return {"text": str(res.get("text", ""))[:MAX_TEXT], "label": str(res.get("label") or "")[:80] or None,
                "data": data if isinstance(data, dict) else {"value": data}, "untrusted": res.get("untrusted") is True}
    return {"text": str(res)[:MAX_TEXT], "label": None, "data": {}, "untrusted": False}


def _worker_main(conn, file: str, module_name: str) -> None:  # pragma: no cover - runs in the child process
    """Child process: import the plugin once, then answer calls until the pipe closes."""
    mod, load_error = None, None
    try:
        mod = _import_plugin(file, module_name)
    except BaseException as e:
        load_error = f"{type(e).__name__}: {e}"
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        if msg[0] != "call":
            continue
        if load_error:
            conn.send(("error", load_error))
            continue
        _, args, c = msg

        def find_place(name: str, _conn=conn):
            _conn.send(("find_place", str(name)[:200]))
            kind, value = _conn.recv()
            return value if kind == "place" else None

        ctx = PluginContext(user_name=c["user_name"], units=c["units"], location=c["location"], now=c["now"],
                            data_dir=Path(c["data_dir"]), find_place=find_place if c["places"] else (lambda name: None))
        try:
            res = mod.run(args, ctx)
            if asyncio.iscoroutine(res):
                res = asyncio.run(res)
            conn.send(("result", _normalise(res)))
        except BaseException as e:
            conn.send(("error", f"{type(e).__name__}: {e}"))


class _Worker:
    def __init__(self, plugin: Plugin):
        self.plugin = plugin
        self.proc = None
        self.conn = None
        self.mtime = 0.0
        self.lock = threading.Lock()

    def _start(self) -> None:
        ctx = mp.get_context("spawn")
        parent, child = ctx.Pipe()
        f = self.plugin.file
        self.mtime = _source_file(f).stat().st_mtime
        self.proc = ctx.Process(target=_worker_main, args=(child, str(f), f"mimi_tools.{self.plugin.name}"),
                                name=f"mimi-tool-{self.plugin.name}", daemon=True)
        self.proc.start()
        child.close()
        self.conn = parent

    def stop(self) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            except OSError:
                pass
        if self.proc is not None and self.proc.is_alive():
            self.proc.kill()
            self.proc.join(2)
        self.proc = self.conn = None

    def call(self, args: dict, c: dict, find_place: Callable[[str], dict | None], deadline: float) -> dict:
        if not self.lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
            raise TimeoutError
        try:
            changed = self.proc is not None and _source_file(self.plugin.file).stat().st_mtime != self.mtime
            if self.proc is None or not self.proc.is_alive() or changed:
                self.stop()
                self._start()
            assert self.conn is not None and self.proc is not None
            self.conn.send(("call", args, c))
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    self.stop()  # hard stop: the process (and anything it was doing) is killed
                    raise TimeoutError
                if not self.conn.poll(min(left, 0.25)):
                    if not self.proc.is_alive():
                        self.stop()
                        raise PluginError("the tool's process exited unexpectedly")
                    continue
                try:
                    kind, value = self.conn.recv()
                except (EOFError, OSError):
                    self.stop()
                    raise PluginError("the tool's process exited unexpectedly") from None
                if kind == "find_place":
                    try:
                        place = find_place(value)
                    except Exception:
                        place = None
                    self.conn.send(("place", _jsonable(place) if place else None))
                elif kind == "result":
                    return value
                else:
                    raise PluginError(value)
        finally:
            self.lock.release()


_WORKERS: dict[str, _Worker] = {}
_WORKERS_LOCK = threading.Lock()


def _worker_for(p: Plugin) -> _Worker:
    with _WORKERS_LOCK:
        w = _WORKERS.get(p.name)
        if w is None or w.plugin.file != p.file:
            if w:
                w.stop()
            w = _WORKERS[p.name] = _Worker(p)
        w.plugin = p
        return w


def stop_workers() -> None:
    """Stop every plugin process (on "Rescan folder" and at shutdown)."""
    with _WORKERS_LOCK:
        ws = list(_WORKERS.values())
        _WORKERS.clear()
    for w in ws:
        w.stop()


def _ctx_payload(p: Plugin, ctx: PluginContext) -> dict:
    return {"user_name": ctx.user_name, "units": ctx.units, "now": ctx.now, "data_dir": str(ctx.data_dir),
            "location": ctx.location if "location" in p.uses else None, "places": "places" in p.uses}


async def call(p: Plugin, args: dict, ctx: PluginContext, timeout: float | None = None) -> dict:
    """Run a plugin in its worker process and normalise the result to {text, label, data}.
    Raises TimeoutError (after killing the worker) or PluginError."""
    ctx.data_dir.mkdir(parents=True, exist_ok=True)
    limit = min(timeout or p.timeout, p.timeout, MAX_TIMEOUT)
    deadline = time.monotonic() + limit
    res = await asyncio.to_thread(_worker_for(p).call, args, _ctx_payload(p, ctx), ctx.find_place, deadline)
    return {"text": res["text"], "label": res["label"] or p.label or f"Used {p.name}", "data": res["data"], "untrusted": res["untrusted"]}


# --------------------------------------------------------------------------- test harness
def run_file(path: str | Path, args: dict | None = None, *, location: dict | None = None, units: str = "metric",
             user_name: str = "Tester", places: dict[str, dict] | None = None, data_dir: str | Path | None = None,
             timeout: float | None = None) -> dict:
    """Load a plugin the way Mimi does (manifest check, argument validation, worker process)
    and call it once. For contributors' tests and ``python -m mimi plugin test``::

        from mimi.plugins import run_file
        r = run_file("tools/my_tool.py", {"value": 3}, location={"lat": 51.5, "lon": -0.12, "name": "London"})
        assert "..." in r["text"]

    Raises PluginError for an invalid manifest or arguments."""
    import tempfile

    path = Path(path).resolve()
    p = _load_one(path, set())
    if p.error:
        raise PluginError(p.error)
    clean, errors = validate_args(p.parameters, args or {})
    if errors:
        raise PluginError("invalid arguments: " + "; ".join(errors))
    places = {k.lower(): v for k, v in (places or {}).items()}
    ctx = PluginContext(user_name=user_name, units=units, location=location, now=datetime.now().astimezone(),
                        data_dir=Path(data_dir or tempfile.mkdtemp(prefix=f"mimi-{p.name}-")),
                        find_place=lambda name: places.get(str(name).lower()))
    try:
        return {**asyncio.run(call(p, clean, ctx, timeout)), "args": clean, "manifest": p.info()}
    finally:
        w = _WORKERS.pop(p.name, None)
        if w:
            w.stop()


def cli(argv: list[str]) -> int:
    """``python -m mimi plugin check [folder]`` / ``python -m mimi plugin test FILE [--args JSON] ...``"""
    import argparse

    ap = argparse.ArgumentParser(prog="mimi plugin", description="Check and try community tools")
    sub = ap.add_subparsers(dest="action", required=True)
    c = sub.add_parser("check", help="read every manifest in a folder (no plugin code runs)")
    c.add_argument("folder", nargs="?", default="tools")
    t = sub.add_parser("test", help="call one tool the way Mimi would")
    t.add_argument("file")
    t.add_argument("--args", default="{}", help='JSON arguments, e.g. \'{"value": 32, "from_unit": "psi", "to_unit": "kPa"}\'')
    t.add_argument("--location", help="LAT,LON[,NAME] for ctx.location")
    t.add_argument("--place", action="append", default=[], help="NAME=LAT,LON answered by ctx.find_place (repeatable)")
    t.add_argument("--units", choices=["metric", "imperial"], default="metric")
    t.add_argument("--timeout", type=float)
    a = ap.parse_args(argv)
    if a.action == "check":
        found = discover(Path(a.folder), set())
        for p in found:
            status = f"ERROR {p.error}" if p.error else (f"ok  api={p.api or 'legacy'} side_effects={p.side_effects} "
                                                         f"uses={','.join(p.uses) or '-'} timeout={p.timeout:g}s")
            print(f"{p.file.name:28} {p.name:24} {status}")
        return 1 if any(p.error for p in found) else 0

    def latlon(s: str) -> dict:
        bits = s.split(",", 2)
        return {"lat": float(bits[0]), "lon": float(bits[1]), "name": bits[2] if len(bits) > 2 else None}

    places = {}
    for spec in a.place:
        name, _, coords = spec.partition("=")
        places[name] = {**latlon(coords), "name": name}
    try:
        r = run_file(a.file, json.loads(a.args), location=latlon(a.location) if a.location else None, units=a.units,
                     places=places, timeout=a.timeout)
    except (PluginError, TimeoutError, ValueError) as e:
        print(f"error: {e or 'timed out'}", file=sys.stderr)
        return 1
    print(json.dumps({k: r[k] for k in ("label", "text", "data", "untrusted", "args")}, indent=2, ensure_ascii=False))
    return 0
