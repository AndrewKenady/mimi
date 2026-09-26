"""Model manager: runs llama.cpp servers, swaps models, streams chat and embeddings.

Design
------
* One chat model is resident at a time (memory is the binding constraint on a
  16 GB handheld). Switching roles (main → reader) stops one llama-server and
  starts another; the UI is told what is happening through events.
* Embeddings run on a separate, CPU-only llama-server (the CPU build, so it
  never competes for GPU memory). It starts on demand and idles out.
* Generation is serialized with an asyncio lock; extra requests wait in line
  (guests on the shared network see a "queued" state).
* We let llama.cpp's `--fit` decide how many layers fit on the GPU, so a model
  still loads (partially on CPU) when other apps are holding memory.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, AsyncIterator

import httpx
import numpy as np

from . import log
from .catalog import Catalog, ModelSpec
from .events import EventBus
from .paths import Paths
from .procs import ManagedProcess
from .settings import SettingsStore

L = log.get("llm")

CHAT_PORT = int(os.environ.get("MIMI_CHAT_PORT", "7610"))
EMBED_PORT = int(os.environ.get("MIMI_EMBED_PORT", "7611"))
EMBED_IDLE_SECONDS = 15 * 60


class ModelError(RuntimeError):
    pass


class ModelManager:
    def __init__(self, paths: Paths, catalog: Catalog, settings: SettingsStore, events: EventBus, hw: dict):
        self.paths = paths
        self.catalog = catalog
        self.settings = settings
        self.events = events
        self.hw = hw
        self.chat_proc: ManagedProcess | None = None
        self.chat_model: ModelSpec | None = None
        self.chat_ctx: int = 0
        self.embed_proc: ManagedProcess | None = None
        self.embed_model: ModelSpec | None = None
        self._embed_last_use = 0.0
        self._switch_lock = asyncio.Lock()
        self._embed_lock = asyncio.Lock()
        self.gen_lock = asyncio.Lock()
        self.waiting = 0
        self.state: dict[str, Any] = {"status": "idle", "model": None, "model_name": None, "error": None, "since": time.time()}
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(connect=5, read=600, write=60, pool=10))
        self._janitor: asyncio.Task | None = None

    # ------------------------------------------------------------------ config
    @property
    def profile(self) -> str:
        p = self.settings.device("models").profile
        return self.hw.get("profile", "standard") if p == "auto" else p

    def on_battery_saver(self) -> bool:
        power = self.settings.device("power")
        b = self.hw.get("battery")
        return bool(power.battery_saver and b and not b.get("plugged") and b.get("percent", 100) <= power.battery_saver_threshold)

    def model_for(self, role: str) -> ModelSpec | None:
        ms = self.settings.device("models")
        if role == "main" and self.on_battery_saver():
            role = "quick"
        override = getattr(ms, role, None) if role in ("main", "quick", "reader") else None
        return self.catalog.resolve(role, self.profile, override)

    def _build_dir(self, cpu_only: bool = False) -> str:
        order = ["llama-cpu"] if cpu_only else {
            "cuda": ["llama-cuda", "llama-vulkan", "llama-cpu"],
            "vulkan": ["llama-vulkan", "llama-cpu"],
        }.get(self.hw.get("backend", "cpu"), ["llama-cpu"])
        for b in order + ["llama-vulkan", "llama-cpu"]:
            if self.paths.exe(b, "llama-server").exists():
                return b
        raise ModelError("No llama.cpp build found in bin/. Run scripts/setup.ps1.")

    def _threads(self) -> int:
        return max(2, int(self.hw.get("cores") or 4))

    # ------------------------------------------------------------------ status
    def _set_state(self, status: str, model: ModelSpec | None = None, error: str | None = None) -> None:
        self.state = {
            "status": status,
            "model": model.id if model else (self.chat_model.id if self.chat_model else None),
            "model_name": model.name if model else (self.chat_model.name if self.chat_model else None),
            "error": error,
            "since": time.time(),
            "ctx": self.chat_ctx,
            "profile": self.profile,
            "waiting": self.waiting,
        }
        self.events.publish("model", self.state, sticky=True)

    def status(self) -> dict:
        s = dict(self.state)
        s.update(
            waiting=self.waiting,
            profile=self.profile,
            battery_saver=self.on_battery_saver(),
            roles={r: (m.id if (m := self.model_for(r)) else None) for r in ("main", "quick", "reader")},
            embeddings=bool(self.embed_proc and self.embed_proc.alive()),
        )
        return s

    # ------------------------------------------------------------------ lifecycle
    def _chat_args(self, spec: ModelSpec, ctx: int) -> list[str]:
        build = self._build_dir()
        args = [
            str(self.paths.exe(build, "llama-server")),
            "-m", str(spec.file),
            "--host", "127.0.0.1",
            "--port", str(CHAT_PORT),
            "-c", str(ctx),
            "-np", "1",
            "-fa", "on",
            "-ctk", "q8_0",
            "-ctv", "f16",
            "-t", str(self._threads()),
            "--jinja",
            "--no-webui",
            "--cache-reuse", "256",
            "--fit", "on",
            "--fit-target", "768",
            "--reasoning-format", "deepseek",
        ]
        if spec.vision and spec.mmproj:
            args += ["--mmproj", str(spec.mmproj)]
        if build == "llama-cpu":
            args += ["-ngl", "0"]
        return args

    async def ensure(self, spec: ModelSpec) -> str:
        """Make sure `spec` is the resident chat model; returns its base URL."""
        async with self._switch_lock:
            if self.chat_model and self.chat_model.id == spec.id and self.chat_proc and self.chat_proc.alive():
                return f"http://127.0.0.1:{CHAT_PORT}"
            await self._stop_chat()
            want_ctx = int(min(self.settings.device("models").context, spec.get("context", 8192)))
            self._set_state("loading", spec)
            t0 = time.time()
            for attempt, ctx in enumerate([want_ctx, max(spec.get("min_context", 4096), want_ctx // 2)]):
                self.chat_ctx = ctx
                proc = ManagedProcess(f"llama[{spec.id}]", self._chat_args(spec, ctx), cwd=self.paths.root, log_path=self.paths.logs / "llama-chat.log")
                proc.start()
                ok = await self._wait_ready(proc, CHAT_PORT, timeout=240)
                if ok:
                    self.chat_proc, self.chat_model = proc, spec
                    try:
                        props = (await self.client.get(f"http://127.0.0.1:{CHAT_PORT}/props", timeout=10)).json()
                        self.chat_ctx = int(props.get("default_generation_settings", {}).get("n_ctx") or ctx)
                    except Exception:
                        pass
                    L.info("%s ready in %.1fs (ctx %s)", spec.id, time.time() - t0, self.chat_ctx)
                    self._set_state("ready", spec)
                    return f"http://127.0.0.1:{CHAT_PORT}"
                tail = proc.tail(12)
                proc.stop()
                L.warning("%s failed to start with ctx %s (attempt %s):\n%s", spec.id, ctx, attempt + 1, tail)
            self.chat_model = None
            self._set_state("error", spec, error=f"{spec.name} could not start. Close other apps to free memory, or pick a smaller model.")
            raise ModelError(f"{spec.name} failed to load")

    async def _wait_ready(self, proc: ManagedProcess, port: int, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not proc.alive():
                return False
            try:
                r = await self.client.get(f"http://127.0.0.1:{port}/health", timeout=2)
                if r.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.4)
        return False

    async def _stop_chat(self) -> None:
        if self.chat_proc:
            proc, self.chat_proc = self.chat_proc, None
            await asyncio.to_thread(proc.stop)
        self.chat_model = None

    async def unload(self) -> None:
        async with self._switch_lock:
            await self._stop_chat()
            self._set_state("idle")

    async def preload(self) -> None:
        spec = self.model_for("main")
        if spec:
            try:
                await self.ensure(spec)
            except ModelError as e:
                L.warning("preload failed: %s", e)

    def start_janitor(self) -> None:
        async def loop():
            while True:
                await asyncio.sleep(60)
                if self.embed_proc and time.time() - self._embed_last_use > EMBED_IDLE_SECONDS and not self._embed_lock.locked():
                    L.info("stopping idle embedding server")
                    await asyncio.to_thread(self.embed_proc.stop)
                    self.embed_proc = None
                if self.chat_proc and not self.chat_proc.alive() and self.state.get("status") == "ready":
                    L.warning("chat model process exited unexpectedly")
                    self.chat_model = None
                    self._set_state("error", error="The model stopped unexpectedly. It will restart on your next message.")

        self._janitor = asyncio.create_task(loop())

    async def shutdown(self) -> None:
        if self._janitor:
            self._janitor.cancel()
        await self._stop_chat()
        if self.embed_proc:
            await asyncio.to_thread(self.embed_proc.stop)
        await self.client.aclose()

    # ------------------------------------------------------------------ chat
    def _body(self, spec: ModelSpec, messages: list[dict], *, tools: list[dict] | None, max_tokens: int,
              temperature: float | None, think: bool, stream: bool, json_schema: dict | None = None,
              tool_choice: str = "auto") -> dict:
        s = dict(spec.get("sampling", {}))
        t_override = self.settings.device("models").temperature
        if temperature is not None:
            s["temperature"] = temperature
        elif t_override is not None:
            s["temperature"] = t_override
        body: dict[str, Any] = {
            "messages": messages,
            "stream": stream,
            "max_tokens": max_tokens,
            "cache_prompt": True,
            "chat_template_kwargs": dict(spec.get("think_kwargs" if think else "template_kwargs", {}) or {}),
            **s,
        }
        if stream:
            body["stream_options"] = {"include_usage": True}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice
        if json_schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "result", "schema": json_schema, "strict": True}}
        return body

    async def chat_stream(self, spec: ModelSpec, messages: list[dict], *, tools: list[dict] | None = None,
                          max_tokens: int = 1024, temperature: float | None = None, think: bool = False,
                          cancel: asyncio.Event | None = None, tool_choice: str = "auto") -> AsyncIterator[dict]:
        """Yields {'type': 'content'|'reasoning'|'tool_calls'|'done', ...}. Caller must hold gen_lock."""
        base = await self.ensure(spec)
        body = self._body(spec, messages, tools=tools, max_tokens=max_tokens, temperature=temperature, think=think, stream=True, tool_choice=tool_choice)
        calls: dict[int, dict] = {}
        finish = None
        timings: dict = {}
        usage: dict = {}
        async with self.client.stream("POST", f"{base}/v1/chat/completions", json=body) as resp:
            if resp.status_code != 200:
                text = (await resp.aread()).decode("utf-8", "replace")
                raise ModelError(f"model error {resp.status_code}: {text[:400]}")
            async for line in resp.aiter_lines():
                if cancel is not None and cancel.is_set():
                    break
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except ValueError:
                    continue
                if chunk.get("timings"):
                    timings = chunk["timings"]
                if chunk.get("usage"):
                    usage = chunk["usage"]
                for ch in chunk.get("choices") or []:
                    d = ch.get("delta") or {}
                    if d.get("reasoning_content"):
                        yield {"type": "reasoning", "text": d["reasoning_content"]}
                    if d.get("content"):
                        yield {"type": "content", "text": d["content"]}
                    for tc in d.get("tool_calls") or []:
                        i = tc.get("index", 0)
                        slot = calls.setdefault(i, {"id": None, "name": "", "arguments": ""})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] += fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
                    if ch.get("finish_reason"):
                        finish = ch["finish_reason"]
        if calls:
            out = []
            for i in sorted(calls):
                c = calls[i]
                out.append({"id": c["id"] or f"call_{i}_{int(time.time()*1000)}", "name": c["name"], "arguments": c["arguments"]})
            yield {"type": "tool_calls", "calls": out}
        yield {"type": "done", "finish_reason": finish, "timings": timings, "usage": usage, "cancelled": bool(cancel and cancel.is_set())}

    async def chat_once(self, spec: ModelSpec, messages: list[dict], *, max_tokens: int = 512, temperature: float | None = None,
                        json_schema: dict | None = None) -> str:
        base = await self.ensure(spec)
        body = self._body(spec, messages, tools=None, max_tokens=max_tokens, temperature=temperature, think=False, stream=False, json_schema=json_schema)
        r = await self.client.post(f"{base}/v1/chat/completions", json=body)
        if r.status_code != 200:
            raise ModelError(f"model error {r.status_code}: {r.text[:300]}")
        msg = r.json()["choices"][0]["message"]
        return msg.get("content") or ""

    # ------------------------------------------------------------------ embeddings
    async def _ensure_embed(self) -> str:
        async with self._embed_lock:
            if self.embed_proc and self.embed_proc.alive():
                return f"http://127.0.0.1:{EMBED_PORT}"
            spec = self.catalog.embed_model(self.profile)
            if not spec:
                raise ModelError("No embedding model installed")
            build = self._build_dir(cpu_only=True)
            args = [
                str(self.paths.exe(build, "llama-server")),
                "-m", str(spec.file),
                "--host", "127.0.0.1", "--port", str(EMBED_PORT),
                "--embedding", "--pooling", spec.get("pooling", "cls"),
                "-c", "8192", "-b", "8192", "-ub", "8192", "-np", "1",
                "-t", str(max(2, self._threads() // 2)),
                "--no-webui", "-ngl", "0",
            ]
            proc = ManagedProcess("llama[embed]", args, cwd=self.paths.root, log_path=self.paths.logs / "llama-embed.log")
            proc.start()
            if not await self._wait_ready(proc, EMBED_PORT, timeout=90):
                tail = proc.tail(10)
                proc.stop()
                raise ModelError(f"embedding server failed to start: {tail[-300:]}")
            self.embed_proc, self.embed_model = proc, spec
            return f"http://127.0.0.1:{EMBED_PORT}"

    async def embed(self, texts: list[str], batch: int = 16) -> np.ndarray:
        """Return L2-normalised float32 embeddings, shape (len(texts), dims)."""
        if not texts:
            return np.zeros((0, 1024), dtype=np.float32)
        base = await self._ensure_embed()
        self._embed_last_use = time.time()
        vecs: list[list[float]] = []
        for i in range(0, len(texts), batch):
            part = [t[:6000] if t else " " for t in texts[i : i + batch]]
            r = await self.client.post(f"{base}/v1/embeddings", json={"input": part, "model": "embed"}, timeout=120)
            if r.status_code != 200:
                raise ModelError(f"embedding error {r.status_code}: {r.text[:200]}")
            data = sorted(r.json()["data"], key=lambda d: d["index"])
            vecs.extend(d["embedding"] for d in data)
        self._embed_last_use = time.time()
        arr = np.asarray(vecs, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms


def to_blob(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def from_blob(b: bytes | None) -> np.ndarray | None:
    if not b:
        return None
    return np.frombuffer(b, dtype=np.float32)
