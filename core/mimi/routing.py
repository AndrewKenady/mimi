"""Offline driving directions with Valhalla (routing tiles built from OpenStreetMap).

Tiles live in maps/routing/ (full region, built by scripts/build_routing.py) or
maps/routing-test/ (a small test region). The Valhalla config stored beside the
tiles is re-pointed at the actual folder on load, so the tree stays portable.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

from . import log
from .paths import Paths

L = log.get("routing")
COSTING = {"auto": "auto", "drive": "auto", "car": "auto", "walk": "pedestrian", "pedestrian": "pedestrian", "bike": "bicycle", "bicycle": "bicycle"}


def decode_polyline6(s: str) -> list[list[float]]:
    """Decode a Valhalla polyline (precision 6) into [[lon, lat], ...]."""
    coords, index, lat, lon = [], 0, 0, 0
    while index < len(s):
        for which in (0, 1):
            shift = result = 0
            while True:
                b = ord(s[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if which == 0:
                lat += delta
            else:
                lon += delta
        coords.append([lon / 1e6, lat / 1e6])
    return coords


def fmt_duration(seconds: float) -> str:
    m = int(round(seconds / 60))
    if m < 60:
        return f"{max(m, 1)} min"
    return f"{m // 60} h {m % 60:02d} min"


class RoutingService:
    def __init__(self, paths: Paths):
        self.paths = paths
        self._actor = None
        self._dir: Path | None = None
        self._lock = threading.Lock()

    def tile_dir(self) -> Path | None:
        for name in ("routing", "routing-test"):
            d = self.paths.maps / name
            if (d / "config.json").exists() and (d / "tiles").is_dir() and any((d / "tiles").iterdir()):
                return d
        return None

    def available(self) -> bool:
        return self.tile_dir() is not None

    def status(self) -> dict:
        d = self.tile_dir()
        meta = {}
        if d and (d / "meta.json").exists():
            try:
                meta = json.loads((d / "meta.json").read_text("utf-8"))
            except ValueError:
                pass
        return {"available": d is not None, "region": meta.get("region") or (d.name if d else None), "built": meta.get("built")}

    def _get_actor(self):
        d = self.tile_dir()
        if d is None:
            raise RuntimeError("Offline routing data isn't installed yet.")
        if self._actor is not None and self._dir == d:
            return self._actor
        libs = Path(sys.prefix) / "Lib" / "site-packages" / "pyvalhalla.libs"
        if libs.is_dir() and hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(libs))
        import valhalla

        cfg = json.loads((d / "config.json").read_text("utf-8"))
        cfg["mjolnir"]["tile_dir"] = str(d / "tiles")
        extract = d / "tiles.tar"
        cfg["mjolnir"]["tile_extract"] = str(extract) if extract.exists() else ""
        cfg["mjolnir"]["traffic_extract"] = ""
        cfg["mjolnir"].setdefault("logging", {})["type"] = ""
        t0 = time.time()
        self._actor = valhalla.Actor(cfg)
        self._dir = d
        L.info("routing ready from %s in %.2fs", d.name, time.time() - t0)
        return self._actor

    def route(self, origin: tuple[float, float], dest: tuple[float, float], mode: str = "auto", units: str = "miles") -> dict:
        costing = COSTING.get(mode, "auto")
        q = {
            "locations": [{"lat": origin[0], "lon": origin[1]}, {"lat": dest[0], "lon": dest[1]}],
            "costing": costing,
            "units": units,
            "directions_options": {"units": units, "language": "en-US"},
        }
        with self._lock:
            actor = self._get_actor()
            t0 = time.time()
            try:
                raw = actor.route(json.dumps(q))
            except Exception as e:  # valhalla raises on "no route"/out of coverage
                msg = str(e)
                if "No suitable edges" in msg or "442" in msg or "171" in msg:
                    raise ValueError("That place is outside the offline road map, or no road reaches it.") from e
                if "No path could be found" in msg:
                    raise ValueError("No road route connects those two places.") from e
                raise ValueError(f"Couldn't plan that route ({msg[:120]}).") from e
        data = json.loads(raw) if isinstance(raw, str) else raw
        trip = data["trip"]
        leg = trip["legs"][0]
        shape = decode_polyline6(leg["shape"])
        maneuvers = []
        for m in leg.get("maneuvers", []):
            i = m.get("begin_shape_index", 0)
            maneuvers.append({
                "instruction": m.get("instruction", ""),
                "verbal": m.get("verbal_pre_transition_instruction") or m.get("instruction", ""),
                "distance": round(m.get("length", 0.0), 2),
                "time": round(m.get("time", 0.0)),
                "type": m.get("type"),
                "streets": m.get("street_names") or [],
                "at": shape[i] if i < len(shape) else None,
            })
        s = trip["summary"]
        lons = [c[0] for c in shape] or [origin[1], dest[1]]
        lats = [c[1] for c in shape] or [origin[0], dest[0]]
        # Main roads: the longest named stretches, in order.
        named = [m for m in maneuvers if m["streets"] and m["distance"] > 0]
        top = sorted(named, key=lambda m: -m["distance"])[:4]
        via: list[str] = []
        for m in sorted(top, key=lambda m: maneuvers.index(m)):
            if m["streets"][0] not in via:
                via.append(m["streets"][0])
        via = via[:3]
        return {
            "mode": costing,
            "units": units,
            "distance": round(s["length"], 1),
            "duration_s": round(s["time"]),
            "duration": fmt_duration(s["time"]),
            "via": via,
            "has_toll": bool(s.get("has_toll")),
            "has_highway": bool(s.get("has_highway")),
            "has_ferry": bool(s.get("has_ferry")),
            "geometry": shape,
            "bbox": [min(lons), min(lats), max(lons), max(lats)],
            "maneuvers": maneuvers,
            "ms": int((time.time() - t0) * 1000),
        }
