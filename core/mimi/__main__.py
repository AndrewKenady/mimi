"""Mimi Core command line.

    python -m mimi serve            run the backend (the Mimi app starts this for you)
    python -m mimi doctor           print a diagnostic report
    python -m mimi mcp              serve Mimi's offline tools to MCP clients over stdio (docs/MCP.md)
    python -m mimi plugin ...       check or try community tools (tools/README.md)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys


def serve(args: argparse.Namespace) -> None:
    import uvicorn

    from .app import MAIN_PORT, create_app

    app = create_app()
    config = uvicorn.Config(app, host=args.host, port=args.port or MAIN_PORT, log_config=None, access_log=False,
                            ws_ping_interval=20, timeout_graceful_shutdown=5)
    server = uvicorn.Server(config)

    def stop():
        server.should_exit = True

    app.state.svc._stop_server = stop
    try:
        server.run()
    except KeyboardInterrupt:
        pass


def doctor(args: argparse.Namespace) -> None:
    from . import hardware
    from .catalog import Catalog
    from .paths import Paths

    p = Paths()
    hw = hardware.detect(p, use_cache=False)
    cat = Catalog(p)
    report = {
        "root": str(p.root),
        "hardware": hw,
        "models": {m.id: {"installed": m.installed, "vision": m.vision} for m in cat.models.values()},
        "zim_files": sorted(f.name for f in p.zim.glob("*.zim")),
        "maps": sorted(f.name for f in p.maps.glob("*")) if p.maps.exists() else [],
        "voice": {"whisper": [d.name for d in (p.models / "whisper").glob("*")] if (p.models / "whisper").exists() else [],
                  "tts": (p.models / "tts" / "kokoro-v1.0.onnx").exists()},
    }
    print(json.dumps(report, indent=2))


def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    ap = argparse.ArgumentParser(prog="mimi", description="Mimi — Machine Intelligence, Minus the Internet")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="run Mimi Core")
    s.add_argument("--host", default=os.environ.get("MIMI_HOST", "127.0.0.1"))
    s.add_argument("--port", type=int, default=None)
    sub.add_parser("doctor", help="diagnostics")
    # mcp / plugin parse their own options (see mcp_server.main and plugins.cli)
    sub.add_parser("mcp", help="MCP server over stdio for Claude Desktop and other clients", add_help=False)
    sub.add_parser("plugin", help="check or test community tools", add_help=False)
    if len(sys.argv) > 1 and sys.argv[1] in ("mcp", "plugin"):
        if sys.argv[1] == "mcp":
            from .mcp_server import main as mcp_main

            sys.exit(mcp_main(sys.argv[2:]))
        from .plugins import cli

        sys.exit(cli(sys.argv[2:]))
    args = ap.parse_args()
    if args.cmd == "doctor":
        doctor(args)
    else:
        if not getattr(args, "host", None):
            args.host, args.port = "127.0.0.1", None
        serve(args)


if __name__ == "__main__":
    main()
