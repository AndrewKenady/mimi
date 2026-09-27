"""Where am I? Location from a USB GPS (NMEA over serial), a phone on the MIMI
network, or a manually set place — plus offline lookups via GeoNames and
geotagged Wikipedia (see geodata.py).
"""

from __future__ import annotations

import threading
import time
from typing import Any

from . import db as dbm
from . import log
from .events import EventBus
from .paths import Paths
from .settings import SettingsStore

L = log.get("location")
GPS_FRESH = 60        # seconds a GPS fix stays "current"
CLIENT_FRESH = 600    # seconds a phone-provided fix stays "current"


def _nmea_coord(value: str, hemi: str) -> float | None:
    if not value:
        return None
    try:
        dot = value.index(".")
        deg = float(value[: dot - 2])
        minutes = float(value[dot - 2 :])
        v = deg + minutes / 60
        return -v if hemi in ("S", "W") else v
    except (ValueError, IndexError):
        return None


def parse_nmea(line: str) -> dict | None:
    """Parse RMC/GGA sentences into a fix dict (no checksum dependency)."""
    if not line.startswith("$") or "," not in line:
        return None
    body = line.split("*", 1)[0]
    f = body.split(",")
    kind = f[0][-3:]
    if kind == "RMC" and len(f) >= 7 and f[2] == "A":
        lat, lon = _nmea_coord(f[3], f[4]), _nmea_coord(f[5], f[6])
        speed = float(f[7]) * 1.852 if len(f) > 7 and f[7] else None
        if lat is not None and lon is not None:
            return {"lat": lat, "lon": lon, "speed_kmh": speed}
    if kind == "GGA" and len(f) >= 8 and f[6] not in ("", "0"):
        lat, lon = _nmea_coord(f[2], f[3]), _nmea_coord(f[4], f[5])
        if lat is not None and lon is not None:
            return {"lat": lat, "lon": lon, "sats": int(f[7] or 0)}
    return None


class LocationService:
    def __init__(self, paths: Paths, settings: SettingsStore, events: EventBus, db: dbm.Database):
        self.paths = paths
        self.settings = settings
        self.events = events
        self.db = db
        self.geo = None
        self.gps: dict | None = None
        self.client_fix: dict | None = None
        self.gps_port: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_logged = 0.0

    # --- lifecycle ---------------------------------------------------------------
    def start(self) -> None:
        self.reload_geodata()
        self._thread = threading.Thread(target=self._gps_loop, name="gps", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def reload_geodata(self) -> None:
        # Close the old handles first: on Windows an open file can't be replaced,
        # and GeoData swaps in freshly built *.sqlite.new files when it opens.
        if self.geo is not None:
            try:
                self.geo.close()
            except Exception:
                pass
            self.geo = None
        try:
            from .geodata import GeoData

            geo = GeoData(self.paths.maps)
            self.geo = geo if geo else None
        except Exception as e:
            L.info("geodata unavailable: %s", e)
            self.geo = None

    # --- state ---------------------------------------------------------------------
    def available(self) -> bool:
        return self.current() is not None or bool(self.geo)

    def current(self) -> dict | None:
        cfg = self.settings.device("location")
        if cfg.source == "off":
            return None
        now = time.time()
        if cfg.source in ("auto", "gps") and self.gps and now - self.gps["ts"] < GPS_FRESH:
            return {**self.gps, "source": "gps"}
        if cfg.source == "auto" and self.client_fix and now - self.client_fix["ts"] < CLIENT_FRESH:
            return {**self.client_fix, "source": "device"}
        if cfg.source in ("auto", "manual") and cfg.manual and "lat" in cfg.manual:
            return {"lat": float(cfg.manual["lat"]), "lon": float(cfg.manual["lon"]), "label": cfg.manual.get("label"), "source": "manual", "ts": now}
        return None

    def set_client_fix(self, lat: float, lon: float, accuracy: float | None = None) -> None:
        self.client_fix = {"lat": lat, "lon": lon, "accuracy": accuracy, "ts": time.time()}
        self._record(lat, lon, "device", accuracy)
        self.events.publish("location", self.status(), sticky=True)

    def status(self) -> dict:
        cur = self.current()
        desc = self.describe() if cur else None
        return {
            "current": cur,
            "description": desc,
            "gps": {"port": self.gps_port, "fix": bool(self.gps and time.time() - self.gps["ts"] < GPS_FRESH), "last": self.gps},
            "geodata": {
                "places": bool(self.geo and getattr(self.geo, "places_available", True)),
                "wikipedia": bool(self.geo and getattr(self.geo, "wiki_available", True)),
            },
        }

    def describe(self) -> dict | None:
        cur = self.current()
        if not cur:
            return None
        info: dict[str, Any] = {"lat": round(cur["lat"], 5), "lon": round(cur["lon"], 5), "source": cur["source"]}
        if self.geo:
            try:
                w = self.geo.where_am_i(cur["lat"], cur["lon"]) or {}
                info.update({k: w.get(k) for k in ("place", "admin1", "country", "distance_km", "distance_mi", "direction", "description") if k in w})
                if self.settings.device("general").units == "imperial" and w.get("description_mi"):
                    info["description"] = w["description_mi"]
            except Exception as e:
                L.warning("where_am_i failed: %s", e)
        if cur.get("label") and not info.get("description"):
            info["description"] = cur["label"]
        elif cur.get("label"):
            info["label"] = cur["label"]
        return info

    def nearby(self, lat: float, lon: float, radius_km: float = 15, kinds: list[str] | None = None, limit: int = 20) -> list[dict]:
        if not self.geo:
            return []
        try:
            return self.geo.nearby(lat, lon, radius_km=radius_km, kinds=kinds, limit=limit)
        except Exception as e:
            L.warning("nearby failed: %s", e)
            return []

    def search(self, query: str, limit: int = 10) -> list[dict]:
        if not self.geo:
            return []
        cur = self.current()
        try:
            return self.geo.search_places(query, limit=limit, near=(cur["lat"], cur["lon"]) if cur else None)
        except Exception as e:
            L.warning("place search failed: %s", e)
            return []

    def _record(self, lat: float, lon: float, source: str, accuracy: float | None = None) -> None:
        cfg = self.settings.device("location")
        if not cfg.history or time.time() - self._last_logged < 60:
            return
        self._last_logged = time.time()
        self.db.execute("INSERT INTO locations(ts,lat,lon,source,accuracy) VALUES(?,?,?,?,?)", (time.time(), lat, lon, source, accuracy))
        self.db.execute("DELETE FROM locations WHERE ts < ?", (time.time() - cfg.history_days * 86400,))

    def history(self, days: int = 7) -> list[dict]:
        return self.db.all("SELECT ts,lat,lon,source FROM locations WHERE ts > ? ORDER BY ts", (time.time() - days * 86400,))

    # --- GPS -------------------------------------------------------------------------
    def _candidate_ports(self) -> list[str]:
        cfg = self.settings.device("location")
        if cfg.gps_port and cfg.gps_port != "auto":
            return [cfg.gps_port]
        try:
            from serial.tools import list_ports

            ports = list(list_ports.comports())
        except Exception:
            return []
        # Only listen (never write) to ports that look like GNSS receivers; other
        # ports can be chosen explicitly in Settings → Maps & Location.
        keys = ("gps", "gnss", "u-blox", "ublox", "nmea", "sirf", "usb serial")
        return [p.device for p in ports if any(k in (p.description or "").lower() for k in keys)]

    def _gps_loop(self) -> None:
        try:
            import serial  # pyserial
        except Exception:
            L.info("pyserial not available; GPS disabled")
            return
        while not self._stop.is_set():
            cfg = self.settings.device("location")
            if cfg.source not in ("auto", "gps"):
                self._stop.wait(10)
                continue
            found = False
            for port in self._candidate_ports():
                for baud in (9600, 4800, 38400, 115200):
                    if self._stop.is_set():
                        return
                    try:
                        with serial.Serial(port, baud, timeout=1.5) as s:
                            deadline = time.time() + 4
                            saw_nmea = False
                            while time.time() < deadline or saw_nmea:
                                raw = s.readline().decode("ascii", "ignore").strip()
                                if raw.startswith("$G"):
                                    if not saw_nmea:
                                        L.info("GPS found on %s @ %s baud", port, baud)
                                        self.gps_port = port
                                    saw_nmea = True
                                    found = True
                                    fix = parse_nmea(raw)
                                    if fix:
                                        prev = self.gps
                                        self.gps = {**(prev or {}), **fix, "ts": time.time()}
                                        self._record(fix["lat"], fix["lon"], "gps")
                                        if not prev or time.time() - prev.get("_pub", 0) > 5:
                                            self.gps["_pub"] = time.time()
                                            self.events.publish("location", self.status(), sticky=True)
                                if self._stop.is_set():
                                    return
                                if saw_nmea and time.time() - (self.gps or {}).get("ts", time.time()) > 30 and not raw:
                                    break
                    except Exception:
                        continue
                    if found:
                        break
                if found:
                    break
            self.gps_port = None if not found else self.gps_port
            self._stop.wait(20 if not found else 2)
