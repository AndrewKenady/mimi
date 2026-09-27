"""Tests for mimi.address: the address parser, and the search engine on a tiny index
built here to the schema scripts/build_addresses.py writes."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[1]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from mimi.address import (  # noqa: E402
    AddressIndex, _key_variants, _spelled_out, _typos, cell_of, cells_around, encode_polyline, looks_like_address,
    parse_address,
)
from mimi.address_norm import STATES, VERSION, street_base, street_key  # noqa: E402
from mimi.geodata import haversine_km, name_key  # noqa: E402
from mimi.routing import decode_polyline6  # noqa: E402

# --------------------------------------------------------------------------- parser

P = [
    # input, expected fields (anything not listed is not checked)
    ("123 Main St", dict(number=123, numtext="123", unit=None, key="main st", locality=None, region=None, postcode=None)),
    ("123 Main St, Springfield", dict(number=123, key="main st", locality="Springfield", region=None)),
    ("123 Main St, Springfield, IL", dict(number=123, key="main st", locality="Springfield", region="il", country="US")),
    ("123 Main St Springfield IL 62701", dict(number=123, key="main st", locality="Springfield", region="il", postcode="62701")),
    ("123 N Main Street Apt 4", dict(number=123, key="n main st", unit="4", locality=None)),
    ("123 Main St #5", dict(number=123, key="main st", unit="5")),
    ("123 Main St # 5", dict(number=123, key="main st", unit="5")),
    ("Unit 5, 123 Main St", dict(number=123, key="main st", unit="5", locality=None)),
    ("Apt 4 123 Main St", dict(number=123, key="main st", unit="4")),
    ("4-123 King St W, Toronto, ON M5V 1A1",
     dict(number=123, numtext="123", unit="4", key="king st w", locality="Toronto", region="on", postcode="M5V1A1", country="CA")),
    ("123A Elm Ave", dict(number=123, numtext="123A", key="elm ave")),
    ("123 1/2 Oak St", dict(number=123, numtext="123 1/2", key="oak st")),
    ("123 ½ Oak St", dict(number=123, numtext="123 1/2", key="oak st")),
    ("1600 Pennsylvania Ave NW, Washington, DC 20500",
     dict(number=1600, key="pennsylvania ave nw", locality="Washington", region="dc", postcode="20500", country="US")),
    ("1600 Pennsylvania Ave, Washington", dict(number=1600, key="pennsylvania ave", locality="Washington", region=None)),
    ("123 Rue Principale, Gatineau, QC", dict(number=123, key="rue principale", locality="Gatineau", region="qc", country="CA")),
    ("123, rue Principale, Gatineau", dict(number=123, key="rue principale", locality="Gatineau")),
    ("123 Rue Principale Gatineau QC", dict(number=123, key="rue principale", locality="Gatineau", region="qc")),
    ("123 Boulevard Saint-Laurent, Montréal, QC H2X 2T3",
     dict(number=123, key="blvd st laurent", locality="Montréal", region="qc", postcode="H2X2T3")),
    ("890 US 20 South, Basin, WY", dict(number=890, key="us hwy 20 s", locality="Basin", region="wy")),
    ("890 US 20 South Basin WY", dict(number=890, key="us hwy 20 s", locality="Basin", region="wy")),
    ("12 County Road 5, Afton, Wyoming", dict(number=12, key="co rd 5", locality="Afton", region="wy")),
    ("12 County Road 5 Afton Wyoming", dict(number=12, key="co rd 5", locality="Afton", region="wy")),
    ("Hwy 59, Gillette WY", dict(number=None, key="hwy 59", locality="Gillette", region="wy")),
    ("100 I-25, Cheyenne, WY", dict(number=100, key="i 25", locality="Cheyenne")),
    ("Main St, Laramie WY", dict(number=None, key="main st", locality="Laramie", region="wy")),
    ("82070", dict(number=None, key="", postcode="82070", country="US")),
    ("82070-1234", dict(key="", postcode="82070")),
    ("K1A 0B1", dict(number=None, key="", postcode="K1A0B1", country="CA")),
    ("K1A0B1", dict(key="", postcode="K1A0B1", country="CA")),
    ("k1a 0b1", dict(key="", postcode="K1A0B1")),
    ("K1A", dict(key="", postcode="K1A", country="CA")),
    ("Elm Street", dict(number=None, key="elm st", locality=None, region=None)),
    ("  123   main st.  ", dict(number=123, key="main st", locality=None)),
    ("123 main st springfield il", dict(number=123, key="main st", locality="springfield", region="il")),
    ("123 Main St, Springfield, IL, USA", dict(number=123, key="main st", locality="Springfield", region="il", country="US")),
    ("123 Main St, Springfield, IL.", dict(number=123, key="main st", locality="Springfield", region="il")),
    ("123 Main St Miami FL 33101", dict(number=123, key="main st", locality="Miami", region="fl", postcode="33101")),
    ("123 Main St Suite 200, Denver, CO 80202", dict(number=123, key="main st", unit="200", locality="Denver", region="co")),
    ("123 Main St Apt 4 Springfield IL", dict(number=123, key="main st", unit="4", locality="Springfield", region="il")),
    ("350 5th Ave, New York, NY 10118", dict(number=350, key="5th ave", locality="New York", region="ny")),
    ("123 Main St, New York", dict(number=123, key="main st", locality="New York", region="ny")),
    ("123 Lake Shore Dr Chicago IL", dict(number=123, key="lake shore dr", locality="Chicago", region="il")),
    ("123 Main St Park City UT", dict(number=123, key="main st", locality="Park City", region="ut")),
    ("123 King St West Toronto ON", dict(number=123, key="king st w", locality="Toronto", region="on")),
    ("12 Oak Ct", dict(number=12, key="oak ct", region=None, locality=None)),  # Court, not Connecticut
    ("12 Oak Ct Hartford CT", dict(number=12, key="oak ct", locality="Hartford", region="ct")),
    ("100 Main St NE", dict(number=100, key="main st ne", region=None, locality=None)),  # a direction, not Nebraska
    ("123 Main Springfield IL", dict(number=123, key="main", locality="Springfield", region="il")),
    ("123 Rue Ste Catherine", dict(number=123, unit=None, key="rue ste catherine")),  # Sainte, not Suite
    ("Laramie WY 82070", dict(number=None, key="laramie", region="wy", postcode="82070")),
    ("Springfield, IL", dict(number=None, key="springfield", region="il", locality=None)),
    # numbered roads without a street type
    ("420 autauga county 4 prattville al", dict(number=420, key="autauga county 4", locality="prattville", region="al")),
    ("420 Autauga County 4 36067", dict(number=420, key="autauga county 4", locality=None, postcode="36067")),
    ("473 AUTAUGA COUNTY 68 W. MARBURY AL 36022-1234", dict(number=473, key="autauga county 68 w", locality="MARBURY")),
    # units written before the civic number
    ("#2-219 Masonic Dr, Mount Pearl, NL", dict(number=219, unit="2", key="masonic dr", locality="Mount Pearl", region="nl")),
    ("A-42 Bell's Turn, St. John's, NL", dict(number=42, unit="A", key="bells turn", locality="St. John's")),
    ("I-25 Cheyenne", dict(number=None, unit=None)),  # a route, not unit I of civic 25
    # traditional and French state/province names
    ("169 Bridger St., Gillette, Wyo.", dict(number=169, key="bridger st", locality="Gillette", region="wy")),
    ("12 Elm St, Seattle, Wash", dict(key="elm st", locality="Seattle", region="wa")),
    ("5 Iron Ore Rd", dict(key="iron ore rd", region=None)),
    ("8, rue de l'École, Moncton, Nouveau-Brunswick", dict(number=8, key="rue de lecole", locality="Moncton", region="nb")),
]


@pytest.mark.parametrize("text,expected", P, ids=[p[0] for p in P])
def test_parse_address(text, expected):
    got = parse_address(text)
    assert {k: got[k] for k in expected} == expected


def test_parse_offers_alternative_readings_without_commas():
    alts = [(a["street"], a["locality"]) for a in parse_address("123 Main St North Platte NE")["alts"]]
    assert ("Main St", "North Platte") in alts
    alts = [(a["street"], a["locality"]) for a in parse_address("123 Main St Park City UT")["alts"]]
    assert alts[0] == ("Main St", "Park City") and len(alts) > 1
    assert parse_address("")["key"] == "" and parse_address("   ,  ")["postcode"] is None


@pytest.mark.parametrize("text", [
    "123 Main St", "123 Main St, Springfield, IL", "4-123 King St W, Toronto", "Main St, Laramie WY", "Main St Laramie WY",
    "82070", "K1A 0B1", "K1A0B1", "US 20, Basin WY", "Hwy 59, Gillette WY", "123 Rue Principale, Gatineau", "12 County Road 5",
])
def test_looks_like_address(text):
    assert looks_like_address(text)


@pytest.mark.parametrize("text", [
    "Jackson", "Old Faithful", "Grand Teton National Park", "Yellowstone Lake", "Lake Louise, Alberta", "Springfield, IL",
    "Elm Street", "Laramie WY", "Jackson Hole Mountain Resort", "Mount Rushmore", "", "Paris",
])
def test_not_an_address(text):
    assert not looks_like_address(text)


def test_looser_spellings():
    assert _typos("stephevnille", "stephenville") == 1 and _typos("pasaedna", "pasadena") == 1
    assert _typos("laramie", "laramie") == 0 and _typos("laramie", "cheyenne") > 2
    assert _spelled_out("bridge crk") == "bridge creek" and _spelled_out("2nd w") == "2nd west"
    assert _spelled_out("n pne") == "pine" and _spelled_out("hwy 59") is None and _spelled_out("rue principale") is None
    assert _key_variants("Cir Dr", "cir dr", "US") == ["circle dr"]
    assert "avenue 32e" in _key_variants("av. 32e", "av 32e", "CA")
    assert _key_variants("Cocagne Sud Rd", "cocagne sud rd", "CA") == ["ch cocagne s"]
    assert _key_variants("Main St", "main st", "US") == [] and _key_variants("Main St", "main st", None) == ["rue main"]


def test_spelled_out_suffixes_key_like_abbreviations():
    """OSM writes "Doctor Martin Luther King Junior Boulevard"; TIGER "Dr Martin Luther King Jr Blvd"."""
    assert street_key("Doctor Martin Luther King Junior Boulevard") == "dr martin luther king jr blvd"
    assert street_key("Dr Martin Luther King Jr Blvd") == "dr martin luther king jr blvd"
    assert street_base(street_key("Martin Luther King Junior Blvd")) == street_base(street_key("Martin Luther King Jr Blvd"))


def test_grid_and_polyline_helpers():
    assert cell_of(39.8, -89.65) == int(129.8 * 10) * 3600 + int(90.35 * 10)
    cells = cells_around(39.8, -89.65, 10)
    assert cell_of(39.8, -89.65) in cells and cell_of(39.86, -89.75) in cells and cell_of(40.5, -89.65) not in cells
    assert cell_of(0.05, 179.95) in cells_around(0.05, -179.95, 20)  # wraps the antimeridian
    pts = [(39.8012, -89.66), (39.8012, -89.65), (39.81, -89.649999)]
    assert [(la, lo) for lo, la in decode_polyline6(encode_polyline(pts))] == pytest.approx(pts)


# --------------------------------------------------------------------------- fixture index

SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE streets(id INTEGER PRIMARY KEY, key TEXT NOT NULL, base TEXT NOT NULL, name TEXT NOT NULL, cell INTEGER NOT NULL,
                     lat INTEGER NOT NULL, lon INTEGER NOT NULL, region TEXT, postcode TEXT);
CREATE INDEX streets_key ON streets(key, cell);
CREATE INDEX streets_base ON streets(base, cell);
CREATE TABLE ranges(sid INTEGER NOT NULL, lo INTEGER NOT NULL, hi INTEGER NOT NULL, parity INTEGER NOT NULL, rev INTEGER NOT NULL,
                    postcode TEXT, geom TEXT NOT NULL);
CREATE INDEX ranges_sid ON ranges(sid, lo);
CREATE TABLE points(sid INTEGER NOT NULL, num INTEGER NOT NULL, numtext TEXT NOT NULL, unit TEXT, lat INTEGER NOT NULL,
                    lon INTEGER NOT NULL, postcode TEXT, source TEXT NOT NULL);
CREATE INDEX points_sid ON points(sid, num);
CREATE TABLE postcodes(code TEXT PRIMARY KEY, lat INTEGER NOT NULL, lon INTEGER NOT NULL, region TEXT);
"""
E6 = 1_000_000


class Builder:
    def __init__(self, path: Path, version: int = VERSION):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)
        self.db.executemany("INSERT INTO meta VALUES(?, ?)", [
            ("norm_version", str(version)), ("built_at", "2026-09-26T00:00:00Z"),
            ("sources", '["tiger", "nar", "osm"]'), ("streets", "0"), ("points", "0"),
        ])

    def street(self, name, lat, lon, region=None, postcode=None) -> int:
        key = street_key(name)
        cur = self.db.execute("INSERT INTO streets(key, base, name, cell, lat, lon, region, postcode) VALUES(?,?,?,?,?,?,?,?)",
                              (key, street_base(key), name, cell_of(lat, lon), round(lat * E6), round(lon * E6), region, postcode))
        return cur.lastrowid

    def range(self, sid, lo, hi, parity, pts, rev=0, postcode=None):
        self.db.execute("INSERT INTO ranges VALUES(?,?,?,?,?,?,?)", (sid, lo, hi, parity, rev, postcode, encode_polyline(pts)))

    def point(self, sid, numtext, lat, lon, unit=None, source="osm", postcode=None):
        self.db.execute("INSERT INTO points VALUES(?,?,?,?,?,?,?,?)",
                        (sid, int("".join(c for c in numtext.split()[0] if c.isdigit())), numtext, unit,
                         round(lat * E6), round(lon * E6), postcode, source))

    def postcode(self, code, lat, lon, region):
        self.db.execute("INSERT INTO postcodes VALUES(?,?,?,?)", (code, round(lat * E6), round(lon * E6), region))

    def close(self):
        self.db.commit()
        self.db.close()


PLACES = [
    {"name": "Springfield", "fcode": "PPLA", "lat": 39.8017, "lon": -89.6437, "admin1": "Illinois", "country": "US", "population": 114394},
    {"name": "Springfield", "fcode": "PPLA2", "lat": 37.2153, "lon": -93.2982, "admin1": "Missouri", "country": "US", "population": 169176},
    {"name": "Springfield Lake", "fcode": "RSV", "lat": 39.75, "lon": -89.60, "admin1": "Illinois", "country": "US", "population": 0},
    {"name": "Toronto", "fcode": "PPLA", "lat": 43.7001, "lon": -79.4163, "admin1": "Ontario", "country": "CA", "population": 2794356},
    {"name": "Basin", "fcode": "PPLA2", "lat": 44.3797, "lon": -108.0390, "admin1": "Wyoming", "country": "US", "population": 1305},
    {"name": "Sizzling Basin", "fcode": "SPNT", "lat": 44.7250, "lon": -110.7000, "admin1": "Wyoming", "country": "US", "population": 0},
    {"name": "Laramie", "fcode": "PPLA2", "lat": 41.3114, "lon": -105.5911, "admin1": "Wyoming", "country": "US", "population": 32158},
]
SPRINGFIELD_IL = (39.8017, -89.6437)
SPRINGFIELD_MO = (37.2153, -93.2982)


def make_resolver(near=None):
    """A stand-in for GeoData.search_places: prefix match, optional ', XX' region, nearer and bigger first."""
    calls: list[str] = []

    def resolve(q: str) -> list[dict]:
        calls.append(q)
        name, _, reg = q.partition(",")
        reg = reg.strip().lower()
        hits = [dict(p) for p in PLACES if name_key(p["name"]).startswith(name_key(name))
                and (not reg or STATES.get(p["admin1"].lower()) == reg)]
        if near:
            return sorted(hits, key=lambda p: haversine_km(near[0], near[1], p["lat"], p["lon"]))
        return sorted(hits, key=lambda p: -p["population"])

    resolve.calls = calls
    return resolve


def describe(lat, lon):
    towns = [p for p in PLACES if p["fcode"].startswith("PPL")]
    p = min(towns, key=lambda p: haversine_km(lat, lon, p["lat"], p["lon"]))
    return {"place": p["name"], "admin1": p["admin1"], "country": p["country"],
            "distance_km": round(haversine_km(lat, lon, p["lat"], p["lon"]), 1)}


@pytest.fixture(scope="module")
def index_path(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("maps") / "addresses.sqlite"
    b = Builder(path)
    # Springfield, IL: Main St crosses two grid cells (-89.65 and -89.705)
    main = b.street("Main St", 39.8010, -89.6500, "il", "62701")
    b.point(main, "123", 39.80105, -89.64950, postcode="62701")
    b.point(main, "123A", 39.80106, -89.64940)
    b.range(main, 201, 299, 1, [(39.8012, -89.6600), (39.8012, -89.6500)])
    b.range(main, 200, 298, 2, [(39.8008, -89.6600), (39.8008, -89.6500)], rev=1)  # 298 at the west end
    b.range(main, 300, 398, 2, [(39.8008, -89.6500), (39.8008, -89.6400)])  # the odd side of this block is missing
    main_w = b.street("Main St", 39.8010, -89.7050, "il")
    b.range(main_w, 1001, 1099, 1, [(39.8012, -89.7100), (39.8012, -89.7000)])
    b.street("Elm Ave", 39.7990, -89.6400, "il")  # a name only: no numbers known
    oak = b.street("Oak St", 39.7950, -89.6450, "il")
    for n, lon in (("10", -89.6460), ("14", -89.6455), ("20", -89.6440)):
        b.point(oak, n, 39.7950, lon, source="nar")
    b.street("Elm St", 39.9000, -89.5000, "il")  # 13 km out of town
    # Springfield, MO
    mo = b.street("Main St", 37.2100, -93.3000, "mo", "65806")
    b.point(mo, "123", 37.2101, -93.2999, postcode="65806")
    # Toronto: NAR points, one per unit
    king = b.street("King St W", 43.6440, -79.3990, "on", "M5V1A1")
    b.point(king, "123", 43.64410, -79.39890, source="nar", postcode="M5V1A1")
    b.point(king, "123", 43.64412, -79.39888, unit="4", source="nar", postcode="M5V1A1")
    b.point(king, "125", 43.64420, -79.39870, source="nar")
    # Basin, WY, and a US 20 inside Yellowstone that must not be picked for "Basin"
    us20 = b.street("US Hwy 20 S", 44.3790, -108.0400, "wy")
    b.range(us20, 800, 898, 2, [(44.3700, -108.0400), (44.3900, -108.0400)])
    ys = b.street("US Hwy 20 S", 44.7200, -110.7000, "wy")
    b.range(ys, 800, 898, 2, [(44.7100, -110.7000), (44.7300, -110.7000)])
    # postcodes
    b.postcode("62701", 39.7990, -89.6440, "il")
    b.postcode("82070", 41.3100, -105.5900, "wy")
    b.postcode("M5V1A1", 43.6445, -79.3985, "on")
    b.postcode("M5V", 43.6400, -79.4000, "on")
    b.close()
    return path


@pytest.fixture()
def idx(index_path):
    ix = AddressIndex(index_path)
    yield ix
    ix.close()


def search(idx, text, near=None, **kw):
    return idx.search(text, near=near, resolve_place=make_resolver(near), describe=describe, **kw)


RESULT_KEYS = {"name", "label", "kind", "lat", "lon", "precision", "source", "admin1", "country", "postcode"}


def test_exact_point(idx):
    r = search(idx, "123 Main St, Springfield, IL")
    top = r[0]
    assert set(top) == RESULT_KEYS
    assert (top["name"], top["kind"], top["precision"], top["source"]) == ("123 Main St", "address", "exact", "osm")
    assert (top["lat"], top["lon"]) == pytest.approx((39.80105, -89.64950))
    assert top["label"] == "123 Main St, Springfield, Illinois 62701"
    assert (top["admin1"], top["country"], top["postcode"]) == ("Illinois", "US", "62701")
    assert all(x["lat"] > 39 for x in r)  # nothing from Missouri
    assert search(idx, "123A Main St, Springfield, IL")[0]["name"] == "123A Main St"


def test_interpolated_odd_and_even_with_reversed_numbering(idx):
    odd = search(idx, "251 Main St, Springfield, IL")[0]
    assert (odd["precision"], odd["source"], odd["name"]) == ("interpolated", "tiger", "251 Main St")
    assert (odd["lat"], odd["lon"]) == pytest.approx((39.8012, -89.66 + 0.01 * 50 / 98), abs=2e-6)
    even = search(idx, "250 Main St Springfield IL")[0]  # numbers decrease west to east
    assert even["precision"] == "interpolated"
    assert (even["lat"], even["lon"]) == pytest.approx((39.8008, -89.66 + 0.01 * (1 - 50 / 98)), abs=2e-6)
    far = search(idx, "1051 Main St, Springfield, IL")[0]  # the segment in the next grid cell
    assert far["precision"] == "interpolated" and far["lon"] == pytest.approx(-89.71 + 0.01 * 50 / 98, abs=2e-6)


def test_one_result_per_street(idx):
    r = search(idx, "251 Main St, Springfield, IL")
    assert [x["name"] for x in r].count("251 Main St") == 1
    assert not [x for x in r if x["kind"] == "street" and haversine_km(x["lat"], x["lon"], *SPRINGFIELD_IL) < 20]


def test_nearby_number(idx):
    r = search(idx, "16 Oak St, Springfield, IL")[0]
    assert (r["name"], r["precision"], r["source"]) == ("14 Oak St", "nearby", "nar")
    past_end = search(idx, "500 Main St, Springfield, IL")[0]  # beyond every range: the closest end
    assert (past_end["name"], past_end["precision"]) == ("398 Main St", "nearby")
    other_side = search(idx, "301 Main St, Springfield, IL")[0]  # only the even side is known here
    assert (other_side["name"], other_side["precision"]) == ("302 Main St", "nearby")


def test_street_precision_and_street_only(idx):
    r = search(idx, "123 Elm Ave, Springfield, IL")[0]
    assert (r["name"], r["kind"], r["precision"], r["source"]) == ("Elm Ave", "street", "street", "streets")
    st = search(idx, "Main St, Springfield IL")
    assert st[0]["name"] == "Main St" and st[0]["kind"] == "street"
    assert st[0]["lon"] == pytest.approx(-89.65)  # the part nearest the town centre
    assert len([x for x in st if x["name"] == "Main St"]) == 1


def test_base_fallback(idx):
    # "Elm Blvd" isn't a street in town, but Elm Ave (same base name) is; Elm St is 13 km out
    r = search(idx, "Elm Blvd, Springfield, IL")
    assert r and r[0]["name"] == "Elm Ave"
    r = search(idx, "123 Main Springfield IL")  # no street type at all
    assert r[0]["name"] == "123 Main St" and r[0]["precision"] == "exact"


def test_postcodes(idx):
    r = search(idx, "82070")
    assert len(r) == 1
    assert (r[0]["name"], r[0]["kind"], r[0]["precision"], r[0]["country"]) == ("82070", "postcode", "postcode", "US")
    assert r[0]["label"] == "82070, Laramie, Wyoming"
    ca = search(idx, "m5v1a1")[0]
    assert (ca["name"], ca["country"], ca["admin1"]) == ("M5V 1A1", "CA", "Ontario")
    fsa = search(idx, "M5V 9Z9")[0]  # unknown code: its forward sortation area
    assert fsa["name"] == "M5V" and fsa["lat"] == pytest.approx(43.64)
    assert search(idx, "99999") == []
    # a postcode anchors a street without a town
    r = search(idx, "123 Main St 62701")
    assert r[0]["precision"] == "exact" and r[0]["lat"] == pytest.approx(39.80105)


def test_canadian_unit_and_postcode(idx):
    r = search(idx, "4-123 King St W, Toronto, ON M5V 1A1")[0]
    assert (r["name"], r["precision"], r["source"], r["country"]) == ("123 King St W #4", "exact", "nar", "CA")
    assert r["label"] == "123 King St W #4, Toronto, Ontario M5V 1A1"
    plain = search(idx, "123 King St W, Toronto")[0]
    assert plain["name"] == "123 King St W" and plain["lat"] == pytest.approx(43.64410)


def test_locality_anchoring(idx):
    il = search(idx, "123 Main St, Springfield, IL")[0]
    mo = search(idx, "123 Main St, Springfield, MO")[0]
    assert il["admin1"] == "Illinois" and mo["admin1"] == "Missouri"
    assert mo["label"] == "123 Main St, Springfield, Missouri 65806"
    # no state: both Springfields, the nearer one first
    both = search(idx, "123 Main St, Springfield", near=SPRINGFIELD_MO)
    assert [x["admin1"] for x in both[:2]] == ["Missouri", "Illinois"]
    assert both[0]["distance_km"] < 1
    both = search(idx, "123 Main St, Springfield", near=SPRINGFIELD_IL)
    assert both[0]["admin1"] == "Illinois"
    # a town, not the hot spring that shares its name
    basin = search(idx, "890 US 20 South, Basin, WY")
    assert basin[0]["precision"] == "interpolated"
    assert basin[0]["lat"] == pytest.approx(44.37 + 0.02 * 90 / 98, abs=2e-6)
    assert all(x["lon"] > -109 for x in basin)


def test_anchor_resolution_calls(idx):
    resolve = make_resolver()
    idx.search("123 Main St, Springfield, IL", resolve_place=resolve)
    assert resolve.calls == ["Springfield, IL"]


def test_near_and_nationwide(idx):
    assert search(idx, "123 Main St", near=SPRINGFIELD_MO)[0]["admin1"] == "Missouri"
    assert search(idx, "123 Main St", near=SPRINGFIELD_IL)[0]["admin1"] == "Illinois"
    everywhere = idx.search("123 Main St")  # no position, no town: every Main St with a 123
    assert {x["admin1"] for x in everywhere} >= {"Illinois", "Missouri"}
    assert {x["admin1"] for x in idx.search("123 Main St, MO")} == {"Missouri"}  # a state alone filters


def test_unknown_street_and_town(idx):
    assert search(idx, "123 Nowhere Rd, Springfield, IL") == []
    assert search(idx, "Main St, Atlantis") != []  # an unknown town doesn't block the street lookup
    assert idx.search("") == [] and idx.search("   ") == []


def test_ranking_prefers_precision(idx):
    r = search(idx, "123 Main St", near=(38.5, -91.5))  # halfway between the two Springfields
    assert r[0]["precision"] == "exact"
    precs = [x["precision"] for x in r]
    order = {"exact": 0, "interpolated": 1, "nearby": 2, "street": 3}
    assert precs == sorted(precs, key=order.get)


def test_limit(idx):
    assert len(search(idx, "123 Main St", limit=1)) == 1


def test_version_mismatch_and_missing_file(tmp_path):
    old = tmp_path / "old.sqlite"
    b = Builder(old, version=VERSION - 1)
    b.street("Main St", 39.8, -89.65, "il")
    b.close()
    ix = AddressIndex(old)
    assert not ix.available() and not ix and ix.search("Main St") == [] and ix.info() == {"available": False}
    ix.close()
    missing = AddressIndex(tmp_path / "nope.sqlite")
    assert not missing.available()
    missing.close()


def test_pending_rebuild_is_swapped_in(tmp_path, index_path):
    target = tmp_path / "addresses.sqlite"
    (tmp_path / "addresses.sqlite.new").write_bytes(index_path.read_bytes())
    ix = AddressIndex(target)
    assert ix.available() and target.is_file() and not (tmp_path / "addresses.sqlite.new").exists()
    info = ix.info()
    assert info["available"] and info["sources"] == ["tiger", "nar", "osm"] and "points" in info["counts"]
    ix.close()


def test_street_on_a_state_line_matches_either_state(tmp_path):
    """State St in Bristol is the TN/VA line: one street row with no region, labelled by postcode."""
    path = tmp_path / "addresses.sqlite"
    b = Builder(path)
    st = b.street("State St", 36.5950, -82.1850)  # region NULL: TIGER saw it in both states
    b.range(st, 101, 199, 1, [(36.5952, -82.1900), (36.5952, -82.1800)], postcode="37620")
    b.range(st, 100, 198, 2, [(36.5948, -82.1900), (36.5948, -82.1800)], postcode="24201")
    b.postcode("37620", 36.58, -82.18, "tn")
    b.postcode("24201", 36.61, -82.18, "va")
    b.close()
    ix = AddressIndex(path)
    try:
        va = ix.search("150 State St, VA")
        assert va and (va[0]["name"], va[0]["precision"], va[0]["admin1"]) == ("150 State St", "interpolated", "Virginia")
        tn = ix.search("151 State St, TN")
        assert tn and (tn[0]["name"], tn[0]["admin1"], tn[0]["country"]) == ("151 State St", "Tennessee", "US")
        assert ix.search("150 State St")[0]["admin1"] == "Virginia"
    finally:
        ix.close()


def test_nationwide_lookup_reaches_northern_cells(tmp_path):
    """Without a town the street is looked up everywhere; the number must not be lost to the
    index order, which lists the southernmost cells of a common name first."""
    path = tmp_path / "addresses.sqlite"
    b = Builder(path)
    for i in range(300):  # 300 Main Streets across the south, none with number 4821
        sid = b.street("Main St", 25.05 + (i // 60) * 0.3, -100.05 + (i % 60) * 0.3, "tx")
        b.range(sid, 1, 99, 1, [(25.05 + (i // 60) * 0.3, -100.05 + (i % 60) * 0.3),
                                (25.05 + (i // 60) * 0.3, -100.04 + (i % 60) * 0.3)])
    north = b.street("Main St", 46.8750, -96.7850, "nd")
    b.range(north, 4801, 4899, 1, [(46.8752, -96.7900), (46.8752, -96.7800)])
    b.close()
    ix = AddressIndex(path)
    try:
        r = ix.search("4821 Main St")
        assert r and (r[0]["name"], r[0]["precision"]) == ("4821 Main St", "interpolated") and r[0]["lat"] > 46
        r = ix.search("4821 Main St", near=(25.1, -99.9))  # typed far away: offered after the local near miss
        assert any(x["name"] == "4821 Main St" and x["precision"] == "interpolated" and x["lat"] > 46 for x in r)
    finally:
        ix.close()


def test_closed_index_finds_nothing(index_path):
    ix = AddressIndex(index_path)
    ix.close()
    assert not ix.available() and ix.search("123 Main St") == []


# --------------------------------------------------------------------------- adversarial spellings

LARAMIE = (41.3114, -105.5911)
TOWNS2 = [
    {"name": "Laramie", "fcode": "PPLA2", "lat": 41.3114, "lon": -105.5911, "admin1": "Wyoming", "country": "US", "population": 32158},
    {"name": "Gillette", "fcode": "PPLA2", "lat": 44.2911, "lon": -105.5022, "admin1": "Wyoming", "country": "US", "population": 32857},
    {"name": "Moncton", "fcode": "PPL", "lat": 46.1159, "lon": -64.8019, "admin1": "New Brunswick", "country": "CA", "population": 79470},
    {"name": "Bath", "fcode": "PPL", "lat": 43.9109, "lon": -69.8206, "admin1": "Maine", "country": "US", "population": 8514},
] + [  # five towns called Sleepy Hollow; Wyoming's is the smallest
    {"name": "Sleepy Hollow", "fcode": "PPL", "lat": lat, "lon": lon, "admin1": st, "country": "US", "population": pop}
    for lat, lon, st, pop in ((41.0857, -73.8585, "New York", 10000), (42.0942, -88.3084, "Illinois", 3300),
                              (38.0080, -122.5800, "California", 2400), (40.0, -83.0, "Ohio", 2000),
                              (44.2269, -105.4383, "Wyoming", 1300))
]


def resolver2(q: str) -> list[dict]:
    """Prefix match on TOWNS2, biggest first, at most 8 like the real call."""
    name, _, reg = q.partition(",")
    reg = reg.strip().lower()
    hits = [dict(t) for t in TOWNS2 if name_key(t["name"]).startswith(name_key(name))
            and (not reg or STATES.get(t["admin1"].lower()) == reg)]
    return sorted(hits, key=lambda t: -t["population"])[:8]


def describe2(lat, lon):
    t = min(TOWNS2, key=lambda t: haversine_km(lat, lon, t["lat"], t["lon"]))
    d = haversine_km(lat, lon, t["lat"], t["lon"])
    if d > 30:  # the NB village of Bath isn't in TOWNS2 (the place search misses it) but the gazetteer knows it
        return {"place": "Bath", "admin1": "New Brunswick", "country": "CA", "distance_km": 1.0} if lat > 46 else {}
    return {"place": t["name"], "admin1": t["admin1"], "country": t["country"], "distance_km": round(d, 1)}


@pytest.fixture(scope="module")
def idx2(tmp_path_factory):
    path = tmp_path_factory.mktemp("maps2") / "addresses.sqlite"
    b = Builder(path)
    # an odd/even range beats an overlapping range that lists every number
    good = b.street("Goodson Rd", 41.3000, -105.5900, "wy")
    b.range(good, 900, 920, 0, [(41.3000, -105.6000), (41.3000, -105.5980)])
    b.range(good, 901, 999, 1, [(41.3100, -105.5900), (41.3200, -105.5900)])
    # the right side of town for a mistyped street type
    for name, lat in (("W 5th St", 41.3150), ("E 5th St", 41.3050)):
        b.range(b.street(name, lat, -105.5900, "wy"), 100, 198, 2, [(lat, -105.6000), (lat, -105.5800)])
    # typed without a street type, or with a type word inside the name
    b.point(b.street("Bridge Creek Rd", 41.3300, -105.6000, "wy"), "1737", 41.3300, -105.6000)
    b.point(b.street("Bridge St", 41.3120, -105.5920, "wy"), "20", 41.3120, -105.5920)
    b.point(b.street("Circle Drive", 41.3200, -105.5800, "wy"), "404", 41.3200, -105.5800)
    b.point(b.street("North Pine Street", 41.3180, -105.5850, "wy"), "462", 41.3180, -105.5850)
    b.point(b.street("18th Street", 41.3160, -105.5700, "wy"), "2502", 41.3160, -105.5700)
    # the same street in two towns, the number only in the far one
    b.point(b.street("Bridger Street", 41.3130, -105.5950, "wy"), "1404", 41.3130, -105.5950)
    b.point(b.street("Bridger Street", 44.2900, -105.5000, "wy"), "169", 44.2900, -105.5000)
    b.point(b.street("Sammye Avenue", 44.2270, -105.4380, "wy"), "2409", 44.2270, -105.4380)
    # New Brunswick, in French
    b.point(b.street("Chemin Cocagne Sud", 46.1200, -64.8000, "nb"), "1725", 46.1200, -64.8000, source="nar")
    b.point(b.street("Avenue 32e", 46.1100, -64.8100, "nb"), "9", 46.1100, -64.8100, source="nar")
    # 155 B Smith Rd in Bath, NB (which the place search doesn't offer); Bath, Maine has the street but not the number
    b.point(b.street("B Smith Rd", 46.5200, -67.6000, "nb"), "155", 46.5200, -67.6000, source="nar")
    b.street("B Smith Rd", 43.9000, -69.8200, "me")
    b.close()
    ix = AddressIndex(path)
    yield ix
    ix.close()


def s2(idx2, text, near=None):
    return idx2.search(text, near=near, resolve_place=resolver2, describe=describe2)


def test_parity_range_beats_all_numbers_range(idx2):
    r = s2(idx2, "915 Goodson Rd, Laramie, WY")[0]
    assert r["precision"] == "interpolated" and r["lat"] > 41.30 and r["lon"] == pytest.approx(-105.59)


def test_direction_breaks_ties_between_looser_matches(idx2):
    r = s2(idx2, "140 W 5th Ave, Laramie, WY")[0]
    assert r["name"] == "140 W 5th St" and r["lat"] == pytest.approx(41.315)


@pytest.mark.parametrize("text,name", [
    ("1737 Bridge Creek, Laramie, WY", "1737 Bridge Creek Rd"),
    ("404 Cir Dr, Laramie, WY", "404 Circle Drive"),
    ("462 North Pine, Laramie, WY", "462 North Pine Street"),
    ("1725 Cocagne Sud Rd, Moncton, NB", "1725 Chemin Cocagne Sud"),
    ("9, av. 32e, Moncton (NB)", "9 Avenue 32e"),
    ("9 32e Ave, Moncton, NB", "9 Avenue 32e"),
])
def test_other_spellings_of_the_street(idx2, text, name):
    r = s2(idx2, text)
    assert r and r[0]["name"] == name and r[0]["precision"] == "exact"


@pytest.mark.parametrize("text", ["2502 18th Street, Laramei, WY", "2502 18th St, Larmaie"])
def test_misspelt_town(idx2, text):
    r = s2(idx2, text)[0]
    assert r["name"] == "2502 18th Street" and r["label"].startswith("2502 18th Street, Laramie")


def test_many_towns_of_the_same_name(idx2):
    r = s2(idx2, "2409 Sammye Ave, Sleepy Hollow")[0]
    assert r["name"] == "2409 Sammye Avenue" and r["precision"] == "exact"


def test_number_found_beyond_the_devices_surroundings(idx2):
    r = s2(idx2, "169 Bridger St", near=LARAMIE)
    assert r[0]["name"] == "169 Bridger Street" and r[0]["precision"] == "exact" and r[0]["lat"] > 44
    assert any(x["name"] == "1404 Bridger Street" and x["precision"] == "nearby" for x in r)


def test_town_the_place_search_missed(idx2):
    r = s2(idx2, "155 B Smith Rd, Bath")[0]
    assert r["precision"] == "exact" and r["lat"] == pytest.approx(46.52) and r["admin1"] == "New Brunswick"


# --------------------------------------------------------------------------- LocationService / API

class StubGeo:
    """GeoData stand-in: knows a few places by exact name."""

    def __init__(self):
        self.places = {"elm street": [{"name": "Elm Street Historic District", "label": "Elm Street Historic District, Illinois, US",
                                       "kind": "historic site", "fcode": "HSTS", "lat": 39.79, "lon": -89.64, "admin1": "Illinois",
                                       "country": "US", "population": 0, "source": "geonames", "wiki_path": None}],
                       "main st": [{"name": "Main Street Museum", "label": "Main Street Museum, Nebraska, US", "kind": "museum",
                                    "fcode": "MUS", "lat": 40.87, "lon": -96.14, "admin1": "Nebraska", "country": "US",
                                    "population": 0, "source": "geonames", "wiki_path": None}],
                       "oak st springfield": [{"name": "Oak St, Springfield", "label": "Oak St, Springfield", "kind": "landmark",
                                               "fcode": None, "lat": 39.795, "lon": -89.645, "admin1": None, "country": "US",
                                               "population": 0, "source": "wikipedia", "wiki_path": "A/Oak_St"}],
                       "elm park": [{"name": "Elm Park", "label": "Elm Park, Illinois, US", "kind": "park", "fcode": "PRK",
                                     "lat": 39.80, "lon": -89.63, "admin1": "Illinois", "country": "US", "population": 0,
                                     "source": "geonames", "wiki_path": None}]}

    def search_places(self, query, limit=10, near=None):
        q, head = name_key(query), name_key(query.split(",")[0])
        found = [dict(p) for k, v in self.places.items() if name_key(k) in (q, head) for p in v]
        if "," in query or q in ("springfield", "laramie", "toronto", "basin"):
            found += [dict(p, kind="city", label=p["name"]) for p in make_resolver(near)(query)[:limit]]
        return found

    def where_am_i(self, lat, lon):
        return describe(lat, lon)

    def close(self):
        pass


@pytest.fixture()
def svc(client, index_path):
    client.post("/api/auth/setup", json={"name": "Ada"})
    s = client.app.state.svc
    s.location.geo = StubGeo()
    s.location.addr = AddressIndex(index_path)
    yield s
    s.location.addr.close()


def test_location_search_orders_addresses_and_places(svc):
    loc = svc.location
    r = loc.search("123 Main St, Springfield, IL", 10)
    assert r[0]["kind"] == "address" and r[0]["name"] == "123 Main St"
    both = loc.search("Elm Street", 10)  # a place name first, then the street
    assert both[0]["name"] == "Elm Street Historic District"
    assert any(x["kind"] == "street" and x["name"] == "Elm St" for x in both[1:])
    assert loc.search("Springfield", 10)[0]["kind"] != "street"  # a plain place name doesn't pull in streets
    # an address that isn't in the index still finds the town
    assert loc.search("123 Nowhere Rd, Laramie, WY", 10)[0]["name"] == "Laramie"


def test_location_search_local_street_and_exact_place_names(svc):
    loc = svc.location
    loc.current = lambda: {"lat": SPRINGFIELD_IL[0], "lon": SPRINGFIELD_IL[1], "source": "manual"}
    try:
        r = loc.search("Main St", 10)  # Springfield's Main St, then the museum 700 km away
        assert r[0]["kind"] == "street" and r[0]["name"] == "Main St"
        assert any(x["name"] == "Main Street Museum" for x in r)
    finally:
        del loc.current
    r = loc.search("Oak St, Springfield", 10)  # a landmark of exactly that name before the street
    assert r[0]["kind"] == "landmark" and any(x["kind"] == "street" and x["name"] == "Oak St" for x in r)
    r = loc.search("Elm Park, Springfield", 10)  # "Landmark, Town": the park before Elm Ave (same base name)
    assert r[0]["name"] == "Elm Park" and any(x["kind"] == "street" and x["name"] == "Elm Ave" for x in r)
    assert loc.search("123 Elm Park, Springfield", 10)[0]["kind"] != "park"  # a number means an address


def test_location_search_falls_back_to_places_when_the_engine_fails(svc):
    class Broken:
        def search(self, *a, **kw):
            raise sqlite3.DatabaseError("database disk image is malformed")

        def close(self):
            pass

    real, svc.location.addr = svc.location.addr, Broken()
    try:
        results, note = svc.location.search_detailed("Elm Street", 10)
        assert results and results[0]["name"] == "Elm Street Historic District" and note
    finally:
        svc.location.addr = real


def test_api_search_and_maps_info(client, svc):
    r = client.get("/api/location/search", params={"q": "4-123 King St W, Toronto, ON"}).json()
    assert "error" not in r
    assert r["results"][0]["name"] == "123 King St W #4" and r["results"][0]["precision"] == "exact"
    info = client.get("/api/maps/info").json()
    assert info["addresses"] is True and info["address_counts"]["points"] == 0
    assert "Statistics Canada" in info["attribution"]
    svc.location.addr.close()
    assert client.get("/api/maps/info").json()["addresses"] is False


def test_city_suffix_counts_as_exact_town(tmp_path):
    """"New York" is the state in the gazetteer; the city is "New York City"."""
    from mimi.address import name_key
    towns = [{"name": "New York City", "fcode": "PPL"}, {"name": "New York Mills", "fcode": "PPL"}]
    want = name_key("New York" + " City")
    assert [t["name"] for t in towns if name_key(t["name"]) == want] == ["New York City"]
