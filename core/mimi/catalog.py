"""Model catalog and profiles (config/models.json)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .paths import Paths

ROLES = ("main", "quick", "reader")


@dataclass
class ModelSpec:
    id: str
    raw: dict
    paths: Paths

    def __getitem__(self, k):
        return self.raw[k]

    def get(self, k, default=None):
        return self.raw.get(k, default)

    @property
    def name(self) -> str:
        return self.raw.get("name", self.id)

    @property
    def kind(self) -> str:
        return self.raw.get("kind", "chat")

    @property
    def file(self) -> Path:
        return self.paths.rel(self.raw["file"])

    @property
    def mmproj(self) -> Path | None:
        m = self.raw.get("mmproj")
        return self.paths.rel(m) if m else None

    @property
    def installed(self) -> bool:
        return self.file.exists() and self.file.stat().st_size > 1_000_000

    @property
    def vision(self) -> bool:
        return bool(self.raw.get("vision")) and bool(self.mmproj and self.mmproj.exists())

    @property
    def size_gb(self) -> float:
        try:
            total = self.file.stat().st_size + (self.mmproj.stat().st_size if self.mmproj and self.mmproj.exists() else 0)
            return round(total / 1e9, 1)
        except OSError:
            return 0.0

    def public(self) -> dict:
        r = {k: v for k, v in self.raw.items() if k not in ("file", "mmproj", "draft", "sampling", "template_kwargs", "think_kwargs")}
        r.update(id=self.id, installed=self.installed, vision=self.vision, size_gb=self.size_gb if self.installed else None)
        return r


class Catalog:
    def __init__(self, paths: Paths):
        self.paths = paths
        self.reload()

    def reload(self) -> None:
        data = json.loads((self.paths.config / "models.json").read_text("utf-8"))
        self.models = {k: ModelSpec(k, v, self.paths) for k, v in data["models"].items()}
        self.profiles: dict[str, dict] = data["profiles"]

    def get(self, model_id: str | None) -> ModelSpec | None:
        return self.models.get(model_id or "")

    def resolve(self, role: str, profile: str, override: str | None = None) -> ModelSpec | None:
        """Pick the model for a role: explicit override → profile preference list → any installed chat model."""
        if override:
            m = self.get(override)
            if m and m.installed:
                return m
        prof = self.profiles.get(profile) or self.profiles["standard"]
        for mid in prof.get(role, []):
            m = self.get(mid)
            if m and m.installed:
                return m
        # graceful fallback: walk the standard profile, then anything installed
        for mid in self.profiles["standard"].get(role, []) + self.profiles["standard"]["main"]:
            m = self.get(mid)
            if m and m.installed:
                return m
        for m in self.models.values():
            if m.kind == "chat" and m.installed:
                return m
        return None

    def embed_model(self, profile: str) -> ModelSpec | None:
        prof = self.profiles.get(profile) or self.profiles["standard"]
        m = self.get(prof.get("embed"))
        return m if m and m.installed else None
