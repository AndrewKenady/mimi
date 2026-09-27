"""Offline street-address search for the US and Canada.

Reads ``maps/addresses.sqlite`` (built by ``scripts/build_addresses.py``), which merges
three sources into one set of streets keyed by ``address_norm.street_key``:

* US Census TIGER address ranges (public domain): house-number ranges along street
  segments, interpolated to a position ("123" is 23% of the way along 101-199).
* Statistics Canada National Address Register (Open Licence) and OpenStreetMap
  ``addr:*`` points (ODbL): exact positions of individual civic numbers.
* Street names alone (OSM roads, TIGER), for "Main St, Laramie" without a number.

Streets are stored once per 0.1 degree grid cell, so a lookup is an index probe on
``(key, cell)`` for the few cells around the town the user named; no query ever scans
a table. The town itself comes from the place gazetteer (``GeoData.search_places``),
passed in as ``resolve_place`` so this module has no dependency on it.

Results use the shape of ``GeoData.search_places`` results (name, label, kind, lat,
lon, admin1, country, ...) plus ``precision`` and ``postcode``, so the map and the
chat tools can show them without special cases.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import log
from .address_norm import (
    DIRECTIONS, DIRS, STATE_CODES, STATES, TYPE_WORDS, TYPES, VERSION, fold, house_number, street_base, street_key,
)
from .geodata import KM_PER_DEG_LAT, haversine_km, name_key
from .routing import decode_polyline6

L = log.get("address")

__all__ = ["AddressIndex", "parse_address", "looks_like_address", "cell_of", "cells_around", "encode_polyline"]

CA_REGIONS = frozenset(("ab", "bc", "mb", "nb", "nl", "ns", "nt", "nu", "on", "pe", "qc", "sk", "yt"))


def _region_names() -> dict[str, str]:
    out: dict[str, str] = {}
    for name, code in STATES.items():
        if len(name) > len(out.get(code, "")):  # "newfoundland and labrador", not "newfoundland"
            out[code] = name
    return {c: " ".join(w if w in ("of", "and") else w.capitalize() for w in n.split()) for c, n in out.items()}


REGION_NAMES = _region_names()


def region_country(code: str | None) -> str | None:
    return None if not code else ("CA" if code in CA_REGIONS else "US")


# ---------------------------------------------------------------------------
# Grid and geometry helpers (the builder uses the same definitions)
# ---------------------------------------------------------------------------


def cell_of(lat: float, lon: float) -> int:
    """0.1 degree grid cell of a point."""
    return int((lat + 90) * 10) * 3600 + int((lon + 180) * 10)


def cells_around(lat: float, lon: float, radius_km: float) -> list[int]:
    """Every grid cell touching the bounding box of a circle."""
    dlat = radius_km / KM_PER_DEG_LAT
    lat0, lat1 = max(-89.99, lat - dlat), min(89.99, lat + dlat)
    coslat = max(math.cos(math.radians(max(abs(lat0), abs(lat1)))), 0.02)
    dlon = min(179.9, radius_km / (KM_PER_DEG_LAT * coslat))
    c0, c1 = math.floor((lon - dlon + 180) * 10), math.floor((lon + dlon + 180) * 10)
    return [r * 3600 + c % 3600 for r in range(int((lat0 + 90) * 10), int((lat1 + 90) * 10) + 1) for c in range(c0, c1 + 1)]


def encode_polyline(points: list[tuple[float, float]], precision: int = 6) -> str:
    """Google polyline encoding of (lat, lon) pairs."""
    factor, out, plat, plon = 10 ** precision, [], 0, 0
    for lat, lon in points:
        ilat, ilon = round(lat * factor), round(lon * factor)
        for d in (ilat - plat, ilon - plon):
            v = ~(d << 1) if d < 0 else d << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        plat, plon = ilat, ilon
    return "".join(out)


def _along(geom: str, frac: float) -> tuple[float, float]:
    """The (lat, lon) a fraction of the way along a polyline6, by length."""
    pts = [(lat, lon) for lon, lat in decode_polyline6(geom)]
    if len(pts) == 1:
        return pts[0]
    k = math.cos(math.radians(pts[0][0]))
    lens = [math.hypot(b[0] - a[0], (b[1] - a[1]) * k) for a, b in zip(pts, pts[1:])]
    target = max(0.0, min(1.0, frac)) * sum(lens)
    for (a, b), seg in zip(zip(pts, pts[1:]), lens):
        if target <= seg and seg > 0:
            t = target / seg
            return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        target -= seg
    return pts[-1]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_ZIP = re.compile(r"(\d{5})(?:-\d{4})?")
_CA_CODE = re.compile(r"([A-Z]\d[A-Z])-?(\d[A-Z]\d)")
_FSA = re.compile(r"[A-Z]\d[A-Z]")
_NUMLIKE = re.compile(r"\d+[a-z]?")
_UNIT_CIVIC = re.compile(r"([A-Za-z]?\d{1,6}[A-Za-z]?|[A-Za-z])-(\d{1,7}[A-Za-z]?)")
_UNIT_ID = re.compile(r"#?(?:[A-Za-z]{0,3}-?\d{1,6}[A-Za-z]{0,2}|[A-Za-z])")
_UNIT_WORDS = frozenset(("apt", "apartment", "unit", "suite", "ste", "bldg", "building", "fl", "floor", "rm", "room", "lot",
                         "spc", "space", "trlr", "dept", "app", "appt", "appartement", "bureau", "ph", "penthouse"))
# Traditional (AP style) abbreviations and French names. The short ones are also ordinary
# words ("Iron Ore", "Isle of Man"), so they only count after a comma or with a period.
_REGION_ABBR = {
    "ala": "al", "ariz": "az", "ark": "ar", "calif": "ca", "cal": "ca", "colo": "co", "conn": "ct", "del": "de",
    "fla": "fl", "ill": "il", "ind": "in", "kan": "ks", "kans": "ks", "mass": "ma", "mich": "mi", "minn": "mn",
    "miss": "ms", "mont": "mt", "neb": "ne", "nebr": "ne", "nev": "nv", "okla": "ok", "ore": "or", "oreg": "or",
    "penn": "pa", "tenn": "tn", "tex": "tx", "wash": "wa", "wis": "wi", "wisc": "wi", "wyo": "wy", "alta": "ab",
    "sask": "sk", "man": "mb", "nfld": "nl", "que": "qc", "ont": "on", "pei": "pe", "nwt": "nt", "yuk": "yt",
}
_REGION_FRENCH = {
    "nouveau brunswick": "nb", "nouvelle ecosse": "ns", "ile du prince edouard": "pe", "terre neuve et labrador": "nl",
    "terre neuve": "nl", "colombie britannique": "bc", "territoires du nord ouest": "nt",
}
_COUNTRY_WORDS = {"usa": "US", "us": "US", "unitedstates": "US", "unitedstatesofamerica": "US", "canada": "CA"}
# street types that almost always end a street name; "Lake", "Park" or "Hill" often don't
_STRONG = frozenset(("st", "ave", "rd", "dr", "blvd", "ln", "ct", "pl", "way", "hwy", "pkwy", "cir", "ter", "trl", "cres",
                     "sq", "loop", "expy", "fwy", "tpke", "aly", "xing", "byp", "cswy", "plz", "rte", "sideroad",
                     "concession", "line", "close", "mews", "rue", "ch", "rang", "montee", "impasse", "terrasse"))
_FRENCH_FIRST = frozenset(("rue", "ch", "chemin", "boul", "boulevard", "blvd", "av", "ave", "avenue", "rang", "rg", "montee",
                           "cote", "prom", "promenade", "impasse", "imp", "terrasse", "sentier", "croissant", "allee",
                           "place", "carre"))
_FRENCH_KEY_FIRST = frozenset(("rue", "ch", "blvd", "ave", "rang", "montee", "cote", "prom", "impasse", "terrasse",
                               "sentier", "croissant", "aly", "pl", "carre"))
_PARTICLES = frozenset(("de", "du", "des", "la", "le", "les", "l", "d", "st", "ste", "saint", "sainte", "au", "aux"))
_ROUTE_PREFIXES = ("us hwy ", "i ", "hwy ", "co rd ")
_MAX_ALTS = 4


def _f(tok: str) -> str:
    """Folded form of one raw token ('St.' -> 'st', 'D.C.' -> 'dc')."""
    return fold(tok).replace(" ", "")


def _unit_civic(tok: str) -> re.Match | None:
    """Canadian "4-123" or "A-42": unit 4 (or A) of civic 123 (42); not a route such as "I-25"."""
    m = _UNIT_CIVIC.fullmatch(tok.lstrip("#"))
    if m and m.group(1).isalpha() and street_key(tok).startswith(_ROUTE_PREFIXES):
        return None
    return m


def _clean(text: str) -> str:
    s = (text or "").replace("½", " 1/2").replace(" ", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s.strip(" .,;:!?")


def _norm_postcode(text: str) -> str | None:
    """'82070', '82070-1234' -> '82070'; 'k1a 0b1' -> 'K1A0B1'; 'K1A' -> 'K1A'; else None."""
    t = text.strip().upper().replace(" ", "")
    if m := _ZIP.fullmatch(t):
        return m.group(1)
    if m := _CA_CODE.fullmatch(t):
        return m.group(1) + m.group(2)
    if _FSA.fullmatch(t):
        return t
    return None


def postcode_country(code: str | None) -> str | None:
    return None if not code else ("US" if code.isdigit() else "CA")


def format_postcode(code: str | None) -> str | None:
    return f"{code[:3]} {code[3:]}" if code and len(code) == 6 and not code.isdigit() else code


def _is_typed(key: str) -> bool:
    """Does a street key end in a street type or name a numbered route?"""
    toks = key.split()
    if not toks:
        return False
    if key.startswith(_ROUTE_PREFIXES):
        return True
    if len(toks) > 1 and toks[-1] in TYPES:
        return True
    if len(toks) > 2 and toks[-1] in DIRS and toks[-2] in TYPES:
        return True
    return len(toks) > 1 and toks[0] in _FRENCH_KEY_FIRST


def _route_end(f: list[str]) -> float:
    """3.5 if the tokens are a complete numbered route ('us 20', 'county road 5 n'), else 0."""
    if not f or not f[-1]:
        return 0.0
    last = f[-1]
    if not (_NUMLIKE.fullmatch(last) or (last in DIRECTIONS and len(f) > 1 and _NUMLIKE.fullmatch(f[-2]))):
        return 0.0
    k = street_key(" ".join(f))
    return 3.5 if k.startswith(_ROUTE_PREFIXES) else 0.0


def _split_scores(f: list[str], prefer_locality: bool) -> list[tuple[float, int]]:
    """Where a comma-less "street locality" run of tokens most plausibly splits.

    Returns (score, i) pairs, best first: tokens[:i] is the street, tokens[i:] the
    locality. A split right after a street type ("Main St | Springfield") or a
    numbered route ("US 20 | Basin") scores high, as does a trailing direction that
    belongs to the street ("King St W | Toronto").
    """
    n = len(f)
    out = []
    for i in range(1, n + 1):
        head, rest = f[:i], f[i:]
        last, t_last = head[-1], TYPE_WORDS.get(head[-1])
        if not rest:
            ends = (t_last in TYPES and i >= 2) or _route_end(head) or (head[0] in _FRENCH_FIRST and i >= 2) \
                or (last in DIRECTIONS and i >= 3 and TYPE_WORDS.get(head[-2]) in TYPES)
            s = 1.0 if ends else 0.8 if _NUMLIKE.fullmatch(last) and i >= 2 else 0.2
        elif all(x in DIRECTIONS for x in rest):
            s = -5.0  # "100 Main St | NE": a trailing direction is part of the street, never the town
        else:
            s = 0.0
            if r := _route_end(head):
                s = r + (0.2 if last in DIRECTIONS else 0.0)
            elif t_last in _STRONG and i >= 2:
                s = 3.0
            elif t_last in TYPES and i >= 2:
                s = 1.5
            elif last in DIRECTIONS and i >= 3 and TYPE_WORDS.get(head[-2]) in TYPES:
                s = (3.4 if len(last) <= 2 else 3.1) if TYPE_WORDS.get(head[-2]) in _STRONG else 1.7
            elif head[0] in _FRENCH_FIRST and i >= 2 and last not in _PARTICLES:
                s = 2.0 - 0.3 * (i - 2 - sum(1 for x in head[1:-1] if x in _PARTICLES))
            elif _NUMLIKE.fullmatch(last) and i >= 2:
                s = 1.0  # a numbered road without a type: "Autauga County 4 | Prattville"
            elif last in DIRECTIONS and i >= 3 and _NUMLIKE.fullmatch(head[-2]):
                s = 1.1  # "Autauga County 68 W | Marbury"
            if _NUMLIKE.fullmatch(rest[-1]):
                s -= 1.5  # town names don't end in a number, numbered roads do
            first = TYPE_WORDS.get(rest[0])
            if first in _STRONG:
                s -= 2.0
            elif first in TYPES:
                s -= 0.5
            if _NUMLIKE.fullmatch(rest[0]):
                s -= 2.0  # "County Road | 5": the number belongs to the street
            if prefer_locality:
                s += 0.3
        out.append((s, i))
    out.sort(key=lambda x: (-x[0], x[1]))
    return out


def _take_region(tokens: list[str], guarded: bool) -> tuple[str, str | None] | None:
    """Remove a trailing state/province ('IL', 'New York') from tokens; returns (code, name).

    ``guarded`` is for a run that starts with the street itself, where "12 Oak Ct" or
    "100 Main St NE" end in a street type or direction rather than Connecticut or Nebraska.
    """
    f = [_f(t) for t in tokens]
    for n in (4, 3, 2, 1):
        if len(f) < n:
            continue
        cand = " ".join(f[-n:])
        plain = cand.replace("-", " ")
        code = STATES.get(plain) or _REGION_FRENCH.get(plain) \
            or (cand if n == 1 and len(cand) == 2 and cand in STATE_CODES else None)
        if not code and n == 1 and cand in _REGION_ABBR and (not guarded or tokens[-1].endswith(".")):
            code, cand = _REGION_ABBR[cand], _REGION_ABBR[cand]
        if not code:
            continue
        rest = f[:-n]
        if guarded:
            street = rest[1:] if rest and (house_number(rest[0]) or _unit_civic(rest[0])) else rest
            if not street:
                return None
            if len(cand) == 2:
                if cand in TYPE_WORDS and not any(TYPE_WORDS.get(x) in _STRONG for x in street):
                    return None
                if cand in DIRECTIONS and (TYPE_WORDS.get(rest[-1]) in TYPES or _NUMLIKE.fullmatch(rest[-1])):
                    return None
        del tokens[-n:]
        return code, cand if n > 1 or len(cand) > 2 else None
    return None


def _lead_number(tokens: list[str]) -> bool:
    return bool(tokens) and bool(house_number(tokens[0]) or _unit_civic(tokens[0]))


def _is_unit_seg(tokens: list[str]) -> str | None:
    if len(tokens) == 1 and tokens[0].startswith("#") and len(tokens[0]) > 1:
        return tokens[0][1:]
    if len(tokens) == 2 and (_f(tokens[0]) in _UNIT_WORDS or tokens[0] == "#") and _UNIT_ID.fullmatch(tokens[1]):
        return tokens[1].lstrip("#")
    return None


def parse_address(text: str) -> dict:
    """Split a free-form US/Canadian address into its parts.

    Returns ``{number, numtext, unit, street, key, locality, region, postcode, country,
    typed, confident, alts}``: ``region`` is a lowercase 2-letter state/province code,
    ``postcode`` a 5-digit ZIP or an uppercase Canadian code without the space,
    ``typed`` whether the street has a type or is a numbered route, ``confident``
    whether the street/locality boundary is clear (a comma, or a split right after a
    street type), and ``alts`` every plausible (street, key, locality) reading, the
    primary one first, for input without commas.
    """
    out: dict = {"number": None, "numtext": None, "unit": None, "street": "", "key": "", "locality": None,
                 "region": None, "postcode": None, "country": None, "typed": False, "confident": False, "alts": []}
    s = _clean(text)
    if not s:
        return out
    if pc := _norm_postcode(s):
        out.update(postcode=pc, country=postcode_country(pc), confident=True)
        return out
    segs = [seg.split() for seg in re.split(r"[,;]", s)]
    segs = [x for x in segs if x]
    country = None

    # trailing country and postcode, in either order ("..., ON M5V 1A1, Canada")
    postcode = None
    changed = True
    while changed and segs:
        changed = False
        last = segs[-1]
        f = [_f(t) for t in last]
        for n in (4, 3, 2, 1):
            if len(f) >= n and "".join(f[-n:]) in _COUNTRY_WORDS and not (len(segs) == 1 and len(f) == n):
                country = _COUNTRY_WORDS["".join(f[-n:])]
                del last[-n:]
                changed = True
                break
        if not changed and postcode is None:
            if len(last) >= 2 and _CA_CODE.fullmatch("".join(last[-2:]).upper()) and _FSA.fullmatch(last[-2].upper()):
                postcode = _norm_postcode("".join(last[-2:]))
                del last[-2:]
                changed = True
            elif _CA_CODE.fullmatch(last[-1].upper()) or (_ZIP.fullmatch(last[-1]) and not (len(segs) == 1 and len(last) == 1)):
                postcode = _norm_postcode(last[-1])
                del last[-1]
                changed = True
        segs = [x for x in segs if x]
    if not segs:
        out.update(postcode=postcode, country=postcode_country(postcode) or country)
        return out

    # the state or province, from the end of the last part
    region, soft_locality = None, None
    last = segs[-1]
    guarded = len(segs) == 1 or _lead_number(last)
    if got := _take_region(last, guarded):
        region, name = got
        if name in ("washington", "new york") and (guarded or not last):
            # "1600 Pennsylvania Ave, Washington" is the city, not the state
            soft_locality = name.title()
            if name == "washington":
                region = None
    segs = [x for x in segs if x]

    unit = None
    kept = []
    for seg in segs:
        u = _is_unit_seg(seg)
        if u is not None and unit is None:
            unit = u
        else:
            kept.append(seg)
    segs = kept
    if not segs:
        out.update(region=region, postcode=postcode, country=postcode_country(postcode) or region_country(region) or country)
        return out

    # the part with the house number is the street; anything before it (a building name) is dropped
    si = next((i for i, seg in enumerate(segs) if _lead_number(seg) or (len(seg) >= 3 and _f(seg[0]) in _UNIT_WORDS
                                                                           and _lead_number(seg[2:]))), 0)
    if len(segs[si]) == 1 and _lead_number(segs[si]) and si + 1 < len(segs):  # "123, rue Principale"
        segs[si] = segs[si] + segs.pop(si + 1)
    tokens = list(segs[si])
    later = segs[si + 1:]

    if len(tokens) >= 3 and (_f(tokens[0]) in _UNIT_WORDS or tokens[0] == "#") and _UNIT_ID.fullmatch(tokens[1]) \
            and _lead_number(tokens[2:]):
        unit, tokens = tokens[1].lstrip("#"), tokens[2:]  # "Apt 4 123 Main St"
    elif len(tokens) >= 2 and tokens[0].startswith("#") and len(tokens[0]) > 1 and _lead_number(tokens[1:]):
        unit, tokens = tokens[0][1:], tokens[1:]

    number = numtext = None
    if tokens:
        m = _unit_civic(tokens[0])
        if m and len(tokens) > 1:  # Canadian "4-123 King St W": unit 4 of civic 123
            hn = house_number(m.group(2))
            if hn:
                unit = unit or m.group(1)
                number, numtext = hn
                tokens = tokens[1:]
        elif len(tokens) > 2 and tokens[1] in ("1/2",) and house_number(tokens[0] + " 1/2"):
            number, numtext = house_number(tokens[0] + " 1/2")
            tokens = tokens[2:]
        elif len(tokens) > 1 and (hn := house_number(tokens[0])):
            number, numtext = hn
            tokens = tokens[1:]

    # an inline unit ends the street: "123 Main St Apt 4 Springfield"
    after: list[str] = []
    for j in range(1, len(tokens)):
        t = tokens[j]
        nxt = tokens[j + 1] if j + 1 < len(tokens) else ""
        if t.startswith("#") and (len(t) > 1 or nxt):
            uid, span = (t[1:], 1) if len(t) > 1 else (nxt, 2)
        elif _f(t) in _UNIT_WORDS and nxt and _UNIT_ID.fullmatch(nxt) and (_f(t) != "ste" or any(c.isdigit() for c in nxt)):
            uid, span = nxt, 2
        else:
            continue
        unit = unit or uid.lstrip("#")
        after = tokens[j + span:]
        tokens = tokens[:j]
        break

    locality = " ".join(later[-1]) if later else (" ".join(after) if after else None)
    if soft_locality and not guarded:
        locality = locality or soft_locality
    readings: list[tuple[float, list[str], str | None]] = []
    if locality or not tokens:
        readings.append((9.0, tokens, locality))
    else:
        f = [_f(t) for t in tokens]
        # with a house number and a state or postcode, a town is probably in there too
        split = _split_scores(f, number is not None and (region is not None or postcode is not None))
        for score, i in split[:1] + [x for x in split[1:] if x[0] > -1.0][:_MAX_ALTS - 1]:
            readings.append((score, tokens[:i], " ".join(tokens[i:]) or None))
    if soft_locality:
        readings = [(sc, st, loc or soft_locality) for sc, st, loc in readings]

    alts = []
    for score, st, loc in readings:
        raw = " ".join(st).strip(" .")
        key = street_key(raw)
        if key:
            alts.append({"street": raw, "key": key, "locality": loc, "score": score})
    primary = alts[0] if alts else {"street": "", "key": "", "locality": locality, "score": 0.0}
    out.update(
        number=number, numtext=numtext, unit=unit, street=primary["street"], key=primary["key"],
        locality=primary["locality"], region=region, postcode=postcode,
        country=postcode_country(postcode) or region_country(region) or country,
        typed=_is_typed(primary["key"]), confident=primary["score"] >= 2.5, alts=alts,
    )
    return out


def looks_like_address(text: str) -> bool:
    """True for "123 Main St", "Main St, Laramie", "US 20, Basin WY" or a bare postcode;
    False for place names such as "Jackson", "Old Faithful" or "Yellowstone Lake"."""
    p = parse_address(text)
    if not p["key"]:
        return bool(p["postcode"]) and p["number"] is None
    if p["number"] is not None and re.search(r"[^\W\d_]", p["street"]):
        return True
    return p["typed"] and p["confident"] and bool(p["locality"] or p["postcode"])


# ---------------------------------------------------------------------------
# The index
# ---------------------------------------------------------------------------

_PREC = {"exact": 100.0, "interpolated": 90.0, "nearby": 55.0, "street": 40.0, "postcode": 30.0}
_GOOD = ("exact", "interpolated")
_PLACE_SKIP = frozenset(("ADM1", "PCLI", "PCLS", "PCLD", "PCLIX", "CONT", "RGN"))
_STREET_COLS = "id, key, base, name, cell, lat, lon, region, postcode"


@dataclass
class _Anchor:
    lat: float
    lon: float
    radius: float
    kind: str  # "postcode" | "place" | "near"
    rank: int = 0
    name: str | None = None
    admin1: str | None = None
    country: str | None = None


def _place_radius(place: dict) -> float:
    """How far from a town's centre its street addresses can be (8-40 km)."""
    if (place.get("fcode") or "").startswith("ADM"):
        return 40.0
    pop = place.get("population") or 0
    return max(8.0, min(40.0, 6.0 + 0.262 * max(pop, 1) ** 0.32))


def _towns(places: list[dict]) -> list[dict]:
    """Populated places, without historical, abandoned or destroyed ones."""
    return [pl for pl in places if (pl.get("fcode") or "").startswith(("PPL", "ADM"))
            and not (pl.get("fcode") or "").startswith(("PPLH", "PPLQ", "PPLW")) and pl.get("lat") is not None]


def _typos(a: str, b: str) -> int:
    """Edit distance counting a swap of two neighbouring letters as one typo."""
    if abs(len(a) - len(b)) > 2:
        return 3
    prev2, prev = [], list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


def _directions(key: str) -> set[str]:
    toks = key.split()
    return {t for t in (toks[:1] + toks[-1:]) if t in DIRS} if len(toks) > 1 else set()


def _full_words() -> dict[str, str]:
    """'crk' -> 'creek', 'w' -> 'west': the first spelled-out variant of each abbreviation."""
    out: dict[str, str] = {}
    for table in (TYPE_WORDS, DIRECTIONS):
        for word, canon in table.items():
            if canon not in out and len(word) > len(canon) and word != canon + "s":
                out[canon] = word
    return out


_FULL_WORD = _full_words()


def _spelled_out(key: str) -> str | None:
    """A looser base for input without a street type: the last word written out.

    "Bridge Creek" was keyed as "bridge crk" but is probably Bridge Creek Rd (base
    "bridge creek"), "2nd West" ("2nd w") probably 2nd West St, and "North Pine"
    ("n pne") North Pine St (base "pine").
    """
    toks = key.split()
    if len(toks) < 2 or key.startswith(_ROUTE_PREFIXES) or toks[0] in _FRENCH_KEY_FIRST:
        return None
    full = _FULL_WORD.get(toks[-1])
    return street_base(" ".join(toks[:-1] + [full])) if full else None


_TYPE_SPELLINGS: dict[str, list[str]] = {}
for _word, _canon in TYPE_WORDS.items():
    _TYPE_SPELLINGS.setdefault(_canon, []).append(_word)
# how an English speaker may write a French street: "Cocagne Sud Rd" is Chemin Cocagne Sud
_EN_TO_FR = {"st": "rue", "rd": "chemin", "ave": "avenue", "blvd": "boulevard", "dr": "promenade", "cres": "croissant",
             "ter": "terrasse"}


def _key_variants(street: str, key: str, country: str | None) -> list[str]:
    """Other exact keys the same street may be indexed under.

    The key of a French name keeps an unrecognized leading type word as written, so
    "av. 32e" and "Avenue 32e" key differently; and "des Acadiens Blvd" is how
    Boulevard des Acadiens reads in English.
    """
    words = fold(street).split()
    if len(words) < 2 or key.startswith(_ROUTE_PREFIXES):
        return []
    out = set()
    # "Cir Dr" is indexed as "circle dr": only the last word is a street type
    inner = [_FULL_WORD.get(TYPE_WORDS[w], w) if w in TYPE_WORDS and w != "st" else w for w in words[:-1]]
    out.add(street_key(" ".join(inner + words[-1:])))
    first = TYPE_WORDS.get(words[0])
    if first in _FRENCH_KEY_FIRST:
        out.update(street_key(" ".join([w] + words[1:])) for w in _TYPE_SPELLINGS[first])
    last = TYPE_WORDS.get(words[-1])
    if last in _EN_TO_FR and country != "US":
        out.add(street_key(" ".join([_EN_TO_FR[last]] + words[:-1])))
    out.discard(key)
    out.discard("")
    return sorted(out)


def _direction_penalty(want: str, got: str) -> float:
    """A looser match on the wrong side of town ("W 5th Ave" vs "E 5th St") ranks below the right side."""
    w, g = _directions(want), _directions(got)
    if not w or w == g:
        return 0.0
    return 10.0 if g else 3.0


class AddressIndex:
    """Read-only access to ``addresses.sqlite``. Thread-safe; call :meth:`close` when done."""

    FILE = "addresses.sqlite"

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self.meta: dict[str, str] = {}
        self._pc_regions: dict[str, str | None] = {}
        pending = self.path.with_name(self.path.name + ".new")
        if pending.is_file():  # a rebuild that couldn't replace the file while it was open (Windows)
            try:
                os.replace(pending, self.path)
            except OSError:
                pass
        if not self.path.is_file():
            return
        conn = None
        try:
            conn = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)
            conn.execute("PRAGMA query_only = 1")
            conn.execute("PRAGMA mmap_size = 268435456")
            self.meta = {k: v for k, v in conn.execute("SELECT key, value FROM meta")}
        except sqlite3.Error as e:
            L.warning("address index %s unreadable: %s", self.path, e)
            if conn is not None:
                conn.close()
            return
        if self.meta.get("norm_version") != str(VERSION):
            L.warning("address index %s was built with normalization v%s, this version needs v%s; rebuild it "
                      "(scripts/build_addresses.py). Street addresses are off until then.",
                      self.path, self.meta.get("norm_version"), VERSION)
            conn.close()
            return
        self._conn = conn

    def available(self) -> bool:
        return self._conn is not None

    def __bool__(self) -> bool:
        return self.available()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
            self._conn = None

    def info(self) -> dict:
        """Availability, build date, sources and row counts, from the meta table."""
        if not self.available():
            return {"available": False}
        counts = {k: int(v) for k, v in self.meta.items() if k != "norm_version" and str(v).isdigit()}
        try:
            sources = json.loads(self.meta.get("sources") or "null")
        except ValueError:
            sources = self.meta.get("sources")
        return {"available": True, "built_at": self.meta.get("built_at"), "sources": sources, "counts": counts}

    def _all(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._lock:
            if self._conn is None:
                raise sqlite3.ProgrammingError("address index is closed")
            return self._conn.execute(sql, params).fetchall()

    # -- search ---------------------------------------------------------------

    def search(self, text: str, *, near: tuple[float, float] | None = None,
               resolve_place: Callable[[str], list[dict]] | None = None,
               describe: Callable[[float, float], dict] | None = None, limit: int = 5) -> list[dict]:
        """Find an address, a street or a postcode. See the module docstring for the result shape.

        ``resolve_place(query)`` finds the town named in the address (GeoData.search_places),
        ``describe(lat, lon)`` names the town a result is in (GeoData.where_am_i), and
        ``near`` (the device's position) breaks ties and anchors addresses without a town.
        """
        if not self.available():
            return []
        p = parse_address(text)
        if not p["key"] and not p["postcode"]:
            return []
        limit = max(1, int(limit))
        pc_row = self._postcode(p["postcode"]) if p["postcode"] else None
        results: list[dict] = []
        if not p["key"]:
            if pc_row:
                results.append(self._postcode_result(p["postcode"], pc_row, near, describe))
            return self._finish(results, describe)


        for ai, alt in enumerate(p["alts"]):
            anchors = self._anchors(p, alt, pc_row, near, resolve_place)
            found = self._search_alt(p, alt, ai, anchors, near)
            results += found
            # a hit on a looser spelling ("Autauga St" for "Autauga County 4") doesn't end the
            # search: another reading of the input may name the street exactly
            if any(r["precision"] in _GOOD and r["_key"] == alt["key"] for r in found) or (found and p["number"] is None):
                break
        if p["number"] is not None and describe is not None and not any(r["precision"] in _GOOD for r in results):
            alt = next((a for a in p["alts"] if a["locality"]), None)
            if alt:
                results += self._in_named_town(p, alt, describe, near)
        if not results and pc_row:
            results.append(self._postcode_result(p["postcode"], pc_row, near, describe))
            results[-1]["_score"] = 0.0
        return self._finish(self._dedupe(results)[:limit], describe)

    def _finish(self, results: list[dict], describe) -> list[dict]:
        """Label the results and drop the private ranking fields."""
        self._label(results, describe)
        for r in results:
            for k in [k for k in r if k.startswith("_")]:
                del r[k]
        return results

    def _postcode_region(self, code: str | None) -> str | None:
        """The state or province of a postcode (or its FSA): labels a hit on a street whose
        region is unknown because the name runs on both sides of a state line there."""
        if not code:
            return None
        if code not in self._pc_regions:
            if len(self._pc_regions) > 20000:
                self._pc_regions.clear()
            rows = self._all("SELECT region FROM postcodes WHERE code = ?", (code,))
            if not rows and len(code) == 6:
                rows = self._all("SELECT region FROM postcodes WHERE code = ?", (code[:3],))
            self._pc_regions[code] = rows[0][0] if rows else None
        return self._pc_regions[code]

    def _postcode(self, code: str) -> tuple | None:
        rows = self._all("SELECT code, lat, lon, region FROM postcodes WHERE code = ?", (code,))
        if not rows and len(code) == 6:  # an unknown Canadian code: its forward sortation area
            rows = self._all("SELECT code, lat, lon, region FROM postcodes WHERE code = ?", (code[:3],))
        return rows[0] if rows else None

    def _postcode_result(self, code: str, row: tuple, near, describe) -> dict:
        found, lat, lon, region = row[0], row[1] / 1e6, row[2] / 1e6, row[3]
        r = {"name": format_postcode(found), "label": format_postcode(found), "kind": "postcode", "lat": lat, "lon": lon,
             "precision": "postcode", "source": "postcodes", "admin1": REGION_NAMES.get(region or ""),
             "country": postcode_country(found), "postcode": format_postcode(found),
             "_score": _PREC["postcode"], "_key": "#" + found, "_locality": None}
        if near is not None:
            r["distance_km"] = round(haversine_km(near[0], near[1], lat, lon), 2)
        return r

    def _anchors(self, p: dict, alt: dict, pc_row, near, resolve_place) -> list[_Anchor]:
        anchors: list[_Anchor] = []
        if pc_row:
            anchors.append(_Anchor(pc_row[1] / 1e6, pc_row[2] / 1e6, 25.0 if len(pc_row[0]) == 3 else 15.0, "postcode",
                                   admin1=REGION_NAMES.get(pc_row[3] or ""), country=postcode_country(pc_row[0])))
        if alt["locality"] and resolve_place is not None:
            q = alt["locality"] + (f", {p['region'].upper()}" if p["region"] else "")
            try:
                places = resolve_place(q) or []
            except Exception as e:
                L.warning("resolving %r failed: %s", q, e)
                places = []
            usable = []
            for pl in places:
                if (pl.get("fcode") or "") in _PLACE_SKIP or pl.get("lat") is None:
                    continue
                if p["country"] and pl.get("country") and pl["country"] != p["country"]:
                    continue
                if p["region"] and pl.get("admin1") and STATES.get(fold(pl["admin1"])) not in (None, p["region"]):
                    continue
                usable.append(pl)
            # A town, not the lake or hot spring named after it ("Basin" is not "Sizzling Basin"), and
            # the town of exactly that name when there is one (several Springfields, but not "Springfield
            # Gardens"); otherwise the gazetteer's best guess ("New York" -> New York City).
            towns = _towns(usable)
            want = name_key(alt["locality"])
            exact = [pl for pl in towns if name_key(pl.get("name") or "") == want]
            # without a state there may be many towns of that name (Sleepy Hollow NY, IL, CA, WY)
            chosen = (exact[:3 if p["region"] or pc_row else 8] or self._misspelt_towns(alt["locality"], p, resolve_place)
                      or towns[:1] or usable[:1])
            for rank, pl in enumerate(chosen):
                anchors.append(_Anchor(float(pl["lat"]), float(pl["lon"]), _place_radius(pl), "place", rank,
                                       pl.get("name"), pl.get("admin1"), pl.get("country")))
        if not anchors and near is not None:
            anchors.append(_Anchor(near[0], near[1], 60.0, "near"))
        return anchors

    @staticmethod
    def _misspelt_towns(locality: str, p: dict, resolve_place) -> list[dict]:
        """Towns whose name is one or two typos from ``locality`` ("Stephevnille" -> Stephenville).

        The gazetteer matches names by prefix, so it is asked for towns starting like the
        first word ("Step") and the answers are compared letter by letter.
        """
        want = re.sub(r"[^a-z]", "", fold(locality))
        first = re.sub(r"[^a-z]", "", fold(locality).split()[0]) if fold(locality) else ""
        if len(want) < 5 or len(first) < 3:
            return []
        q = first[:4] + (f", {p['region'].upper()}" if p["region"] else "")
        try:
            places = resolve_place(q) or []
        except Exception as e:
            L.warning("resolving %r failed: %s", q, e)
            return []
        limit = 1 if len(want) < 7 else 2
        return [pl for pl in _towns(places)
                if (not p["country"] or pl.get("country") in (None, p["country"]))
                and _typos(re.sub(r"[^a-z]", "", fold(pl.get("name") or "")), want) <= limit][:2]

    def _in_named_town(self, p: dict, alt: dict, describe, near) -> list[dict]:
        """The number on a street of that name anywhere, in a town the gazetteer calls ``locality``.

        For towns the place search didn't offer: "155 B Smith Rd, Bath" is in Bath, New
        Brunswick, but "Bath" alone finds a dozen bigger Baths first.
        """
        rows = self._street_rows("key", alt["key"], None, p["region"])
        if not rows:
            return []
        spots = self._number_spots(rows, p["number"])
        rows = [r for r in rows if r["id"] in spots]
        if near is not None:
            rows.sort(key=lambda r: haversine_km(near[0], near[1], *spots[r["id"]]))
        want, keep = name_key(alt["locality"]), []
        for r in rows[:30]:
            try:
                w = describe(*spots[r["id"]]) or {}
            except Exception as e:
                L.debug("describe failed: %s", e)
                continue
            loc = w.get("locality")
            names = (w.get("place"), loc.get("name") if isinstance(loc, dict) else loc)
            if any(x and name_key(x) == want for x in names):
                r["_fit"], r["_anchor"] = 0.0, None
                keep.append(r)
        return self._evaluate(p, keep, 10.0, near) if keep else []

    def _street_rows(self, col: str, value: str | list[str], cells: list[int] | None, region: str | None,
                     limit: int | None = None) -> list[dict]:
        """Street rows by key or base, in ``cells`` or (None) everywhere.

        Unlimited by default: a LIMIT would keep the lowest cell ids of the index, i.e. only
        the southernmost Main Streets. Callers trim after filtering by number or distance.
        Rows with no region (a name used on both sides of a state line in one cell) match any.
        """
        values = [value] if isinstance(value, str) else list(value)
        where = f"{col} IN ({','.join('?' * len(values))})"
        if cells is None:
            sql = (f"SELECT {_STREET_COLS} FROM streets WHERE {where}"
                   + (" AND (region = ? OR region IS NULL)" if region else "")
                   + (f" LIMIT {int(limit)}" if limit is not None else ""))
            rows = self._all(sql, (*values, region) if region else tuple(values))
        else:
            rows = self._all(f"SELECT {_STREET_COLS} FROM streets WHERE {where} AND cell IN ({','.join(map(str, cells))})",
                             tuple(values))
        out = []
        for sid, key, base, name, cell, lat, lon, reg, pc in rows:
            if region and reg and reg != region:
                continue
            out.append({"id": sid, "key": key, "name": name, "lat": lat / 1e6, "lon": lon / 1e6, "region": reg, "postcode": pc})
        return out

    def _search_alt(self, p: dict, alt: dict, ai: int, anchors: list[_Anchor], near) -> list[dict]:
        key, base = alt["key"], street_base(alt["key"])
        probes: list[tuple[str, str | list[str], float]] = [("key", key, 0.0), ("base", base, 20.0)]
        if (loose := _spelled_out(key)) and loose != base:
            probes.insert(1, ("base", loose, 15.0))
        if variants := _key_variants(alt["street"], key, p["country"]):
            probes.insert(1, ("key", variants, 5.0))
        stages: list[tuple[str, float]] = [("anchor", 1.0), ("wide", 2.5)] if anchors else []
        results: list[dict] = []
        for stage, mult in stages:
            cells = sorted({c for a in anchors for c in cells_around(a.lat, a.lon, min(100.0, a.radius * mult))})
            for col, value, pen in probes:
                rows = []
                for r in self._street_rows(col, value, cells, p["region"]):
                    if value is not key and r["key"] == key:
                        continue  # already looked at by key
                    fit = self._fit(r, anchors, mult)
                    if fit is not None:
                        r["_fit"], r["_anchor"] = fit
                        if value is not key:
                            r["_fit"] += _direction_penalty(key, r["key"])
                        rows.append(r)
                if rows:
                    results += self._evaluate(p, rows, pen + 12.0 * ai + (25.0 if stage == "wide" else 0.0), near)
                if any(r["precision"] in _GOOD for r in results) or (results and p["number"] is None):
                    return results
        # No town, or it didn't resolve: look the street up everywhere (within the state if
        # known). Also when only the device's surroundings were searched and the number wasn't
        # there: "169 Bridger St" typed in Cheyenne may well be the one in Gillette.
        missing = not results or (p["number"] is not None and not any(r["precision"] in _GOOD for r in results))
        if missing and not any(a.kind in ("place", "postcode") for a in anchors):
            for col, value, pen in probes:
                rows = [r for r in self._street_rows(col, value, None, p["region"])
                        if value is key or r["key"] != key]
                for r in rows:
                    r["_fit"] = min(20.0, haversine_km(near[0], near[1], r["lat"], r["lon"]) / 25.0) if near else 0.0
                    r["_anchor"] = None
                    if value is not key:
                        r["_fit"] += _direction_penalty(key, r["key"])
                if rows and p["number"] is not None:
                    # the streets that have the number, however far away: nearest-first would
                    # keep only the 40 closest cells of a long road such as US 26
                    spots = self._number_spots(rows, p["number"])
                    rows = [r for r in rows if r["id"] in spots] or rows
                if rows:
                    results += self._evaluate(p, rows, pen + 25.0 + 12.0 * ai, near)
                    break
        return results

    def _number_spots(self, rows: list[dict], n: int) -> dict[int, tuple[float, float]]:
        """Street row id -> a rough position of number ``n`` on it, for rows that have it.

        Ids are inlined in chunks: a nationwide "main" base can be tens of thousands of rows,
        past what one statement should carry.
        """
        spots: dict[int, tuple[float, float]] = {}
        for i in range(0, len(rows), 5000):
            ids = ",".join(str(r["id"]) for r in rows[i:i + 5000])
            for sid, lat, lon in self._all(f"SELECT sid, lat, lon FROM points WHERE sid IN ({ids}) AND num = ?", (n,)):
                spots.setdefault(sid, (lat / 1e6, lon / 1e6))
            for sid, geom in self._all(f"SELECT sid, geom FROM ranges WHERE sid IN ({ids}) AND lo <= ? AND hi >= ?", (n, n)):
                spots.setdefault(sid, _along(geom, 0.5))
        return spots

    @staticmethod
    def _fit(r: dict, anchors: list[_Anchor], mult: float) -> tuple[float, _Anchor] | None:
        """Penalty for how far a street is from the best anchor, or None if it's outside all of them."""
        best = None
        for a in anchors:
            d = haversine_km(a.lat, a.lon, r["lat"], r["lon"])
            reach = a.radius * mult
            if d > reach + 8.0:  # street rows sit anywhere in their 0.1 degree cell
                continue
            pen = 12.0 * min(d / a.radius, 2.5) + 6.0 * a.rank - (8.0 if a.kind == "postcode" and d <= a.radius else 0.0)
            if best is None or pen < best[0]:
                best = (pen, a)
        return best

    def _evaluate(self, p: dict, rows: list[dict], penalty: float, near) -> list[dict]:
        rows.sort(key=lambda r: r["_fit"])
        rows = rows[:40]
        n = p["number"]
        found: dict[int, tuple] = {}  # sid -> (precision, lat, lon, numtext, unit, postcode, source, extra penalty)
        if n is not None:
            ids = ",".join(str(r["id"]) for r in rows)
            want_nt, want_unit = (p["numtext"] or "").upper(), (p["unit"] or "").upper()
            best_rank: dict[int, int] = {}
            for sid, _num, nt, unit, lat, lon, pc, src in self._all(
                    f"SELECT sid, num, numtext, unit, lat, lon, postcode, source FROM points WHERE sid IN ({ids}) AND num = ?", (n,)):
                u = (unit or "").upper()
                rank = (3 if nt.upper() != want_nt else 0) + (0 if u == want_unit else 1 if not u else 2)
                if sid not in best_rank or rank < best_rank[sid]:
                    best_rank[sid] = rank
                    found[sid] = ("exact", lat / 1e6, lon / 1e6, nt, unit if u == want_unit and u else None, pc, src,
                                  5.0 if rank >= 3 else 0.0)
            spans: dict[int, tuple[bool, int]] = {}
            for sid, lo, hi, parity, rev, pc, geom in self._all(
                    f"SELECT sid, lo, hi, parity, rev, postcode, geom FROM ranges WHERE sid IN ({ids}) AND lo <= ? AND hi >= ?", (n, n)):
                if sid in best_rank or (parity == 1 and n % 2 == 0) or (parity == 2 and n % 2 == 1):
                    continue
                # the narrowest range wins, but an odd/even one beats one that lists every number:
                # "all" comes from TIGER sides whose endpoints disagree on parity, a data error
                rank = (parity == 0, hi - lo)
                if sid in spans and spans[sid] <= rank:
                    continue
                spans[sid] = rank
                frac = (n - lo) / (hi - lo) if hi > lo else 0.5
                lat, lon = _along(geom, 1.0 - frac if rev else frac)
                found[sid] = ("interpolated", lat, lon, p["numtext"], None, pc, "tiger", 0.0)
            if not found:
                for r in rows[:8]:
                    near_hit = self._nearest_number(r["id"], n)
                    if near_hit:
                        found[r["id"]] = near_hit
        out = []
        for r in rows:
            hit = found.get(r["id"])
            if hit:
                prec, lat, lon, nt, unit, pc, src, extra = hit
                name = f"{nt} {r['name']}" + (f" #{unit}" if unit else "")
            else:
                prec, lat, lon, nt, pc, src, extra = "street", r["lat"], r["lon"], None, None, "streets", 0.0
                name = r["name"]
            pc = pc or r["postcode"]
            score = _PREC[prec] - penalty - r["_fit"] - extra
            if p["postcode"] and pc == p["postcode"]:
                score += 6.0
            if near is not None:
                score -= min(8.0, haversine_km(near[0], near[1], lat, lon) / 50.0)
            a: _Anchor | None = r["_anchor"]
            region = r["region"] or self._postcode_region(pc)
            res = {"name": name, "label": name, "kind": "street" if prec == "street" else "address",
                   "lat": round(lat, 6), "lon": round(lon, 6), "precision": prec, "source": src,
                   "admin1": REGION_NAMES.get(region) if region else (a.admin1 if a else None),
                   "country": region_country(region) or (a.country if a else None) or p["country"],
                   "postcode": format_postcode(pc),
                   "_score": score, "_key": r["key"],
                   "_locality": a.name if a is not None and a.kind == "place" and
                   haversine_km(a.lat, a.lon, lat, lon) <= a.radius * 1.25 else None}
            if near is not None:
                res["distance_km"] = round(haversine_km(near[0], near[1], lat, lon), 2)
            out.append(res)
        return out

    def _nearest_number(self, sid: int, n: int) -> tuple | None:
        """The closest known number on one street row, from exact points and TIGER ranges."""
        cands = []  # (difference, parity differs, numtext, lat, lon, postcode, source)
        for sql in ("SELECT num, numtext, lat, lon, postcode, source FROM points WHERE sid = ? AND num < ? ORDER BY num DESC LIMIT 1",
                    "SELECT num, numtext, lat, lon, postcode, source FROM points WHERE sid = ? AND num > ? ORDER BY num LIMIT 1"):
            for num, nt, lat, lon, pc, src in self._all(sql, (sid, n)):
                cands.append((abs(num - n), (num - n) % 2, nt, lat / 1e6, lon / 1e6, pc, src))
        ranges = self._all("SELECT lo, hi, rev, postcode, geom FROM ranges WHERE sid = ? AND lo <= ? ORDER BY lo DESC LIMIT 6", (sid, n))
        ranges += self._all("SELECT lo, hi, rev, postcode, geom FROM ranges WHERE sid = ? AND lo > ? ORDER BY lo LIMIT 1", (sid, n))
        for lo, hi, rev, pc, geom in ranges:
            if lo <= n <= hi:  # covers n, but only the other side of the street: the neighbour number
                num = n + 1 if n + 1 <= hi else n - 1
            else:
                num = hi if hi < n else lo
            frac = (num - lo) / (hi - lo) if hi > lo else 0.5
            lat, lon = _along(geom, 1.0 - frac if rev else frac)
            cands.append((abs(num - n), (num - n) % 2, str(num), lat, lon, pc, "tiger"))
        if not cands:
            return None
        diff, _, nt, lat, lon, pc, src = min(cands, key=lambda c: (c[0], c[1]))
        return ("nearby", lat, lon, nt, None, pc, src, min(10.0, diff / 20.0))

    @staticmethod
    def _dedupe(results: list[dict]) -> list[dict]:
        """Best first; one result per street and area (a street spans several grid cells)."""
        results.sort(key=lambda r: r["_score"], reverse=True)
        kept: list[dict] = []
        for r in results:
            dup = False
            for k in kept:
                if k["_key"] != r["_key"]:
                    if k["name"].lower() == r["name"].lower() and haversine_km(k["lat"], k["lon"], r["lat"], r["lon"]) < 0.25:
                        dup = True
                        break
                    continue
                d = haversine_km(k["lat"], k["lon"], r["lat"], r["lon"])
                better = k["precision"] in _GOOD and r["precision"] not in _GOOD
                if d < (25.0 if better else 5.0):
                    dup = True
                    break
            if not dup:
                kept.append(r)
        return kept

    @staticmethod
    def _label(results: list[dict], describe) -> None:
        """'123 Main St, Springfield, Illinois 62701': the town comes from the anchor or the gazetteer."""
        cache: dict[tuple, dict] = {}
        for r in results:
            town = r.get("_locality")
            if town is None and describe is not None:
                k = (round(r["lat"], 3), round(r["lon"], 3))
                if k not in cache:
                    try:
                        cache[k] = describe(r["lat"], r["lon"]) or {}
                    except Exception as e:
                        L.debug("describe failed: %s", e)
                        cache[k] = {}
                w = cache[k]
                if w.get("place") and (w.get("distance_km") or 0) <= 25:
                    town = w["place"]
                if not r.get("admin1") and w.get("admin1"):
                    r["admin1"] = w["admin1"]
                if not r.get("country") and w.get("country"):
                    r["country"] = w["country"]
            parts = [r["name"]]
            if town and town != r["name"]:
                parts.append(town)
            if r["kind"] == "postcode":
                tail = r.get("admin1")
            else:
                tail = " ".join(x for x in (r.get("admin1"), r.get("postcode")) if x)
            if tail:
                parts.append(tail)
            r["label"] = ", ".join(parts)
