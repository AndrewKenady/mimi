"""Typed settings with device-level and per-user scopes.

Device settings (general, models, sharing, power, controls, location,
knowledge) belong to the device owner. Personal settings (appearance,
assistant, voice, privacy) are stored per user. Everything is validated with
Pydantic on write, persisted as JSON in SQLite and pushed live to every client
through the event bus.
"""

from __future__ import annotations

import secrets
import string
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import db as dbm


def _wifi_password() -> str:
    alphabet = string.ascii_lowercase + string.digits
    alphabet = "".join(c for c in alphabet if c not in "0o1l")
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))


class Section(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=True)


# --- device sections ---------------------------------------------------------
class General(Section):
    launch_at_startup: bool = False
    open_fullscreen: bool = True
    kiosk: bool = False
    keep_running_on_close: bool = False
    local_auto_login: bool = True
    require_pin: bool = False
    units: Literal["imperial", "metric"] = "imperial"
    time_format: Literal["12h", "24h"] = "12h"
    language: str = "en"


class Models(Section):
    profile: Literal["auto", "lite", "standard", "plus", "max"] = "auto"
    main: str | None = None
    quick: str | None = None
    reader: str | None = None
    context: int = Field(8192, ge=2048, le=131072)
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    preload: bool = True
    think_harder: bool = False


class Sharing(Section):
    enabled: bool = False
    ssid: str = Field("MIMI", min_length=1, max_length=32)
    wifi_password: str = Field(default_factory=_wifi_password, min_length=8, max_length=63)
    network_mode: Literal["router", "hotspot"] = "router"
    https_port: int = Field(443, ge=1, le=65535)
    guest_access: bool = True
    guest_features: list[str] = Field(default_factory=lambda: ["chat", "library", "map"])
    max_guests: int = Field(8, ge=1, le=64)
    guest_messages_per_hour: int = Field(30, ge=1, le=1000)


class Power(Section):
    battery_saver: bool = True
    battery_saver_threshold: int = Field(25, ge=5, le=80)
    dim_well_on_battery: bool = True


class Controls(Section):
    gamepad: bool = True
    haptics: bool = True
    mapping: dict[str, str] = Field(
        default_factory=lambda: {
            "A": "select",
            "B": "back",
            "X": "voice",
            "Y": "lens",
            "LB": "prev_surface",
            "RB": "next_surface",
            "LT": "push_to_talk",
            "Start": "quick_menu",
            "Back": "command_palette",
        }
    )


class Location(Section):
    source: Literal["auto", "gps", "manual", "off"] = "auto"
    manual: dict[str, Any] | None = None  # {lat, lon, label}
    gps_port: str = "auto"
    history: bool = False
    history_days: int = Field(30, ge=1, le=3650)


class Knowledge(Section):
    disabled_books: list[str] = Field(default_factory=list)
    extra_zim_dirs: list[str] = Field(default_factory=list)
    articles_per_search: int = Field(3, ge=1, le=6)
    snippet_chars: int = Field(900, ge=400, le=4000)


# --- personal sections -------------------------------------------------------
class Appearance(Section):
    theme: Literal["dark", "light", "oled", "auto"] = "dark"
    accent: str = Field("#6EE7D2", pattern=r"^#[0-9a-fA-F]{6}$")
    well_style: Literal["tide", "aurora", "ember", "mono"] = "tide"
    font_scale: float = Field(1.0, ge=0.8, le=1.5)
    density: Literal["comfortable", "compact"] = "comfortable"
    reading_font: Literal["serif", "sans"] = "serif"
    reduced_motion: bool = False
    high_contrast: bool = False
    home_widgets: list[str] = Field(default_factory=lambda: ["nearby", "notes", "onthisday", "continue"])


class Assistant(Section):
    verbosity: int = Field(40, ge=0, le=100)
    formality: int = Field(35, ge=0, le=100)
    wit: bool = True
    custom_instructions: str = Field("", max_length=2000)
    about_me: str = Field("", max_length=1000)
    citations: Literal["strict", "balanced"] = "strict"
    default_mode: str = "everyday"
    show_tool_activity: bool = True


class Voice(Section):
    voice: str = "af_heart"
    speed: float = Field(1.0, ge=0.6, le=1.6)
    read_aloud: bool = False
    stt_model: Literal["small", "turbo"] = "small"
    hands_free: bool = False
    barge_in: bool = True


class Privacy(Section):
    memory: Literal["ask", "auto", "off"] = "ask"
    memory_paused: bool = False
    history: bool = True
    history_days: int = Field(0, ge=0, le=3650)


DEVICE_SECTIONS: dict[str, type[Section]] = {
    "general": General,
    "models": Models,
    "sharing": Sharing,
    "power": Power,
    "controls": Controls,
    "location": Location,
    "knowledge": Knowledge,
}
USER_SECTIONS: dict[str, type[Section]] = {
    "appearance": Appearance,
    "assistant": Assistant,
    "voice": Voice,
    "privacy": Privacy,
}
GUEST_DEFAULTS: dict[str, dict] = {"privacy": {"memory": "off", "history": False}}


class SettingsError(ValueError):
    pass


def _deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k not in ("mapping", "manual"):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class SettingsStore:
    def __init__(self, db: dbm.Database):
        self.db = db
        self._cache: dict[str, dict] = {}

    # --- raw storage ------------------------------------------------------
    def _load(self, scope: str) -> dict:
        if scope not in self._cache:
            row = self.db.one("SELECT data FROM settings WHERE scope=?", (scope,))
            self._cache[scope] = dbm.loads(row["data"], {}) if row else {}
        return self._cache[scope]

    def _save(self, scope: str, data: dict) -> None:
        self._cache[scope] = data
        self.db.execute(
            "INSERT INTO settings(scope, data, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(scope) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
            (scope, dbm.dumps(data), dbm.now()),
        )

    # --- typed access -----------------------------------------------------
    def device(self, section: str) -> Section:
        model = DEVICE_SECTIONS[section]
        stored = self._load("device").get(section, {})
        try:
            obj = model.model_validate(stored)
        except ValidationError:
            obj = model()
        if section == "sharing" and "wifi_password" not in stored:
            # persist the generated password so it stays stable
            data = self._load("device")
            data = _deep_merge(data, {"sharing": obj.model_dump()})
            self._save("device", data)
        return obj

    def user(self, user_id: str, section: str, role: str = "user") -> Section:
        model = USER_SECTIONS[section]
        stored = self._load(f"user:{user_id}").get(section, {})
        base = GUEST_DEFAULTS.get(section, {}) if role == "guest" else {}
        try:
            return model.model_validate(_deep_merge(base, stored))
        except ValidationError:
            return model.model_validate(base)

    def all_for(self, user_id: str, role: str) -> dict:
        return {
            "device": {k: self.device(k).model_dump() for k in DEVICE_SECTIONS},
            "user": {k: self.user(user_id, k, role).model_dump() for k in USER_SECTIONS},
        }

    # --- mutation ---------------------------------------------------------
    def update(self, scope: str, section: str, patch: dict, user_id: str | None = None, role: str = "user") -> dict:
        if scope == "device":
            if section not in DEVICE_SECTIONS:
                raise SettingsError(f"Unknown device section '{section}'")
            key, model = "device", DEVICE_SECTIONS[section]
            current = self.device(section).model_dump()
        elif scope == "user":
            if section not in USER_SECTIONS or not user_id:
                raise SettingsError(f"Unknown personal section '{section}'")
            key, model = f"user:{user_id}", USER_SECTIONS[section]
            current = self.user(user_id, section, role).model_dump()
        else:
            raise SettingsError("scope must be 'device' or 'user'")
        merged = _deep_merge(current, patch or {})
        try:
            validated = model.model_validate(merged).model_dump()
        except ValidationError as e:
            msgs = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors())
            raise SettingsError(msgs) from e
        data = dict(self._load(key))
        data[section] = validated
        self._save(key, data)
        return validated

    def reset(self, scope: str, section: str, user_id: str | None = None) -> dict:
        key = "device" if scope == "device" else f"user:{user_id}"
        data = dict(self._load(key))
        data.pop(section, None)
        self._save(key, data)
        return (self.device(section) if scope == "device" else self.user(user_id or "", section)).model_dump()

    def export(self, user_id: str, role: str) -> dict:
        return self.all_for(user_id, role)

    def import_(self, payload: dict, user_id: str, role: str, include_device: bool) -> None:
        for sec, val in (payload.get("user") or {}).items():
            if sec in USER_SECTIONS and isinstance(val, dict):
                self.update("user", sec, val, user_id=user_id, role=role)
        if include_device:
            for sec, val in (payload.get("device") or {}).items():
                if sec in DEVICE_SECTIONS and isinstance(val, dict):
                    self.update("device", sec, val)
