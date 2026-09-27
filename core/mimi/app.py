"""MIMI Core application: service container, lifecycle and HTTP app assembly."""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response

from . import __version__, hardware, log
from .auth import SESSION_COOKIE, Auth, Ctx
from .catalog import Catalog
from .chat import ChatService
from .db import Database
from .events import EventBus
from .kiwix import KiwixClient, KiwixService
from .lens import LensService
from .llm import ModelManager
from .location import LocationService
from .memory import MemoryService
from .mydocs import DocsService
from .routing import RoutingService
from .pairing import PairingService
from .paths import Paths
from .scribe import ScribeService
from .settings import SettingsStore
from .share import ShareService
from .uploads import UploadService
from .voice import VoiceService
from . import system, tools

L = log.get("app")
MAIN_PORT = int(os.environ.get("MIMI_PORT", "7600"))


class Services:
    """Everything the API needs, created once per process."""

    def __init__(self, paths: Paths):
        self.paths = paths
        self.started_at = time.time()
        self.db = Database(paths.db_file)
        self.settings = SettingsStore(self.db)
        self.events = EventBus()
        self.auth = Auth(self.db)
        self.pairing = PairingService(self.auth, self.events)
        self.catalog = Catalog(paths)
        self.hw = hardware.detect(paths, use_cache=True, max_age=10**9) if (paths.data / "hardware.json").exists() else {
            "profile": "standard", "backend": "vulkan", "cores": os.cpu_count() or 4, "gpus": [], "battery": hardware.battery()}
        self.models = ModelManager(paths, self.catalog, self.settings, self.events, self.hw)
        self.kiwix_service = KiwixService(paths, self.settings, self.events)
        self.kiwix = KiwixClient(self.kiwix_service, self.settings)
        self.memory = MemoryService(self.db, self.models, self.events, self.settings)
        self.docs = DocsService(self.db, self.models, self.events, paths)
        self.location = LocationService(paths, self.settings, self.events, self.db)
        self.routing = RoutingService(paths)
        self.voice = VoiceService(paths, cores=int(self.hw.get("cores") or 4))
        self.lens = LensService()
        self.uploads = UploadService(paths)
        self.chats = ChatService(self)
        self.scribe = ScribeService(self)
        self.share = ShareService(self)
        self.app: FastAPI | None = None
        self._tasks: list[asyncio.Task] = []
        self._stop_server = None  # set by the launcher (mimi.__main__) so /api/system/shutdown can exit cleanly

    async def startup(self, app: FastAPI) -> None:
        self.app = app
        loop = asyncio.get_running_loop()
        self.events.bind(loop)
        L.info("MIMI Core %s starting at %s", __version__, self.paths.root)
        # Fresh hardware probe in the background (the cached one is used meanwhile).
        self._tasks.append(asyncio.create_task(self._refresh_hardware()))
        await self.kiwix_service.start()
        self.kiwix_service.watch(self.kiwix)
        self.location.start()
        await asyncio.to_thread(tools.load_plugins, self.paths.root / "tools")
        self.docs.start()
        self.scribe.start()
        self.models.start_janitor()
        self.chats.purge()
        if self.settings.device("models").preload and not os.environ.get("MIMI_NO_PRELOAD"):
            self._tasks.append(asyncio.create_task(self._preload()))
        if self.settings.device("sharing").enabled:
            self._tasks.append(asyncio.create_task(self.share.start(app)))
        self._tasks.append(asyncio.create_task(self._housekeeping()))

    async def _preload(self) -> None:
        await self.models.preload()
        await self.chats.warm()

    async def _refresh_hardware(self) -> None:
        try:
            info = await asyncio.to_thread(hardware.detect, self.paths, False)
            self.hw.update(info)
            self.events.publish("system", {"hardware": self.hw}, sticky=True)
        except Exception as e:
            L.warning("hardware detection failed: %s", e)

    async def _housekeeping(self) -> None:
        last_purge = time.time()
        while True:
            await asyncio.sleep(30)
            try:
                self.hw["battery"] = hardware.battery()
                import psutil

                vm = psutil.virtual_memory()
                self.events.publish("system", {"battery": self.hw["battery"], "ram_used_pct": vm.percent,
                                               "battery_saver": self.models.on_battery_saver()}, sticky=True)
                if time.time() - last_purge > 3600:
                    self.chats.purge()
                    last_purge = time.time()
            except Exception as e:
                L.debug("housekeeping: %s", e)

    async def shutdown(self) -> None:
        for t in self._tasks:
            t.cancel()
        await self.share.stop()
        self.location.stop()
        await self.kiwix_service.stop()
        await self.models.shutdown()
        self.db.close()
        L.info("MIMI Core stopped")

    async def shutdown_hook(self) -> None:
        if self._stop_server:
            self._stop_server()
        else:  # pragma: no cover - running under an external ASGI server
            os._exit(0)

    def health(self) -> dict:
        return {
            "version": __version__,
            "uptime": int(time.time() - self.started_at),
            "model": self.models.status(),
            "library": {"running": self.kiwix_service.alive(), "files": len(self.kiwix_service.files)},
            "voice": self.voice.status(),
            "location": {"geodata": bool(self.location.geo), "gps": bool(self.location.gps_port)},
            "share": {"running": self.share.running},
            "maps": {"tiles": (self.paths.maps / "tiles.pmtiles").exists(), "routing": self.routing.available()},
        }


# --------------------------------------------------------------------------- request context
def is_local(request: Request) -> bool:
    server = request.scope.get("server") or ("", 0)
    client = request.client.host if request.client else ""
    if client == "testclient":  # Starlette's TestClient: local only when talking to the default test host
        return server[0] == "testserver"
    return server[1] == MAIN_PORT and client in ("127.0.0.1", "::1", "localhost")


def ctx_or_none(request: Request) -> Ctx | None:
    svc: Services = request.app.state.svc
    token = request.cookies.get(SESSION_COOKIE) or request.headers.get("x-mimi-session")
    local = is_local(request)
    user = svc.auth.resolve(token) if token else None
    if user:
        return Ctx(user, token, local)
    g = svc.settings.device("general")
    if local and g.local_auto_login and not g.require_pin:
        owner = svc.auth.owner()
        if owner:
            return Ctx(owner, None, True)
    return None


def get_ctx(request: Request) -> Ctx:
    ctx = ctx_or_none(request)
    if ctx is None:
        raise HTTPException(401, "Sign in to MIMI to continue.")
    return ctx


def owner_ctx(request: Request) -> Ctx:
    ctx = get_ctx(request)
    if not ctx.is_owner:
        raise HTTPException(403, "Only the device owner can do that.")
    return ctx


def member_ctx(request: Request) -> Ctx:
    ctx = get_ctx(request)
    if ctx.is_guest:
        raise HTTPException(403, "Guests can't use this feature.")
    return ctx


# --------------------------------------------------------------------------- app factory
def create_app(paths: Paths | None = None) -> FastAPI:
    paths = paths or Paths()
    log.setup_logging(paths.logs)
    svc = Services(paths)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await svc.startup(app)
        try:
            yield
        finally:
            await svc.shutdown()

    app = FastAPI(title="MIMI Core", version=__version__, lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.state.svc = svc

    from .api import router as api_router, public_router

    app.include_router(api_router)
    app.include_router(public_router)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp: Response = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    ui = paths.ui_build

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str, request: Request):
        if full_path.startswith(("api/", "kiwix/", "maps/")):
            raise HTTPException(404)
        f = (ui / full_path).resolve() if full_path else None
        if f and f.is_file() and str(f).startswith(str(ui.resolve())):
            headers = {"Cache-Control": "public, max-age=31536000, immutable"} if "/_app/immutable/" in f.as_posix() else {"Cache-Control": "no-cache"}
            return FileResponse(f, headers=headers)
        index = ui / "index.html"
        if index.exists():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return HTMLResponse(PLACEHOLDER)

    return app


PLACEHOLDER = """<!doctype html><html><head><meta charset=utf-8><title>MIMI</title>
<style>body{margin:0;height:100vh;display:grid;place-items:center;background:#060a12;color:#dfe8f5;font:16px/1.5 system-ui}
.o{width:120px;height:120px;border-radius:50%;background:radial-gradient(circle at 40% 35%,#b8fff2,#39c3b0 45%,#0b3b4a 75%);box-shadow:0 0 80px #2ad3bf66;margin:0 auto 24px}</style>
</head><body><div><div class=o></div><h1 style="font-weight:300;letter-spacing:.3em;text-align:center">MIMI</h1>
<p style="opacity:.7;text-align:center">Core is running. The app UI hasn't been built yet — run <code>scripts/build-ui.ps1</code>.</p></div></body></html>"""
