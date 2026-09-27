"""Offline "where am I?", "what's near me?" and place search.

Reads the two SQLite databases built by ``scripts/build_geodata.py``:

* ``places.sqlite``: the GeoNames gazetteer for the US and Canada
  (towns, parks, lakes, peaks, historic sites and more).
  Place data (c) GeoNames (CC BY 4.0)
* ``geowiki.sqlite``: coordinates of English Wikipedia articles, worldwide.
  Wikipedia geotags, CC BY-SA 4.0

Only the standard library is used. Both files are opened read-only. If one is
missing, its results are simply empty, and ``places_available`` /
``wiki_available`` report what is there. A rebuilt database that could not
replace the one in use (it is left as ``<name>.new``) is moved into place when
the directory is next opened. Close any old GeoData first when reloading.

Conventions
-----------
* Distances are great-circle distances (haversine, mean Earth radius).
* In :meth:`GeoData.nearby`, ``bearing_deg`` and ``direction`` point FROM the
  query point TO the result ("the museum is 2 km NE of you").
* In :meth:`GeoData.where_am_i` they point FROM the named place TO the query
  point ("you are 5.2 km NE of Springfield"), matching ``description``.
* Every call does an R-tree bounding-box prefilter first, then exact distances
  in Python. Measured on the target handheld: ``where_am_i`` takes 0.4-6 ms,
  ``search_places`` 1-36 ms, and ``nearby`` (16 km) 3-25 ms. The worst case is
  Manhattan with a ``kinds`` filter, at about 40-50 ms.
"""

from __future__ import annotations

import math
import os
import re
import sqlite3
import threading
import unicodedata
from pathlib import Path
from typing import Iterable, Sequence

__all__ = [
    "GeoData",
    "KINDS",
    "KM_PER_MILE",
    "haversine_km",
    "initial_bearing_deg",
    "compass_point",
    "bounding_boxes",
    "name_key",
]

EARTH_RADIUS_KM = 6371.0088
KM_PER_MILE = 1.609344
KM_PER_DEG_LAT = 111.195  # = EARTH_RADIUS_KM * pi / 180

KINDS = ("nature", "history", "culture", "towns", "water", "mountains", "all")

COUNTRY_NAMES = {"US": "United States", "CA": "Canada"}

# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing from point 1 to point 2, degrees clockwise from north (0-360)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


_COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def compass_point(bearing_deg: float) -> str:
    """8-point compass direction for a bearing ('N', 'NE', ... 'NW')."""
    return _COMPASS[int(((bearing_deg % 360.0) + 22.5) // 45.0) % 8]


def bounding_boxes(lat: float, lon: float, radius_km: float) -> list[tuple[float, float, float, float]]:
    """(minlat, maxlat, minlon, maxlon) boxes covering a circle.

    Returns two boxes when the circle crosses the antimeridian (e.g. the
    Aleutians), and a full-longitude box when it reaches a pole.
    """
    dlat = radius_km / KM_PER_DEG_LAT
    minlat, maxlat = lat - dlat, lat + dlat
    if minlat <= -90.0 or maxlat >= 90.0:
        return [(max(minlat, -90.0), min(maxlat, 90.0), -180.0, 180.0)]
    # widest longitude span of the circle is at the latitude nearest a pole
    coslat = math.cos(math.radians(max(abs(minlat), abs(maxlat))))
    dlon = radius_km / (KM_PER_DEG_LAT * max(coslat, 1e-6))
    if dlon >= 180.0:
        return [(minlat, maxlat, -180.0, 180.0)]
    minlon, maxlon = lon - dlon, lon + dlon
    if minlon < -180.0:
        return [(minlat, maxlat, minlon + 360.0, 180.0), (minlat, maxlat, -180.0, maxlon)]
    if maxlon > 180.0:
        return [(minlat, maxlat, minlon, 180.0), (minlat, maxlat, -180.0, maxlon - 360.0)]
    return [(minlat, maxlat, minlon, maxlon)]


def _approx_km(lat: float, lon: float, coslat: float, plat: float, plon: float) -> float:
    """Fast equirectangular distance; accurate to well under 1% within ~100 km."""
    dx = (plon - lon + 540.0) % 360.0 - 180.0
    return KM_PER_DEG_LAT * math.hypot(plat - lat, dx * coslat)


def _town_radius_km(population: int) -> float:
    """Rough built-up radius of a place from its population. It is about 1 km
    for 1,000 people, 2.5 km for 10,000, 15 km for Toronto and 22 km for New
    York. It decides whether you are "in" a place rather than near it."""
    return max(0.8, 0.131 * max(population, 1) ** 0.32)


# ---------------------------------------------------------------------------
# What counts as notable: GeoNames feature codes and Wikipedia coord types
# ---------------------------------------------------------------------------

N, H, C, T, W, M, O = "nature", "history", "culture", "towns", "water", "mountains", "other"


def _cats(*names: str) -> frozenset[str]:
    return frozenset(names)


# fcode -> (base weight 0..100, categories). Codes that are not listed get
# weight 5 in the 'other' category. Admin areas (class A) and undersea
# features (class U) are never "nearby" results.
_GEONAMES_KINDS: dict[str, tuple[int, frozenset[str]]] = {}


def _reg(weight: int, cats: frozenset[str], *codes: str) -> None:
    for code in codes:
        _GEONAMES_KINDS[code] = (weight, cats)


# populated places (population raises the weight, see _geonames_weight)
_reg(95, _cats(T), "PPLC")
_reg(80, _cats(T), "PPLA", "PPLG")
_reg(55, _cats(T), "PPLA2")
_reg(45, _cats(T), "PPLA3")
_reg(40, _cats(T), "PPLA4", "PPLA5")
_reg(25, _cats(T), "PPL", "PPLS", "STLMT")
_reg(20, _cats(T), "PPLX")
_reg(15, _cats(T), "PPLF", "PPLR", "PPLL")
_reg(35, _cats(T, H), "PPLH", "PPLQ", "PPLW", "PPLCH")
# parks and protected land
_reg(55, _cats(N), "RESN")
_reg(50, _cats(N), "RESW")
_reg(45, _cats(N), "PRK", "RES", "RESF", "FRST", "RESH")
_reg(40, _cats(N, C), "RESV")
_reg(50, _cats(N, C), "GDN")
_reg(50, _cats(C), "AMUS")
_reg(35, _cats(N), "TRL", "HUT", "HUTS")
_reg(20, _cats(N), "CMP")
# landforms and mountains
_reg(65, _cats(M, N), "VLC")
_reg(55, _cats(M, N), "PK", "CLDA")
_reg(50, _cats(M, N), "MTS", "PKS", "CRTR")
_reg(45, _cats(M, N), "MT", "PASS", "BUTE")
_reg(40, _cats(M, N), "MESA", "CLF", "CRQ")
_reg(25, _cats(M, N), "HLL", "HLLS", "RDGE", "GAP", "SDL")
_reg(15, _cats(M, N), "KNLL", "SPUR")
_reg(55, _cats(N), "CNYN", "CAVE", "ARCH")
_reg(50, _cats(N), "GRGE", "LAVA", "FRSTF")
_reg(40, _cats(N), "DUNE")
_reg(40, _cats(N, W), "BCH")
_reg(30, _cats(N, W), "ISL", "ISLS")
_reg(30, _cats(N, W), "CAPE", "PEN", "HDLD", "PROM")
_reg(25, _cats(N, W), "PT", "SPIT")
_reg(25, _cats(N), "PLAT", "RK")
_reg(20, _cats(N), "VAL", "RKS", "VALS")
_reg(10, _cats(N), "PLN", "DPR", "BAR", "SLP", "UPLD")
# water
_reg(70, _cats(W, N), "FLLS", "GYSR")
_reg(60, _cats(W, N), "SPNT", "FJD")
_reg(55, _cats(W, N, M), "GLCR")
_reg(50, _cats(W, N), "FLLSX")
_reg(60, _cats(W), "OCN")
_reg(55, _cats(W), "SEA")
_reg(50, _cats(W), "GULF")
_reg(40, _cats(W, N), "LKC", "LKN")
_reg(40, _cats(W), "SD", "STRT")
_reg(35, _cats(W, N), "LK", "LKS", "RSV", "LGN", "RPDS", "ESTY", "SPNS")
_reg(35, _cats(W), "BAY", "BAYS", "HBR")
_reg(30, _cats(W, N), "SPNG")
_reg(30, _cats(W), "BGHT")
_reg(30, _cats(W, C), "DAM")
_reg(25, _cats(W, N), "LKO", "LKI")
_reg(25, _cats(W), "COVE", "INLT", "LOCK")
_reg(20, _cats(W, N), "STM", "STMS", "SWMP", "MRSH", "BOG")
_reg(20, _cats(W), "CHN", "CNL", "CHNM")
_reg(15, _cats(W), "PND", "PNDS", "OVF", "STMM", "CRKT", "WEIR", "LBED")
_reg(10, _cats(W), "WLL", "WLLS", "STMB", "STMI", "RSVT")
# history
_reg(70, _cats(H), "CSTL")
_reg(70, _cats(H, C), "PAL")
_reg(65, _cats(H), "HSTS", "BTL", "ANS", "PYR", "PYRS")
_reg(60, _cats(H, C), "MNMT")
_reg(60, _cats(H), "RUIN", "FT")
_reg(55, _cats(H, C), "MSSN", "LTHSE")
_reg(45, _cats(H, W), "WRCK")
_reg(45, _cats(H), "TMB")
_reg(40, _cats(H), "HSEC", "MLWND", "MLWTR")
_reg(30, _cats(H), "GRVE", "MNAU", "MLSG")
_reg(25, _cats(H), "MNQ", "SNTR")
_reg(20, _cats(H), "CMTY", "RSTNQ", "CMPQ")
_reg(15, _cats(H), "MN", "AIRQ", "HSE")
# culture
_reg(65, _cats(C, H), "MUS")
_reg(65, _cats(C, N), "ZOO")
_reg(60, _cats(C), "OPRA", "CTRS")
_reg(50, _cats(C), "THTR", "UNIV", "STDM", "OBS")
_reg(55, _cats(N), "OBPT")
_reg(45, _cats(C, H), "MSTY")
_reg(45, _cats(C), "AMTH")
_reg(35, _cats(C, H), "CVNT", "CTHSE")
_reg(35, _cats(C), "SHRN", "SCHC", "SPA", "CSNO")
_reg(30, _cats(C), "LIBR", "TMPL", "RSRT", "SQR", "RECR", "RLG")
_reg(30, _cats(C, H), "BDG")
_reg(25, _cats(C), "MSQE", "SYG", "TNL", "CTRR")
_reg(20, _cats(C), "MKT")
_reg(15, _cats(C), "MALL", "ATHF")
_reg(12, _cats(C), "CH", "BLDG", "RECG")
_reg(10, _cats(C), "SCH")
_reg(8, _cats(C), "HTL", "REST")
# transport and services
_reg(40, _cats(O), "AIRP")
_reg(30, _cats(O), "HSP", "PRT", "PSTB", "INSM")
_reg(25, _cats(O), "RSTN", "FY", "STNR")
_reg(20, _cats(O), "TOWR")  # mostly radio/TV masts; famous towers come via Wikipedia
_reg(20, _cats(O), "PIER", "WHRF", "PP", "HSPC", "HSPD")
_reg(15, _cats(O), "AIRF", "MAR", "LDNG", "JTY", "RSTP", "LCTY")
_reg(10, _cats(O), "BUSTN", "AREA", "RNCH", "HMSD")
_reg(8, _cats(O), "PO")
_reg(5, _cats(O), "AIRH", "FRM", "GRAZ", "OILF")

_DEFAULT_KIND = (5, _cats(O))
# Upper bound of any item's weight: GeoNames 70 + 35 name boost or 100 for a
# town, Wikipedia 50 + 25 keyword + 35 length; x1.1 when an article merges.
_MAX_WEIGHT = 125.0
_EXCLUDED_CLASSES = {"A", "U"}
_HISTORIC_PPL = {"PPLH", "PPLQ", "PPLW", "PPLCH"}

# Search ranking also wants admin areas: "Kentucky" or "Jefferson County".
_SEARCH_ADMIN_WEIGHT = {"PCLI": 90, "ADM1": 75, "ADM2": 45, "ADM3": 25, "ADM4": 20, "ADMD": 15}
_ADMIN_LABELS = {
    ("PCLI", "US"): "country", ("PCLI", "CA"): "country",
    ("ADM1", "US"): "state", ("ADM1", "CA"): "province or territory",
    ("ADM2", "US"): "county", ("ADM2", "CA"): "census division",
}

# Proximity in place search (see _near_bonus): points for being right here, minus
# a fixed amount per doubling of the distance beyond _NEAR_KM. Towns gain 12 points
# per tenfold population, so a place 10x bigger has to be less than ~4x farther away
# to win: Jackson, WY (10k people, 110 km) beats Jackson, MS (170k, 2,240 km) seen
# from Yellowstone, yet Paris, France still outranks the Parises of Texas and Idaho.
_NEAR_POINTS = 60.0
_NEAR_PER_DOUBLING = 6.0
_NEAR_KM = 25.0

# Name phrases that make a GeoNames feature more notable (substring match on
# the lower-cased name). Each entry is (phrase, bonus, extra categories).
_NAME_BOOSTS: tuple[tuple[str, int, frozenset[str]], ...] = (
    ("national park", 35, _cats(N)),
    ("national monument", 25, _cats(H)),
    ("national historic", 25, _cats(H)),
    ("national historical", 25, _cats(H)),
    ("national memorial", 25, _cats(H)),
    ("national battlefield", 25, _cats(H)),
    ("national military park", 25, _cats(H)),
    ("national seashore", 20, _cats(N, W)),
    ("national lakeshore", 20, _cats(N, W)),
    ("national recreation area", 15, _cats(N)),
    ("national preserve", 15, _cats(N)),
    ("national forest", 10, _cats(N)),
    ("national wildlife refuge", 10, _cats(N)),
    ("state park", 15, _cats(N)),
    ("provincial park", 15, _cats(N)),
    ("state historic", 15, _cats(H)),
    ("wilderness", 8, _cats(N)),
)

# Wikipedia {{coord}} type -> (label, base weight, categories). Weight 0 = never a
# nearby result (whole countries/states/counties are not "near" anything).
_WIKI_TYPES: dict[str | None, tuple[str, int, frozenset[str]]] = {
    "landmark": ("landmark", 45, _cats(C, H)),
    "city": ("city", 45, _cats(T)),
    "town": ("town", 40, _cats(T)),
    "village": ("village", 35, _cats(T)),
    "settlement": ("settlement", 35, _cats(T)),
    "township": ("township", 30, _cats(T)),
    "cdp": ("community", 30, _cats(T)),
    "adm3rd": ("municipality", 35, _cats(T)),
    "mountain": ("mountain", 50, _cats(M, N)),
    "pass": ("mountain pass", 40, _cats(M, N)),
    "landform": ("landform", 35, _cats(N)),
    "valley": ("valley", 25, _cats(N)),
    "waterbody": ("body of water", 40, _cats(W, N)),
    "river": ("river", 35, _cats(W, N)),
    "glacier": ("glacier", 50, _cats(W, M, N)),
    "isle": ("island", 45, _cats(N, W)),
    "island": ("island", 45, _cats(N, W)),
    "forest": ("forest", 45, _cats(N)),
    "park": ("park", 45, _cats(N)),
    "edu": ("school or university", 25, _cats(C)),
    "school": ("school", 20, _cats(C)),
    "railwaystation": ("railway station", 25, _cats(O)),
    "airport": ("airport", 35, _cats(O)),
    "event": ("historic event", 30, _cats(H)),
    "church": ("church", 30, _cats(C, H)),
    "temple": ("temple", 30, _cats(C, H)),
    "building": ("building", 30, _cats(C)),
    "bridge": ("bridge", 30, _cats(C, H)),
    "street": ("street", 15, _cats(C)),
    None: ("place", 35, _cats(O)),
}
_WIKI_SKIP_TYPES = {"country", "state", "adm1st", "adm2nd", "county", "district", "region", "satellite", "camera", "regency"}
_WIKI_REFINE_TYPES = {None, "landmark", "building"}
_WIKI_TOWN_TYPES = {"city", "town", "village", "settlement", "township", "cdp", "adm3rd"}
_WIKI_SEARCH_TYPES = _WIKI_TOWN_TYPES | {
    "country", "adm1st", "adm2nd", "isle", "island", "mountain", "pass", "waterbody", "river", "glacier",
    "forest", "park", "airport",
}  # types whose title keywords refine label/categories

# Title keywords refine Wikipedia articles that lack a specific type:
# word or word pair -> (label, categories, bonus).
_KEYWORDS: dict[str, tuple[str, frozenset[str], int]] = {}


def _kw(label: str, cats: frozenset[str], bonus: int, *words: str) -> None:
    for w in words:
        _KEYWORDS[w] = (label, cats, bonus)


_kw("national park", _cats(N), 25, "national park")
_kw("national monument", _cats(H), 20, "national monument", "national memorial", "national battlefield")
_kw("historic site", _cats(H), 15, "historic site", "historical park", "historical site")
_kw("state park", _cats(N), 10, "state park", "provincial park", "regional park")
_kw("protected area", _cats(N), 5, "national forest", "wildlife refuge", "nature reserve", "nature preserve",
    "wilderness", "national seashore", "national lakeshore", "recreation area")
_kw("museum", _cats(C, H), 10, "museum", "museums")
_kw("zoo or aquarium", _cats(C, N), 10, "zoo", "aquarium")
_kw("battlefield", _cats(H), 20, "battlefield", "battle", "siege")
_kw("fort or castle", _cats(H), 5, "fort", "fortress", "castle", "citadel")
_kw("palace", _cats(H, C), 5, "palace")
_kw("historic site", _cats(H), 5, "ruins", "archaeological site", "pueblo", "mound", "mounds", "historic district")
_kw("monument", _cats(H, C), 5, "monument", "memorial", "statue", "obelisk")
_kw("lighthouse", _cats(H), 5, "lighthouse", "light station")
_kw("waterfall", _cats(W, N), 10, "falls", "waterfall", "cascade", "cascades")
_kw("hot spring", _cats(W, N), 5, "hot springs", "hot spring", "geyser")
_kw("natural feature", _cats(N), 5, "cave", "caves", "caverns", "cavern", "canyon", "gorge", "natural bridge",
    "arch", "dunes", "beach", "glacier", "sinkhole")
_kw("mountain", _cats(M, N), 5, "mount", "mountain", "mountains", "peak", "summit", "butte", "mesa", "volcano", "knob")
_kw("hill", _cats(M, N), 0, "hill", "ridge", "pass")
_kw("body of water", _cats(W, N), 0, "lake", "reservoir", "pond", "lagoon", "bay", "harbor", "harbour", "sound")
_kw("river or stream", _cats(W, N), 0, "river", "creek", "brook", "spring", "springs", "canal")
_kw("island", _cats(N, W), 0, "island", "islands", "isle")
_kw("place of worship", _cats(C, H), 0, "cathedral", "basilica", "church", "chapel", "abbey", "monastery",
    "mission", "temple", "mosque", "synagogue", "shrine")
_kw("venue", _cats(C), 0, "theatre", "theater", "opera house", "arena", "stadium", "ballpark", "coliseum",
    "amphitheatre", "amphitheater", "concert hall")
_kw("garden", _cats(C, N), 0, "botanical garden", "botanical gardens", "garden", "gardens", "arboretum")
_kw("historic building", _cats(H), -5, "house", "mansion", "plantation", "homestead", "cabin", "tavern", "inn",
    "mill", "courthouse", "depot", "farm", "cemetery", "hall")
_kw("education", _cats(C), -5, "university", "college", "library", "observatory", "academy", "school")
_kw("park", _cats(N), 0, "park", "forest", "preserve", "reserve", "trail", "refuge")
_kw("ski area", _cats(N, M), 0, "ski area", "ski resort")
_kw("structure", _cats(C), 0, "bridge", "tower", "dam", "tunnel", "building", "skyscraper")
_kw("railway station", _cats(O), -5, "station")
_EVENT_WORDS = frozenset(("festival", "expo", "convention", "conference", "tournament", "championship", "awards"))
_kw("event", _cats(C), -25, *_EVENT_WORDS)

# Articles that are geotagged but are not places you can visit: broadcast call
# signs ("CJRT-FM"), organisations filed under their headquarters, districts.
_NOT_A_PLACE = re.compile(
    r"^[CKWX][A-Z]{2,3}(-(FM|AM|TV|LP|DT|CD|LD)\b|\s*\((AM|FM|TV)\))"
    r"|\((?:[^()]*\s)?(TV channel|TV station|radio station|radio network|company|newspaper|magazine|band"
    r"|record label|organi[sz]ation|broadcaster|publisher|electoral district|federal electoral district)\)$"
    r"|\b(congressional|electoral|legislative|school) district\b",
    re.IGNORECASE,
)

_kw("structure", _cats(C), 0, "towers", "bridges")
_kw("hospital", _cats(O), -5, "hospital", "clinic")  # "Mount Sinai Hospital" is not a mountain
_kw("business", _cats(O), -15, "hotel", "company", "brewery", "restaurant", "store", "mall", "apartments")
_kw("hill", _cats(M, N), 0, "hills")
_kw("body of water", _cats(W, N), 0, "lakes")
_HEAD_BREAKS = {"of", "at", "in", "on", "for", "to"}

# Generic words that name the feature when they come first ("Lake Louise", "Fort Knox").
_PREFIX_KEYWORDS = {"lake", "mount", "fort", "isle", "cape", "museum", "battle", "siege", "castle", "church",
                    "cathedral", "basilica", "university", "college", "temple", "abbey", "monastery", "palace"}

_WORD_SPLIT = re.compile(r"[^\w']+", re.UNICODE)


def _title_keyword(title: str) -> tuple[str, frozenset[str], int] | None:
    """Guess what an article is about from its title's head noun.

    English place names usually end in the generic word ("Mammoth Cave Baptist
    Church and Cemetery", "Palace Theatre") or start with it ("Lake Louise",
    "Battle of Shiloh", "Little Island at Pier 55"). A keyword anywhere else
    says nothing: "Kips Bay Towers" is not a bay, and "National Park Service"
    is not a park.
    """
    t = _PAREN_SUFFIX.sub("", title)
    if ", " in t:
        t = t.split(", ", 1)[0]
    words = [w for w in (w.strip("'") for w in _WORD_SPLIT.split(t.lower())) if w]
    if not words:
        return None
    if _EVENT_WORDS.intersection(words):  # "Fan Expo Canada": an event held here, not a sight
        return _KEYWORDS["festival"]
    head = words
    for i in range(1, len(words)):
        if words[i] in _HEAD_BREAKS:  # "Museum | of Flight", "Little Island | at Pier 55"
            head = words[:i]
            break
    if len(head) >= 2 and (hit := _KEYWORDS.get(head[-2] + " " + head[-1])):
        return hit
    if hit := _KEYWORDS.get(head[-1]):
        return hit
    if head[0] in _PREFIX_KEYWORDS:
        return _KEYWORDS[head[0]]
    return None


# ---------------------------------------------------------------------------
# Name normalisation (for de-duplication and exact-match ranking)
# ---------------------------------------------------------------------------

_ABBREV = {"st": "saint", "ste": "sainte", "mt": "mount", "ft": "fort", "natl": "national", "hist": "historic"}
_PAREN_SUFFIX = re.compile(r"\s*\([^()]*\)\s*$")


def name_key(name: str) -> str:
    """Loose comparison key: 'Mt. St. Helens' -> 'mount saint helens', "St. John's" -> 'saint johns'."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower().replace("&", " and ")
    s = s.replace("'", "").replace("’", "")
    s = "".join(ch if ch.isalnum() else " " for ch in s)
    words = [_ABBREV.get(w, w) for w in s.split()]
    if len(words) > 1 and words[0] == "the":
        words = words[1:]
    return " ".join(words)


# ---------------------------------------------------------------------------
# Internal result record
# ---------------------------------------------------------------------------


class _Item:
    __slots__ = (
        "name", "kind", "cats", "lat", "lon", "dist", "score", "weight", "source",
        "wiki_path", "population", "admin1", "country", "key", "fclass", "merge_km", "id",
    )

    def as_dict(self, qlat: float, qlon: float) -> dict:
        d = haversine_km(qlat, qlon, self.lat, self.lon)
        b = initial_bearing_deg(qlat, qlon, self.lat, self.lon)
        return {
            "name": self.name,
            "kind": self.kind,
            "categories": sorted(self.cats),
            "lat": self.lat,
            "lon": self.lon,
            "distance_km": round(d, 2),
            "distance_mi": round(d / KM_PER_MILE, 2),
            "bearing_deg": round(b, 1),
            "direction": compass_point(b),
            "source": self.source,
            "wiki_path": self.wiki_path,
            "population": self.population,
            "admin1": self.admin1,
            "country": self.country,
            "score": round(self.score, 1),
        }


def _parse_kinds(kinds: str | Iterable[str] | None) -> frozenset[str] | None:
    """Normalise the ``kinds`` filter. None means everything."""
    if kinds is None:
        return None
    if isinstance(kinds, str):
        kinds = [kinds]
    aliases = {
        "town": T, "city": T, "cities": T, "places": T,
        "mountain": M, "peaks": M, "peak": M,
        "historic": H, "historical": H,
        "parks": N, "park": N, "outdoors": N,
        "lakes": W, "rivers": W, "lake": W, "river": W,
        "museums": C, "museum": C, "cultural": C,
    }
    out = set()
    for k in kinds:
        k = str(k).strip().lower()
        k = aliases.get(k, k)
        if k == "all":
            return None
        if k in KINDS:
            out.add(k)
    return frozenset(out) or None


# ---------------------------------------------------------------------------
# The public API
# ---------------------------------------------------------------------------


class GeoData:
    """Read-only access to ``places.sqlite`` and ``geowiki.sqlite`` in ``maps_dir``.

    Thread-safe (queries are serialised per database). Use as a context manager
    or call :meth:`close` when done.
    """

    PLACES_FILE = "places.sqlite"
    WIKI_FILE = "geowiki.sqlite"

    def __init__(self, maps_dir: Path | str) -> None:
        self.maps_dir = Path(maps_dir)
        self._places = self._open(self.maps_dir / self.PLACES_FILE)
        self._wiki = self._open(self.maps_dir / self.WIKI_FILE)
        self._places_lock = threading.Lock()
        self._wiki_lock = threading.Lock()
        self._admin1_names: dict[tuple[str, str], str] = {}
        self._suffixes: set[str] = {"united states", "usa", "u s", "canada", "d c"}
        if self._places is not None:
            try:
                for cc, code, name in self._places.execute("SELECT country, code, name FROM admin1"):
                    self._admin1_names[(cc, code.upper())] = name
                    self._suffixes.add(name_key(name))
            except sqlite3.Error:
                pass  # older/foreign file without the lookup table: region parsing is disabled
        self._sql_cache: dict[tuple, str] = {}
        self._big: list[tuple] | None = None

    # -- lifecycle ----------------------------------------------------------

    @staticmethod
    def _open(path: Path) -> sqlite3.Connection | None:
        # A rebuild that could not replace a database in use (Windows) leaves it
        # as "<name>.new". Install it now, if the old file is free.
        pending = path.with_name(path.name + ".new")
        if pending.is_file():
            try:
                os.replace(pending, path)
            except OSError:
                pass  # still open elsewhere; keep using the current file
        if not path.is_file():
            return None
        conn = None
        try:
            conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)
            conn.execute("PRAGMA query_only = 1")
            conn.execute("PRAGMA mmap_size = 268435456")  # 256 MB of address space; pages stay OS-cached
            conn.execute("SELECT 1 FROM meta LIMIT 1")  # validates that this is one of our databases
            return conn
        except sqlite3.Error:
            if conn is not None:
                conn.close()
            return None

    @property
    def places_available(self) -> bool:
        return self._places is not None

    @property
    def wiki_available(self) -> bool:
        return self._wiki is not None

    @property
    def available(self) -> bool:
        return self._places is not None or self._wiki is not None

    def __bool__(self) -> bool:  # `if geo:` means "has data to answer with"
        return self.available

    def close(self) -> None:
        for conn in (self._places, self._wiki):
            if conn is not None:
                conn.close()
        self._places = self._wiki = None

    def __enter__(self) -> "GeoData":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def info(self) -> dict:
        """Availability, attribution and build metadata of both databases (for an About page)."""
        out = {}
        for key, conn, lock in (("places", self._places, self._places_lock), ("wiki", self._wiki, self._wiki_lock)):
            if conn is None:
                out[key] = {"available": False}
                continue
            with lock:
                meta = dict(conn.execute("SELECT key, value FROM meta"))
            out[key] = {"available": True, **{k: meta.get(k) for k in ("attribution", "license", "build_date", "row_count", "countries", "dump_date") if k in meta}}
        return out

    # -- nearby ---------------------------------------------------------------

    def nearby(
        self,
        lat: float,
        lon: float,
        radius_km: float = 16,
        kinds: Sequence[str] | str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Notable places within ``radius_km``, the most interesting first.

        Combines GeoNames features (weighted by feature type, name and population)
        with geotagged Wikipedia articles (weighted by type and article length),
        discounted by distance. A GeoNames place and a Wikipedia article with
        the same name close together are merged into one entry that carries
        ``wiki_path``.

        ``kinds`` filters by category: 'nature', 'history', 'culture', 'towns',
        'water', 'mountains' or 'all' (default). Each result has the keys
        ``name, kind, categories, lat, lon, distance_km, distance_mi,
        bearing_deg, direction, source ('geonames'|'wikipedia'), wiki_path,
        population, admin1, country, score``.
        """
        lat, lon = _check_point(lat, lon)
        radius_km = min(max(float(radius_km), 0.05), 250.0)
        limit = max(1, int(limit))
        want = _parse_kinds(kinds)
        scale = max(1.5, radius_km / 4.0)  # distance at which the score halves
        coslat = math.cos(math.radians(lat))

        # Scores fall off with distance and no weight exceeds _MAX_WEIGHT. If the
        # inner half of the circle already yields `limit` results that nothing
        # further out could beat, the outer ring is never read. The answer is
        # the same either way, but dense cities cost about a quarter as much.
        inner = radius_km / 2.0
        if inner >= 1.0:
            top = self._nearby_pass(lat, lon, coslat, inner, want, scale, limit)
            if len(top) >= limit and top[limit - 1].score >= _MAX_WEIGHT / (1.0 + inner / scale):
                return [it.as_dict(lat, lon) for it in top[:limit]]
        top = self._nearby_pass(lat, lon, coslat, radius_km, want, scale, limit)
        return [it.as_dict(lat, lon) for it in top[:limit]]

    def _nearby_pass(self, lat, lon, coslat, radius_km, want, scale, limit) -> list[_Item]:
        """Candidates within ``radius_km``, de-duplicated, best first."""
        boxes = bounding_boxes(lat, lon, radius_km)
        items: list[_Item] = []
        if self._places is not None:
            items += self._nearby_geonames(lat, lon, coslat, radius_km, boxes, want, scale, min_weight=20)
            if len(items) < limit:  # sparse area: let churches, schools & co. in
                items = self._nearby_geonames(lat, lon, coslat, radius_km, boxes, want, scale, min_weight=0)
        if self._wiki is not None:
            items += self._nearby_wiki(lat, lon, coslat, radius_km, boxes, want, scale, cap=600)
        # Only the best-scoring window can reach the output, so only it is de-duplicated
        # (name keys are comparatively expensive). Low-scoring GeoNames twins of
        # articles in the window (a plain 'tower' called "CN Tower") are pulled in
        # so that they can merge.
        items.sort(key=lambda it: it.score, reverse=True)
        n = max(200, 5 * limit)
        window, rest = items[:n], items[n:]
        titles = {_PAREN_SUFFIX.sub("", it.name).lower() for it in window if it.source == "wikipedia"}
        if titles:
            window += [it for it in rest if it.source == "geonames" and it.name.lower() in titles]
        for it in window:
            it.key = name_key(it.name) if it.source == "geonames" else self._wiki_key(it.name)
        window = self._dedupe(window)
        window.sort(key=lambda it: it.score, reverse=True)
        return window

    def _codes_sql(self, want: frozenset[str] | None, min_weight: int) -> str:
        key = ("nearby", want, min_weight)
        sql = self._sql_cache.get(key)
        if sql is None:
            codes = sorted(
                code for code, (w, cats) in _GEONAMES_KINDS.items()
                if w >= min_weight and (want is None or cats & want)
            )
            sql = (
                "SELECT p.id, p.name, p.lat, p.lon, p.fclass, p.fcode, p.fdesc, p.population, p.admin1, p.country "
                "FROM places_rtree r CROSS JOIN places p ON p.id = r.id "
                "WHERE r.minlat >= ? AND r.maxlat <= ? AND r.minlon >= ? AND r.maxlon <= ? "
            )
            if want is None and min_weight <= _DEFAULT_KIND[0]:
                sql += "AND coalesce(p.fclass, '') NOT IN ('A', 'U')"
            else:
                sql += "AND p.fcode IN (" + ",".join(f"'{c}'" for c in codes) + ")"
            self._sql_cache[key] = sql
        return sql

    def _nearby_geonames(self, lat, lon, coslat, radius_km, boxes, want, scale, min_weight) -> list[_Item]:
        sql = self._codes_sql(want, min_weight)
        rows: list[tuple] = []
        with self._places_lock:
            for box in boxes:
                rows += self._places.execute(sql, box).fetchall()
        out = []
        for gid, name, plat, plon, fclass, fcode, fdesc, pop, adm1, cc in rows:
            d = _approx_km(lat, lon, coslat, plat, plon)
            if d > radius_km:
                continue
            weight, cats = _GEONAMES_KINDS.get(fcode, _DEFAULT_KIND)
            if fclass in _EXCLUDED_CLASSES:
                continue
            pop = pop or 0
            kind = fdesc or "place"
            if fclass == "P":
                weight, kind = _geonames_town(fcode, pop, weight, kind, cc)
                if want is None and d < _town_radius_km(pop):
                    weight *= 0.35  # the town you are standing in is not a "nearby" sight
            else:
                weight, extra = _name_boost(name, weight)
                if extra:
                    cats = cats | extra
            if want is not None and not (cats & want):
                continue
            it = _Item()
            it.id, it.name, it.kind, it.cats = gid, name, kind, cats
            it.lat, it.lon, it.dist, it.weight = plat, plon, d, weight
            it.score = weight / (1.0 + d / scale)
            it.source, it.wiki_path = "geonames", None
            it.population, it.admin1, it.country, it.fclass = pop, adm1, cc, fclass
            it.key = None
            it.merge_km = (20.0 if pop >= 100_000 else 8.0) if fclass == "P" else (10.0 if fclass in ("L", "T", "H", "V") else 2.5)
            out.append(it)
        return out

    def _nearby_wiki(self, lat, lon, coslat, radius_km, boxes, want, scale, cap) -> list[_Item]:
        # Dense areas (Manhattan has ~15k geotagged articles within 16 km) are
        # pre-ranked inside SQLite by length x proximity, so Python only sees
        # the best `cap` rows.
        kx = (KM_PER_DEG_LAT * coslat) ** 2 / scale ** 2
        ky = KM_PER_DEG_LAT ** 2 / scale ** 2
        sql = (
            "SELECT g.title, g.path, g.lat, g.lon, g.type, g.page_len, g.country, g.dim "
            "FROM geo_rtree r CROSS JOIN geo g ON g.page_id = r.id "
            "WHERE r.minlat >= ? AND r.maxlat <= ? AND r.minlon >= ? AND r.maxlon <= ? "
            "ORDER BY (min(coalesce(g.page_len, 0), 80000) + 4000.0) "
            "/ (1.0 + (g.lat - ?) * (g.lat - ?) * ? + (g.lon - ?) * (g.lon - ?) * ?) DESC LIMIT ?"
        )
        rows: list[tuple] = []
        with self._wiki_lock:
            for box in boxes:
                rows += self._wiki.execute(sql, (*box, lat, lat, ky, lon, lon, kx, cap)).fetchall()
        out = []
        for title, path, plat, plon, gtype, plen, cc, dim in rows:
            if gtype in _WIKI_SKIP_TYPES or (gtype in _WIKI_TOWN_TYPES and (dim or 0) >= 30_000):
                continue  # whole countries, states, counties, metro areas ("Greater Toronto Area")
            d = _approx_km(lat, lon, coslat, plat, plon)
            if d > radius_km:
                continue
            if _NOT_A_PLACE.search(title):
                continue
            label, weight, cats = _WIKI_TYPES.get(gtype) or _WIKI_TYPES[None]
            if gtype in _WIKI_TOWN_TYPES and want is None and d < max(2.0, (dim or 10_000) / 2000.0):
                weight *= 0.35  # the town you are standing in is not a "nearby" sight
            if gtype in _WIKI_REFINE_TYPES:
                hit = _title_keyword(title)
                if hit is not None:
                    label, cats, bonus = hit
                    weight += bonus
            elif gtype == "event" and (hit := _title_keyword(title)) and hit[0] == "battlefield":
                label, weight = "battlefield", weight + hit[2]
            if want is not None and not (cats & want):
                continue
            weight += _length_bonus(plen)
            it = _Item()
            it.id, it.name, it.kind, it.cats = None, title, label, cats
            it.lat, it.lon, it.dist, it.weight = plat, plon, d, weight
            it.score = weight / (1.0 + d / scale)
            it.source, it.wiki_path = "wikipedia", path
            it.population, it.admin1, it.country, it.fclass = None, None, cc, None
            it.key = None
            it.merge_km = 0.0
            out.append(it)
        return out

    def _wiki_key(self, title: str) -> str:
        """Comparison key for an article title: drop '(disambiguation)' and ', State' suffixes."""
        t = _PAREN_SUFFIX.sub("", title)
        if ", " in t:
            head, tail = t.rsplit(", ", 1)
            if name_key(tail) in self._suffixes:
                t = head
        return name_key(t)

    @staticmethod
    def _dedupe(items: list[_Item]) -> list[_Item]:
        """Merge near-identical names that lie close together.

        GeoNames duplicates keep the higher-scoring feature. A Wikipedia
        article that matches a GeoNames place gives it ``wiki_path`` and the
        article's notability (the better of the two scores, plus 10%).
        """
        by_key: dict[str, list[_Item]] = {}
        for it in items:
            by_key.setdefault(it.key, []).append(it)
        out: list[_Item] = []
        for group in by_key.values():
            if len(group) == 1:
                out.extend(group)
                continue
            geo = sorted((g for g in group if g.source == "geonames"), key=lambda g: g.score, reverse=True)
            wiki = sorted((g for g in group if g.source == "wikipedia"), key=lambda g: g.score, reverse=True)
            kept: list[_Item] = []
            for g in geo:
                twin = next((k for k in kept if haversine_km(g.lat, g.lon, k.lat, k.lon) <= max(g.merge_km, k.merge_km)), None)
                if twin is None:
                    kept.append(g)
            for w in wiki:
                host = None
                best = float("inf")
                for g in kept:
                    if g.wiki_path is None:
                        dd = haversine_km(w.lat, w.lon, g.lat, g.lon)
                        if dd <= g.merge_km and dd < best:
                            host, best = g, dd
                if host is None:
                    out.append(w)
                else:
                    host.wiki_path = w.wiki_path
                    host.cats = host.cats | (w.cats - {O})
                    host.score = max(host.score, w.score) * 1.1
            out.extend(kept)
        return out

    # -- where am I -------------------------------------------------------------

    def where_am_i(self, lat: float, lon: float) -> dict:
        """Describe a position relative to the nearest town or city.

        Returns ``{place, admin1, country, lat, lon, fcode, kind, population,
        distance_km, distance_mi, bearing_deg, direction, description,
        description_mi, locality, nearest_city, source}``. ``locality`` is a
        closer named neighbourhood or hamlet, and ``nearest_city`` a bigger
        reference city; either may be None. Returns {} when nothing is known
        nearby (for example, no databases).

        Choice of ``place``: if the point lies within the rough built-up radius
        of a town or city, that place is used. Neighbourhoods (feature code
        PPLX, or small places inside a larger city of the same state or
        province) are reported as ``locality`` instead. Otherwise it is the
        nearest populated place with a known population, falling back to any
        populated place. Outside the US and Canada (no GeoNames place within
        50 km, but a Wikipedia town much closer), Wikipedia city/town articles
        are used instead, without ``admin1``.
        """
        lat, lon = _check_point(lat, lon)
        res = self._where_geonames(lat, lon) if self._places is not None else {}
        if self._wiki is not None and (not res or res["distance_km"] > 50.0):
            alt = self._where_wiki(lat, lon)
            if alt and (not res or alt["distance_km"] < res["distance_km"] / 2):
                return alt
        return res

    _P_SQL = (
        "SELECT p.id, p.name, p.lat, p.lon, p.fcode, p.population, p.admin1, p.country "
        "FROM places_rtree r CROSS JOIN places p ON p.id = r.id "
        "WHERE r.minlat >= ? AND r.maxlat <= ? AND r.minlon >= ? AND r.maxlon <= ? AND p.fclass = 'P'"
    )
    def _big_cities(self) -> list[tuple]:
        """Populated places with >= 50,000 people (~1,100 rows), cached on first use.
        A city's built-up radius can reach well beyond the local search box."""
        if self._big is None:
            with self._places_lock:
                self._big = self._places.execute(
                    "SELECT id, name, lat, lon, fcode, population, admin1, country FROM places "
                    "WHERE fclass = 'P' AND population >= 50000"
                ).fetchall()
        return self._big

    def _where_geonames(self, lat: float, lon: float) -> dict:
        def usable(r: tuple, within: float) -> bool:  # a possible primary answer within `within` km
            return bool(r[5]) and r[4] != "PPLX" and r[4] not in _HISTORIC_PPL and \
                haversine_km(lat, lon, r[2], r[3]) <= within

        big = self._big_cities()
        rows: dict[int, tuple] = {}
        with self._places_lock:
            local = []
            for box in bounding_boxes(lat, lon, 12.0):
                local += self._places.execute(self._P_SQL, box).fetchall()
            found = any(usable(r, 12.0) for r in local)
            # sparse areas: widen until a place with a known population turns up
            for radius in (40.0, 120.0, 400.0):
                if found:
                    break
                for box in bounding_boxes(lat, lon, radius):
                    wider = self._places.execute(self._P_SQL + " AND p.population > 0", box).fetchall()
                    local += wider
                    found = found or any(usable(r, radius) for r in wider)
            if not local:  # nothing with a population: take any populated place
                for box in bounding_boxes(lat, lon, 400.0):
                    local += self._places.execute(self._P_SQL, box).fetchall()
        for r in local:
            rows[r[0]] = r
        coslat = math.cos(math.radians(lat))
        for r in big:  # cities whose built-up radius may reach this point
            if _approx_km(lat, lon, coslat, r[2], r[3]) <= 100.0:
                rows[r[0]] = r
        if not rows:
            return {}

        # (dist, radius, row) for every usable populated place
        cands = []
        for r in rows.values():
            if r[4] in _HISTORIC_PPL:
                continue
            d = haversine_km(lat, lon, r[2], r[3])
            cands.append((d, _town_radius_km(r[5] or 0), r))
        if not cands:
            return {}
        cands.sort(key=lambda c: c[0])
        # PPLX (sections of a city) and population-less points are never the primary answer
        primary = [c for c in cands if c[2][5] and c[2][4] != "PPLX"]
        absorbers = [c for c in primary if c[2][5] >= 20_000]

        def absorbed(c) -> bool:
            _, _, s = c
            for _, rc, big in absorbers:
                if big[0] != s[0] and big[5] >= 3 * s[5] and big[6] == s[6] and \
                        haversine_km(s[2], s[3], big[2], big[3]) <= 0.9 * rc:
                    return True
            return False

        place = None
        for c in sorted((c for c in primary if c[0] <= c[1]), key=lambda c: c[0] / c[1]):
            if not absorbed(c):
                place = c
                break
        inside = place is not None
        if place is None:
            place = next((c for c in primary if not absorbed(c)), None) or (primary[0] if primary else cands[0])

        d, radius, row = place
        res = self._describe(lat, lon, row, d, inside and (d < 1.0 or d < 0.5 * radius))

        # a closer named locality (neighbourhood / hamlet)
        loc = next((c for c in cands if c[2][0] != row[0] and c[0] < min(d, 5.0)), None)
        res["locality"] = self._brief(lat, lon, loc[2], loc[0]) if loc else None
        # a bigger reference city, if the answer is a small place
        city = None
        for c in sorted((c for c in primary if c[2][5] >= 10_000 and c[2][0] != row[0]), key=lambda c: c[0] / c[1]):
            if c[2][5] > (row[5] or 0) and not absorbed(c):
                city = c
                break
        res["nearest_city"] = self._brief(lat, lon, city[2], city[0]) if city and not inside else None
        return res

    def _describe(self, lat: float, lon: float, row: tuple, d: float, inside: bool) -> dict:
        gid, name, plat, plon, fcode, pop, adm1, cc = row
        b = initial_bearing_deg(plat, plon, lat, lon)  # from the place to the user
        direction = compass_point(b)
        region = adm1 or COUNTRY_NAMES.get(cc, cc or "")
        where = f"{name}, {region}" if region else name
        if inside:
            desc = desc_mi = f"In {where}"
        else:
            desc = f"{d:.1f} km {direction} of {where}"
            desc_mi = f"{d / KM_PER_MILE:.1f} mi {direction} of {where}"
        return {
            "place": name,
            "admin1": adm1,
            "country": cc,
            "lat": plat,
            "lon": plon,
            "fcode": fcode,
            "kind": _geonames_town(fcode, pop or 0, 0, "populated place", cc)[1],
            "population": pop or 0,
            "distance_km": round(d, 1),
            "distance_mi": round(d / KM_PER_MILE, 1),
            "bearing_deg": round(b, 1),
            "direction": direction,
            "description": desc,
            "description_mi": desc_mi,
            "source": "geonames",
        }

    @staticmethod
    def _brief(lat: float, lon: float, row: tuple, d: float) -> dict:
        b = initial_bearing_deg(row[2], row[3], lat, lon)
        return {
            "name": row[1], "admin1": row[6], "country": row[7], "population": row[5] or 0,
            "distance_km": round(d, 1), "distance_mi": round(d / KM_PER_MILE, 1), "direction": compass_point(b),
        }

    def _where_wiki(self, lat: float, lon: float) -> dict:
        """Fallback outside GeoNames coverage: Wikipedia city/town articles.

        Wikipedia has no populations, so article length stands in for size
        (Paris: 230 kB, an arrondissement: 27 kB). Each place gets a rough radius
        from it, and the place with the smallest distance relative to that
        radius wins, as in the GeoNames logic.
        """
        sql = (
            "SELECT g.title, g.lat, g.lon, g.country, g.page_len, g.dim "
            "FROM geo_rtree r CROSS JOIN geo g ON g.page_id = r.id "
            "WHERE r.minlat >= ? AND r.maxlat <= ? AND r.minlon >= ? AND r.maxlon <= ? "
            "AND g.type IN ('city', 'town', 'village', 'adm3rd', 'settlement')"
        )
        rows: list[tuple] = []
        for radius in (30.0, 100.0, 300.0):
            with self._wiki_lock:
                for box in bounding_boxes(lat, lon, radius):
                    rows += self._wiki.execute(sql, box).fetchall()
            if rows:
                break
        cands = []
        for title, plat, plon, cc, plen, dim in rows:
            if (dim or 0) >= 30_000:  # metro areas, not towns
                continue
            d = haversine_km(lat, lon, plat, plon)
            cands.append((d / min(25.0, max(1.0, 1.5 * ((plen or 0) / 10000.0) ** 0.7)), d, title, plat, plon, cc))
        if not cands:
            return {}
        _, d, title, plat, plon, cc = min(cands)
        b = initial_bearing_deg(plat, plon, lat, lon)
        direction = compass_point(b)
        closer = min((c for c in cands if c[1] < min(d, 5.0) and c[2] != title), key=lambda c: c[1], default=None)
        return {
            "place": title, "admin1": None, "country": cc, "lat": plat, "lon": plon, "fcode": None,
            "kind": "city or town", "population": None,
            "distance_km": round(d, 1), "distance_mi": round(d / KM_PER_MILE, 1),
            "bearing_deg": round(b, 1), "direction": direction,
            "description": f"{d:.1f} km {direction} of {title}",
            "description_mi": f"{d / KM_PER_MILE:.1f} mi {direction} of {title}",
            "locality": None if closer is None else {
                "name": closer[2], "admin1": None, "country": closer[5], "population": None,
                "distance_km": round(closer[1], 1), "distance_mi": round(closer[1] / KM_PER_MILE, 1),
                "direction": compass_point(initial_bearing_deg(closer[3], closer[4], lat, lon)),
            },
            "nearest_city": None,
            "source": "wikipedia",
        }

    # -- search -------------------------------------------------------------

    def search_places(self, query: str, limit: int = 10, near: tuple[float, float] | None = None) -> list[dict]:
        """Find places by name (prefix matching), e.g. for a "set my location" box.

        Accepts "Springfield", "springf", "Springfield, IL", "Lake Louise, Alberta"
        or "toronto on". Ranking combines feature importance and population,
        exact-name matches and, if ``near=(lat, lon)`` is given, proximity on a log
        scale (:func:`_near_bonus`), so a sizeable place nearby beats a big namesake
        far away. Geotagged Wikipedia articles fill in places outside the US and Canada
        (for example "Paris"). Each result has the keys ``name, label, kind,
        fcode, lat, lon, admin1, country, population, source, wiki_path,
        distance_km`` (the last only when ``near`` is given).
        """
        limit = max(1, int(limit))
        if near is not None:
            near = _check_point(*near)
        query = (query or "").strip()
        name_part, region, guessed = self._split_region(query)
        if not guessed:
            results = self._search(name_part, region, near)
        else:
            # "toronto on" = Toronto, Ontario, but "mammoth ca" is more likely Mammoth
            # Cave than Mammoth, California: try both readings, favour the regional one.
            best: dict[tuple, dict] = {}
            for r in self._search(query, None, near):
                best[(r["source"], r["name"], r["lat"], r["lon"])] = r
            for r in self._search(name_part, region, near):
                r["_score"] += 15.0
                k = (r["source"], r["name"], r["lat"], r["lon"])
                if k not in best or best[k]["_score"] < r["_score"]:
                    best[k] = r
            results = list(best.values())
        results.sort(key=lambda r: r["_score"], reverse=True)
        out = []
        for r in results[:limit]:
            for private in ("_score", "_key", "_merge_km"):
                r.pop(private, None)
            out.append(r)
        return out

    def _search(self, name_part: str, region, near) -> list[dict]:
        tokens = _fts_tokens(name_part)
        if not tokens or (len(tokens) == 1 and len(tokens[0]) < 2):
            return []
        match = " AND ".join(_fts_term(t) for t in tokens)
        qkey = name_key(name_part)
        results: list[dict] = []
        if self._places is not None:
            results += self._search_geonames(match, qkey, region, near)
        if self._wiki is not None:
            # with a state/province filter, articles only lend their wiki_path to matches
            attach_only = region is not None and region[0] is not None
            results += self._search_wiki(match, qkey, tokens, near, results, attach_only)
        return results

    def _split_region(self, query: str) -> tuple[str, tuple[str | None, str | None] | None, bool]:
        """'Springfield, IL' -> ('Springfield', ('US', 'Illinois'), False).

        The region is (country, admin1 name). The flag is True when the region
        was guessed from trailing words without a comma ("toronto on").
        """
        q = query.strip()
        if "," in q:
            head, tail = q.rsplit(",", 1)
            reg = self._resolve_region(tail)
            if reg is not None and head.strip():
                return head.strip(), reg, False
            return q.replace(",", " "), None, False
        words = q.split()
        for n in (2, 1):  # trailing "new york" / "on" without a comma
            if len(words) > n:
                reg = self._resolve_region(" ".join(words[-n:]), strict=True)
                if reg is not None:
                    return " ".join(words[:-n]), reg, True
        return q, None, False

    _CA_POSTAL = {
        "AB": "01", "BC": "02", "MB": "03", "NB": "04", "NL": "05", "NS": "07", "ON": "08",
        "PE": "09", "QC": "10", "SK": "11", "YT": "12", "NT": "13", "NU": "14",
    }

    def _resolve_region(self, text: str, strict: bool = False) -> tuple[str | None, str | None] | None:
        t = text.strip()
        if not t or not self._admin1_names:
            return None
        key = name_key(t)
        if key in ("us", "usa", "united states", "u s", "america"):
            return ("US", None) if not strict or key != "us" else None
        if key == "canada":
            return ("CA", None)
        up = t.replace(".", "").upper()
        if len(up) == 2 and up.isalpha():
            if ("US", up) in self._admin1_names:
                return ("US", self._admin1_names[("US", up)])
            if up in self._CA_POSTAL and ("CA", self._CA_POSTAL[up]) in self._admin1_names:
                return ("CA", self._admin1_names[("CA", self._CA_POSTAL[up])])
            return None
        for (cc, _), name in self._admin1_names.items():
            nk = name_key(name)
            if nk == key or (not strict and len(key) >= 3 and nk.startswith(key)):
                return (cc, name)
        return None

    def _search_geonames(self, match, qkey, region, near) -> list[dict]:
        where = "places_fts MATCH ?"
        params: list = [match]
        if region is not None:
            if region[0]:
                where += " AND p.country = ?"
                params.append(region[0])
            if region[1]:
                where += " AND p.admin1 = ?"
                params.append(region[1])
        base = (
            "SELECT p.id, p.name, p.lat, p.lon, p.fclass, p.fcode, p.fdesc, p.country, p.admin1, p.population "
            "FROM places_fts JOIN places p ON p.id = places_fts.rowid WHERE " + where
        )
        rows: dict[int, tuple] = {}
        with self._places_lock:
            for r in self._places.execute(base + " ORDER BY p.population DESC LIMIT 300", params):
                rows[r[0]] = r
            if near is not None:
                k = math.cos(math.radians(near[0])) ** 2
                for r in self._places.execute(
                    base + " ORDER BY (p.lat - ?) * (p.lat - ?) + (p.lon - ?) * (p.lon - ?) * ? LIMIT 100",
                    params + [near[0], near[0], near[1], near[1], k],
                ):
                    rows[r[0]] = r
        out = []
        for gid, name, plat, plon, fclass, fcode, fdesc, cc, adm1, pop in rows.values():
            pop = pop or 0
            if fclass == "A":
                weight = _SEARCH_ADMIN_WEIGHT.get(fcode, 10)
                kind = _ADMIN_LABELS.get((fcode, cc)) or fdesc or "administrative area"
            elif fclass == "P":
                w, _ = _GEONAMES_KINDS.get(fcode, _DEFAULT_KIND)
                weight, kind = _geonames_town(fcode, pop, w, fdesc or "populated place", cc)
                if fcode in _HISTORIC_PPL:
                    weight -= 20
            else:
                weight, _ = _name_boost(name, _GEONAMES_KINDS.get(fcode, _DEFAULT_KIND)[0])
                kind = fdesc or "place"
            key = name_key(name)
            exact = key == qkey
            score = weight + _text_bonus(key, qkey)
            item = {
                "name": name,
                "label": ", ".join(x for x in (name, adm1 if adm1 != name else None, cc) if x),
                "kind": kind,
                "fcode": fcode,
                "lat": plat,
                "lon": plon,
                "admin1": adm1,
                "country": cc,
                "population": pop,
                "source": "geonames",
                "wiki_path": None,
            }
            if near is not None:
                d = haversine_km(near[0], near[1], plat, plon)
                item["distance_km"] = round(d, 1)
                score += _near_bonus(d, exact and fclass in ("P", "A"), weight)
            item["_score"] = score
            item["_key"] = key
            # how far away a Wikipedia article about the same place may put its coordinates
            if fcode in ("ADM1", "PCLI"):
                item["_merge_km"] = 300.0
            elif fcode == "ADM2":
                item["_merge_km"] = 60.0
            else:
                item["_merge_km"] = 30.0 if pop >= 100_000 else 15.0
            out.append(item)
        # the same place listed twice (e.g. a town and its 'area' twin): keep the better one
        out.sort(key=lambda r: r["_score"], reverse=True)
        kept: list[dict] = []
        seen: dict[tuple, list[dict]] = {}
        for r in out:
            group = seen.setdefault((r["_key"], r["admin1"]), [])
            if any(haversine_km(r["lat"], r["lon"], k["lat"], k["lon"]) <= 25.0 for k in group):
                continue
            group.append(r)
            kept.append(r)
        return kept

    def _search_wiki(self, match, qkey, tokens, near, existing: list[dict], attach_only: bool) -> list[dict]:
        sql = (
            "SELECT g.title, g.path, g.lat, g.lon, g.type, g.page_len, g.country, g.dim "
            "FROM geo_fts JOIN geo g ON g.page_id = geo_fts.rowid WHERE geo_fts MATCH ? "
            "ORDER BY g.page_len DESC LIMIT 200"
        )
        with self._wiki_lock:
            rows = self._wiki.execute(sql, (match,)).fetchall()
        by_key: dict[str, list[dict]] = {}
        for e in existing:
            by_key.setdefault(e["_key"], []).append(e)
        out = []
        for title, path, plat, plon, gtype, plen, cc, dim in rows:
            key = self._wiki_key(title)
            # already represented by a GeoNames result? attach the article to it instead
            twin = next((e for e in by_key.get(key, ())
                         if haversine_km(e["lat"], e["lon"], plat, plon) <= e["_merge_km"]), None)
            if twin is not None:
                if twin["wiki_path"] is None:
                    twin["wiki_path"] = path
                continue
            if _NOT_A_PLACE.search(title):
                continue
            exact = key == qkey
            is_place = gtype in _WIKI_SEARCH_TYPES and not (gtype in _WIKI_TOWN_TYPES and (dim or 0) >= 30_000)
            # Places only: "Toronto Police Service" or a congressional district is not
            # somewhere to set as your location. Landmarks etc. must match exactly.
            if attach_only or not (is_place or exact):
                continue
            # An article titled with exactly what was typed is Wikipedia's primary topic
            # for it: famous by construction, even when its coordinates carry no type
            # ("London", "Berlin", "Sydney"), so its length counts as for a place. Not so
            # "The Den" for "den", "Victoria (state)" or "Hamilton, Massachusetts".
            primary = exact and _fts_tokens(title) == tokens
            label, weight, _ = _WIKI_TYPES.get(gtype) or _WIKI_TYPES[None]
            if gtype in ("country", "adm1st"):
                label, weight = ("country" if gtype == "country" else "state or province"), 45
            elif gtype == "adm2nd":
                label, weight = "county or district", 35
            elif gtype not in _WIKI_SEARCH_TYPES and not primary:
                weight = 30
            # a long article about a place of exactly this name ("Paris") outranks small
            # North American namesakes; everything else from Wikipedia ranks below GeoNames.
            # Article length saturates at 64 kB, so being the primary topic is what lifts
            # London or Berlin above a 5,000-person London, Ohio or Berlin, Wisconsin.
            lb = _length_bonus(plen)
            importance = (weight + (1.5 * lb if exact and (is_place or primary) else lb)
                          - (10 if exact else 20) + (10 if primary else 0))
            score = importance + _text_bonus(key, qkey)
            item = {
                "name": title, "label": title if not cc or cc in title else f"{title}, {cc}",
                "kind": label, "fcode": None, "lat": plat, "lon": plon, "admin1": None, "country": cc,
                "population": None, "source": "wikipedia", "wiki_path": path,
            }
            if near is not None:
                d = haversine_km(near[0], near[1], plat, plon)
                item["distance_km"] = round(d, 1)
                score += _near_bonus(d, exact and (is_place or primary), importance)
            item["_score"] = score
            item["_key"] = key
            out.append(item)
        return out

    # -- misc -----------------------------------------------------------------

    def wiki_location(self, path_or_title: str) -> dict | None:
        """Coordinates of a Wikipedia/Kiwix article ('Statue_of_Liberty' or 'Statue of Liberty'), if geotagged."""
        if self._wiki is None or not path_or_title:
            return None
        path = path_or_title.strip().replace(" ", "_")
        path = path[:1].upper() + path[1:]
        with self._wiki_lock:
            r = self._wiki.execute(
                "SELECT title, path, lat, lon, type, dim, country, region FROM geo WHERE path = ?", (path,)
            ).fetchone()
        if r is None:
            return None
        return dict(zip(("title", "path", "lat", "lon", "type", "dim", "country", "region"), r))


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _check_point(lat, lon) -> tuple[float, float]:
    """Validate a coordinate pair; longitudes outside +-180 are wrapped."""
    lat, lon = float(lat), float(lon)
    if not (math.isfinite(lat) and math.isfinite(lon)) or not (-90.0 <= lat <= 90.0):
        raise ValueError(f"invalid coordinates: {lat}, {lon}")
    if not -180.0 <= lon <= 180.0:
        lon = (lon + 180.0) % 360.0 - 180.0
    return lat, lon


def _geonames_town(fcode: str | None, pop: int, weight: int, kind: str, cc: str | None) -> tuple[int, str]:
    """Weight and human label for a populated place."""
    if pop > 0:
        weight = max(weight, int(20 + 12 * math.log10(pop + 1)))
        if fcode == "PPLX":  # neighbourhoods are context, not destinations
            weight = min(weight, 30)
    if fcode == "PPLC":
        kind = "national capital"
    elif fcode == "PPLA":
        kind = "state capital" if cc == "US" else "provincial capital"
    elif fcode in _HISTORIC_PPL:
        kind = "historical settlement" if fcode != "PPLQ" else "abandoned settlement (ghost town)"
    elif fcode == "PPLX":
        kind = "neighbourhood"
    elif pop >= 100_000:
        kind = "city"
    elif pop >= 1_000:
        kind = "town"
    elif pop > 0:
        kind = "village"
    return min(weight, 100), kind


_BOOST_HINTS = ("national", "state ", "provincial", "wilderness")


def _name_boost(name: str, weight: int) -> tuple[int, frozenset[str] | None]:
    """Apply the first matching _NAME_BOOSTS phrase ('... National Park' etc.)."""
    lname = name.lower()
    if not any(h in lname for h in _BOOST_HINTS):  # cheap pre-check; most names match nothing
        return weight, None
    for phrase, bonus, extra in _NAME_BOOSTS:
        if phrase in lname:
            return weight + bonus, extra
    return weight, None


def _length_bonus(page_len: int | None) -> float:
    """Article length as a notability signal: 4 kB -> 0, 16 kB -> +20, >=64 kB -> +35."""
    return max(-10.0, min(35.0, 10.0 * math.log2(max(page_len or 0, 500) / 4000.0)))


def _near_bonus(d_km: float, full: bool, importance: float) -> float:
    """Search bonus for a result ``d_km`` from the user: 60 here, 46 at 100 km, 22 at
    2,000 km, 10 at 8,000 km.

    Log-scaled rather than a cutoff, so it still tells a namesake one state over
    from one across the continent or an ocean. ``full`` (an exact name of a town or
    admin area) gets all of it: "Jackson" means the nearest Jackson. Anything else,
    partial names and exact-name features such as canyons, hills and landmarks, only
    gets a share in proportion to the result's ``importance`` (its score before text
    and distance, about 0-100): around any point the nearest of the many prefix
    matches for "Den" are creeks, parks and hamlets rather than the city being typed,
    and an unpeopled "Grand Canyon" in Missouri must not outrank the national park.
    "Richmond" near Toronto still finds Richmond Hill (185,000 people) and "Mammoth"
    near Memphis still finds Mammoth Cave.
    """
    bonus = max(0.0, _NEAR_POINTS - _NEAR_PER_DOUBLING * math.log2(1.0 + d_km / _NEAR_KM))
    return bonus if full else bonus * min(1.0, max(0.0, importance) / 100.0)


def _text_bonus(key: str, qkey: str) -> float:
    if not qkey:
        return 0.0
    if key == qkey:
        return 30.0
    if key.startswith(qkey):
        return 12.0
    return 0.0


_ABBREV_SHORT = {v: k for k, v in _ABBREV.items()}


_POSSESSIVE = re.compile(r"(\w{3,})['’]s\b")


def _fts_term(t: str) -> str:
    """One query word as an FTS5 expression.

    Every word is a prefix ("spring" "fi" -> Springfield) and single letters must match
    whole words. The index splits "St. John's" into "st" "john" "s", so "saint" also
    matches "st" (and back), and "johns" also matches "john's".
    """
    alts = [f'"{t}"*' if len(t) >= 2 else f'"{t}"']
    for other in (_ABBREV.get(t), _ABBREV_SHORT.get(t)):
        if other:
            alts.append(f'"{other}"')
    if len(t) >= 4 and t.endswith("s") and not t.endswith("ss"):
        alts.append(f'"{t[:-1]} s"')
    return alts[0] if len(alts) == 1 else "(" + " OR ".join(alts) + ")"


def _fts_tokens(text: str) -> list[str]:
    """Split user input into FTS5-safe tokens (letters/digits only).

    A possessive is kept as one word ("john's" -> "johns"), which :func:`_fts_term`
    matches against both "Saint Johns" and the index's "john" "s"; a lone "s" would
    have to be a whole word and miss the spelling without an apostrophe.
    """
    s = _POSSESSIVE.sub(r"\1s", text)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    return "".join(ch if ch.isalnum() else " " for ch in s).split()
