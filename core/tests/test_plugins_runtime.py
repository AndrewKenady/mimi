"""Plugin API v1: static manifests, argument validation, worker processes with hard timeouts."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

from mimi import plugins
from mimi.plugins import PluginContext, PluginError, discover, run_file, validate_args

ROOT = Path(__file__).resolve().parents[2]
V1 = 'MIMI_API = 1\nNAME = "{name}"\nDESCRIPTION = "test"\nSIDE_EFFECTS = False\n'


def _tool(folder: Path, name: str, body: str, header: str | None = None) -> Path:
    f = folder / f"{name}.py"
    f.write_text((V1.format(name=name) if header is None else header) + body, encoding="utf-8")
    return f


def test_discovery_never_runs_plugin_code(tmp_path):
    marker = tmp_path / "ran"
    _tool(tmp_path, "sneaky", f"open({str(marker)!r}, 'w').write('x')\ndef run(args, ctx):\n    return 'hi'\n")
    (found,) = discover(tmp_path, set())
    assert not found.error and not marker.exists()
    assert found.api == 1 and found.side_effects is False and found.uses == []


@pytest.mark.parametrize("header,error", [
    ('MIMI_API = 1\nNAME = "x_y"\n', "SIDE_EFFECTS"),
    ('MIMI_API = 9\nNAME = "x_y"\nSIDE_EFFECTS = False\n', "MIMI_API"),
    ('MIMI_API = 1\nNAME = "x_y"\nSIDE_EFFECTS = False\nPARAMETERS = dict(type="object")\n', "plain literal"),
    ('MIMI_API = 1\nNAME = "x_y"\nSIDE_EFFECTS = False\nPARAMETERS = {"type": "object", "oneOf": []}\n', "unsupported keywords"),
    ('MIMI_API = 1\nNAME = "x_y"\nSIDE_EFFECTS = False\nUSES = ["camera"]\n', "USES"),
    ('MIMI_API = 1\nNAME = "x_y"\nSIDE_EFFECTS = False\nTIMEOUT = 600\n', "TIMEOUT"),
    ('MIMI_API = 1\nNAME = "Bad Name"\nSIDE_EFFECTS = False\n', "NAME"),
])
def test_manifest_errors_are_reported(tmp_path, header, error):
    _tool(tmp_path, "x_y", "def run(args, ctx):\n    return ''\n", header=header)
    (p,) = discover(tmp_path, set())
    assert error in p.error


def test_legacy_plugins_keep_working_but_count_as_side_effecting(tmp_path):
    _tool(tmp_path, "old", "def run(args, ctx):\n    return ctx.location['name']\n", header='NAME = "old"\n')
    (p,) = discover(tmp_path, set())
    assert p.api == 0 and p.side_effects is True and set(p.uses) == {"location", "places"}
    assert run_file(p.file, {}, location={"lat": 1, "lon": 2, "name": "Here"})["text"] == "Here"


def test_argument_validation():
    schema = {"type": "object", "properties": {
        "value": {"type": "number", "minimum": 0}, "unit": {"type": "string", "enum": ["km", "mi"]},
        "count": {"type": "integer"}, "exact": {"type": "boolean"},
        "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 3}}, "required": ["value"]}
    ok, errs = validate_args(schema, {"value": "3.5", "unit": "KM", "count": "2", "exact": "true", "tags": ["a", 1], "evil": "x", "unit2": None})
    assert not errs and ok == {"value": 3.5, "unit": "km", "count": 2, "exact": True, "tags": ["a", "1"]}
    _, errs = validate_args(schema, {"unit": "parsecs", "value": -1, "tags": ["a", "b", "c", "d"]})
    assert any("one of" in e for e in errs) and any("too small" in e for e in errs) and any("items" in e for e in errs)
    _, errs = validate_args(schema, {"unit": "km"})
    assert errs == ["missing required argument 'value'"]
    assert validate_args(schema, ["not", "an", "object"])[1]
    # built-in tools: a bad optional argument is dropped rather than failing the call
    ok, errs = validate_args(schema, {"value": 1, "unit": "parsecs"}, lenient=True)
    assert ok == {"value": 1} and not errs


def test_parse_args_never_evaluates():
    from mimi.tools import parse_args

    assert parse_args('{"query": "x"}') == {"query": "x"}
    assert parse_args("{'query': 'it\\'s', 'n': True, 'm': None,}") == {"query": "it's", "n": True, "m": None}
    assert parse_args('{"query": "burns"} and then some text') == {"query": "burns"}
    assert parse_args("__import__('os').system('x')") == {}
    assert parse_args("{'a': __import__('os')}") == {}
    assert parse_args("[" * 100000) == {}
    assert parse_args("{" + '"a":' * 50000 + "1" + "}" * 50000) == {}


def test_hung_plugin_is_killed_on_timeout(tmp_path):
    _tool(tmp_path, "sleepy", "import time\ndef run(args, ctx):\n    time.sleep(60)\n", header=V1.format(name="sleepy") + "TIMEOUT = 1\n")
    (p,) = discover(tmp_path, set())
    ctx = PluginContext(user_name="t", units="metric", location=None, now=datetime.now().astimezone(), data_dir=tmp_path / "d")
    t0 = time.monotonic()
    with pytest.raises(TimeoutError):
        asyncio.run(plugins.call(p, {}, ctx))
    assert time.monotonic() - t0 < 10
    w = plugins._WORKERS[p.name]
    assert w.proc is None  # the worker process was killed, not left running in a thread
    plugins.stop_workers()


def test_worker_reports_import_errors_and_serves_find_place(tmp_path):
    _tool(tmp_path, "broken", "raise RuntimeError('nope')\ndef run(args, ctx):\n    return ''\n")
    with pytest.raises(PluginError, match="nope"):
        run_file(tmp_path / "broken.py")
    _tool(tmp_path, "where", "async def run(args, ctx):\n    p = ctx.find_place(args['q'])\n    return {'text': p['name'] if p else 'none', 'data': {'loc': ctx.location}}\n",
          header=V1.format(name="where") + 'USES = ["places"]\nPARAMETERS = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}\n')
    r = run_file(tmp_path / "where.py", {"q": "Oslo"}, location={"lat": 1, "lon": 2, "name": "Secret"},
                 places={"oslo": {"lat": 59.9, "lon": 10.7, "name": "Oslo"}})
    assert r["text"] == "Oslo"
    assert r["data"]["loc"] is None  # didn't declare "location": least privilege
    with pytest.raises(PluginError, match="missing required"):
        run_file(tmp_path / "where.py", {})


def test_example_tools_through_the_harness():
    conv = run_file(ROOT / "tools" / "unit_converter.py", {"value": "32", "from_unit": "psi", "to_unit": "kPa"})
    assert conv["text"] == "32 psi = 220.6322 kPa" and conv["manifest"]["side_effects"] is False
    sun = run_file(ROOT / "tools" / "sun_times.py", {"place": "Tromsø", "date": "2026-06-21"},
                   places={"tromsø": {"lat": 69.65, "lon": 18.96, "name": "Tromsø"}})
    assert "midnight sun" in sun["text"]


def test_plugin_cli(tmp_path):
    env_root = str(ROOT / "core")
    r = subprocess.run([sys.executable, "-m", "mimi", "plugin", "test", str(ROOT / "tools" / "unit_converter.py"),
                        "--args", json.dumps({"value": 212, "from_unit": "F", "to_unit": "C"})],
                       capture_output=True, text=True, cwd=env_root, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["text"] == "212 F = 100 C"
    r = subprocess.run([sys.executable, "-m", "mimi", "plugin", "check", str(ROOT / "tools")], capture_output=True, text=True,
                       cwd=env_root, timeout=60)
    assert r.returncode == 0 and "sun_times" in r.stdout and "side_effects=False" in r.stdout
