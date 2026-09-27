"""Where am I? Location from a USB GPS (NMEA over serial), a phone on the Mimi
network, or a manually set place — plus offline lookups via GeoNames and
geotagged Wikipedia (see geodata.py) and street addresses (see address.py).
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


def _merge(first: list[dict], second: list[dict], limit: int) -> list[dict]:
    """``first`` then ``second``, keeping room for a few of the second kind (3 of 10, 1 of 3)
    and dropping the same thing found twice."""
    from .geodata import haversine_km

    head = first[: max(1, limit - min(len(second), limit // 3))]
    out: list[dict] = []
    for r in head + second:
        if len(out) >= limit:
            break
        name = str(r.get("name") or "").lower()
        if any(str(o.get("name") or "").lower() == name and haversine_km(o["lat"], o["lon"], r["lat"], r["lon"]) < 0.3 for o in out):
            continue
        out.append(r)
    return out


class LocationService:
    def __init__(self, paths: Paths, settings: SettingsStore, events: EventBus, db: dbm.Database):
        self.paths = paths
        self.settings = settings
        self.events = events
        self.db = db
        self.geo = None
        self.addr = None
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
        # and GeoData/AddressIndex swap in freshly built *.sqlite.new files when they open.
        for handle in (self.geo, self.addr):
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
        self.geo = self.addr = None
        try:
            from .geodata import GeoData

            geo = GeoData(self.paths.maps)
            self.geo = geo if geo else None
        except Exception as e:
            L.info("geodata unavailable: %s", e)
        try:
            from .address import AddressIndex

            addr = AddressIndex(self.paths.maps / AddressIndex.FILE)
            self.addr = addr if addr else None
        except Exception as e:
            L.warning("address index unavailable: %s", e)

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
                "addresses": bool(self.addr),
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
        return self.search_detailed(query, limit)[0]

    def search_detailed(self, query: str, limit: int = 10) -> tuple[list[dict], str | None]:
        """Places and street addresses for the map's search box and the chat tools.

        Returns (results, note); the note says when address search failed and only
        places are shown, so a broken index isn't mistaken for "no such address".
        Something that looks like an address lists addresses first; anything else lists
        places first, followed by streets when it names one ("Elm Street").
        """
        from .address import looks_like_address, parse_address

        cur = self.current()
        near = (cur["lat"], cur["lon"]) if cur else None
        geo, addr = self.geo, self.addr
        places: list[dict] = []
        addrs: list[dict] = []
        note = None
        if geo:
            try:
                places = geo.search_places(query, limit=limit, near=near)
            except Exception as e:
                L.warning("place search failed: %s", e)
        address_first = looks_like_address(query)
        parsed = parse_address(query) if addr or address_first else None
        if addr and (address_first or parsed["typed"]):
            try:
                addrs = addr.search(query, near=near, limit=limit,
                                    resolve_place=(lambda q: geo.search_places(q, limit=8, near=near)) if geo else None,
                                    describe=geo.where_am_i if geo else None)
            except Exception:
                L.exception("address search failed for %r", query)
                note = "Street address search isn't working right now, so only places are shown."
        if address_first and not addrs and not places and geo and parsed and parsed["locality"]:
            # "123 Nowhere St, Laramie WY": at least find the town
            town = parsed["locality"] + (f", {parsed['region'].upper()}" if parsed["region"] else "")
            try:
                places = geo.search_places(town, limit=min(limit, 3), near=near)
            except Exception as e:
                L.warning("place search failed: %s", e)
        from .geodata import name_key

        # a place named like the whole query, or like its street part ("Central Park" for
        # "Central Park, New York"), among the first few
        want = {name_key(query)} | ({name_key(parsed["street"])} if parsed and parsed["street"] else set())
        exact_place = any(name_key(pl.get("name") or "") in want for pl in places[:3])
        if not address_first and addrs and places and near is not None and (addrs[0].get("distance_km") or 1e9) <= 50:
            # "Main St" with the device in Laramie means Laramie's Main St, not a museum
            # called "Main Street" three states away; a place of exactly that name still wins
            address_first = not exact_place
        elif address_first and exact_place and parsed and parsed["number"] is None:
            address_first = False  # "Central Park, New York" is the park before Central Park W
        first, second = (addrs, places) if address_first else (places, addrs)
        return _merge(first, second, limit), note

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
