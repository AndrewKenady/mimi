"""Street addresses outside the US and Canada: the parser's international forms, the spelling
rules in address_norm, and an OpenStreetMap-only index built by scripts/build_addresses.py from a
small synthetic extract, searched the way LocationService does. No network.

The US and Canadian behavior is pinned by test_address.py and test_build_addresses.py, unchanged."""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[1]
ROOT = CORE.parent
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from mimi.address import AddressIndex, looks_like_address, parse_address
from mimi.address_norm import (
    format_intl_postcode, house_number_intl, intl_postcode, intl_typed, intl_variants, number_first, postcode_first,
    street_key, uk_outward,
)
from mimi.geodata import haversine_km, name_key
from mimi.location import LocationService

_spec = importlib.util.spec_from_file_location("build_addresses", ROOT / "scripts" / "build_addresses.py")
ba = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ba)

# --------------------------------------------------------------------------- the parser

INTL = [
    # input, expected fields
    ("Hauptstraße 5, 10115 Berlin", dict(number=5, key="hauptstraße", locality="Berlin", postcode="10115", order="postfix")),
    ("Hauptstraße 5 10115 Berlin", dict(number=5, key="hauptstraße", locality="Berlin", postcode="10115")),
    ("Hauptstraße 5 Berlin", dict(number=5, key="hauptstraße", locality="Berlin", postcode=None)),
    ("Hauptstr. 5a, Berlin", dict(number=5, numtext="5a", key="hauptstr", locality="Berlin")),
    ("Hauptstraße 5, 10115 Berlin, Deutschland", dict(number=5, locality="Berlin", country="DE")),
    ("Kärntner Straße 5/7, 1010 Wien", dict(number=5, numtext="5/7", key="karntner straße", locality="Wien", postcode="1010")),
    ("Landstrasse 12, 9490 Vaduz", dict(number=12, key="landstrasse", locality="Vaduz", postcode="9490")),
    ("Städtle 23, 9490 Vaduz", dict(number=23, key="stadtle", locality="Vaduz", postcode="9490")),  # no street word
    ("Calle Mayor 12, Madrid", dict(number=12, key="calle mayor", locality="Madrid", order="postfix")),
    ("Calle Mayor, 12, 28013 Madrid", dict(number=12, key="calle mayor", locality="Madrid", postcode="28013")),
    ("Calle Mayor 12 bis, Madrid", dict(number=12, numtext="12bis", key="calle mayor")),
    ("C/ Mayor 12, Madrid", dict(number=12, key="c mayor", locality="Madrid")),
    ("Via Roma 1, Milano", dict(number=1, key="via roma", locality="Milano")),
    ("Via Roma 1, 20121 Milano MI", dict(number=1, key="via roma", locality="Milano", postcode="20121")),
    ("Via Roma n. 1, Milano", dict(number=1, key="via roma", locality="Milano")),
    ("Avinguda Meritxell 25, AD500 Andorra la Vella", dict(number=25, locality="Andorra la Vella", postcode="AD500")),
    ("Damrak 1, 1012 LG Amsterdam", dict(number=1, key="damrak", locality="Amsterdam", postcode="1012LG")),
    ("10 rue de la Paix, 75002 Paris", dict(number=10, key="rue de la paix", locality="Paris", postcode="75002", order="prefix")),
    ("10 rue de la Paix 75002 Paris", dict(number=10, key="rue de la paix", locality="Paris", postcode="75002")),
    ("10 Downing Street, London SW1A 2AA", dict(number=10, key="downing st", locality="London", postcode="SW1A2AA")),
    ("10 Downing Street London SW1A 2AA", dict(number=10, key="downing st", locality="London", postcode="SW1A2AA")),
    ("13-14 King Street, St Helier JE2 4WE", dict(number=13, numtext="13-14", key="king st", locality="St Helier")),
    ("1 Queen Street, Auckland 1010", dict(number=1, key="queen st", locality="Auckland", postcode="1010")),
    ("10 George St, Sydney NSW 2000", dict(number=10, key="george st", locality="Sydney", postcode="2000", admin="NSW")),
    ("SW1A 2AA", dict(number=None, key="", postcode="SW1A2AA")),
]


@pytest.mark.parametrize("text,expected", INTL, ids=[t for t, _ in INTL])
def test_parse_international(text, expected):
    got = parse_address(text)
    assert got["intl"] and {k: got[k] for k in expected} == expected
    assert looks_like_address(text)


@pytest.mark.parametrize("text", [
    "123 Main St, Springfield, IL 62701", "4-123 King St W, Toronto, ON M5V 1A1", "Hwy 59, Gillette WY", "US 20, Basin WY",
    "12 County Road 5 Afton Wyoming", "Laramie WY 82070", "350 5th Ave, New York, NY 10118", "82070", "K1A 0B1",
    "123 Rue Principale, Gatineau, QC", "Studio 54 New York", "Avenue 64, Pasadena", "Elm Street", "Jackson",
])
def test_us_and_canadian_input_is_read_as_before(text):
    assert parse_address(text)["intl"] is False


def test_with_an_international_index_every_input_reads_that_way():
    p = parse_address("Städtle 23, Vaduz", intl=True)  # no street word, no postcode: still a postfix number
    assert (p["number"], p["key"], p["locality"]) == (23, "stadtle", "Vaduz")
    assert parse_address("Städtle 23, Vaduz")["intl"] is False  # without the hint, "Städtle 23" is just a name
    p = parse_address("9490 Vaduz", intl=True)
    assert (p["postcode"], p["key"], p["number"]) == ("9490", "", None)
    assert parse_address("9490", intl=True)["postcode"] == "9490" and parse_address("9490")["postcode"] is None
    p = parse_address("66 King Street, St Helier", intl=True)
    assert (p["number"], p["key"], p["locality"], p["region"]) == (66, "king st", "St Helier", None)
    assert parse_address("12 Main St, Wellington, CT", intl=True)["region"] is None  # no US states in Europe's index


# --------------------------------------------------------------------------- spelling rules

def test_postcodes():
    cases = {"SW1A 2AA": "SW1A2AA", "sw1a2aa": "SW1A2AA", "JE2 4WE": "JE24WE", "D02 X285": "D02X285", "1012 ab": "1012AB",
             "AD500": "AD500", "10115": "10115", "9490": "9490", "D-10115": "10115", "FL-9490": "9490", "114 55": "11455",
             "00-950": "00950", "1000-001": "1000001", "K1A 0B1": None, "82070-1234": None, "hello": None, "": None}
    for text, want in cases.items():
        assert intl_postcode(text) == want, text
    assert format_intl_postcode("SW1A2AA") == "SW1A 2AA" and format_intl_postcode("D02X285") == "D02 X285"
    assert format_intl_postcode("1012AB") == "1012 AB" and format_intl_postcode("10115") == "10115"
    assert uk_outward("SW1A2AA") == "SW1A" and uk_outward("M11AE") == "M1" and uk_outward("10115") is None


def test_house_numbers():
    assert house_number_intl("5") == [(5, "5")] and house_number_intl("5 a") == [(5, "5a")]
    assert house_number_intl("12bis") == [(12, "12bis")] and house_number_intl("5/1") == [(5, "5/1")]
    assert house_number_intl("16-18") == [(16, "16-18"), (18, "16-18")]
    assert house_number_intl("4-123") == [] and house_number_intl("Hauptstraße") == []


def test_spellings_people_type():
    def keys(s):
        return {street_key(v) for v in intl_variants(s)}

    assert "hauptstraße" in keys("Hauptstrasse") and "landstrasse" in keys("Landstraße")
    assert {"hauptstraße", "hauptstrasse"} <= keys("Hauptstr.") and "berliner straße" in keys("Berliner Str.")
    assert "mullerstraße" in keys("Muellerstrasse")  # the index folds ü to u
    assert {"calle mayor", "carrer mayor"} <= keys("C/ Mayor") and "piazza garibaldi" in keys("P.zza Garibaldi")
    assert "viale europa" in keys("V.le Europa") and "avenida diagonal" in keys("Av. Diagonal")
    assert intl_variants("Rue de la Paix") == [] and intl_variants("Avenue Foch") == []  # "ue" ending a word stays
    assert intl_typed("Hauptstraße") and intl_typed("Calle Mayor") and intl_typed("Kirchgasse")
    assert not intl_typed("Städtle") and not intl_typed("Main St") and not intl_typed("Walnut")


def test_country_conventions():
    assert number_first("GB") and number_first("FR") and number_first("us") and not number_first("DE") and not number_first("IT")
    assert number_first(None) is None and postcode_first(None) is None
    assert postcode_first("DE") and postcode_first("FR") and not postcode_first("GB") and not postcode_first("AU")


# --------------------------------------------------------------------------- an OSM-only index

AREAS = {  # (lat, lon) of each made-up neighborhood, and the town the gazetteer has there
    "berlin": (52.5200, 13.4000), "munich": (48.1370, 11.5750), "london": (51.5034, -0.1276), "paris": (48.8686, 2.3310),
    "madrid": (40.4155, -3.7074), "vaduz": (47.1410, 9.5215), "weissbad": (47.3100, 9.4300),
}
_ids = iter(range(1, 10_000))


def _addr(area: str, dlat: float, number: str, street: str | None, pc: str, city: str, way: bool = False, **extra) -> str:
    lat, lon = AREAS[area][0] + dlat, AREAS[area][1] + dlat
    tags = {"addr:housenumber": number, "addr:postcode": pc, "addr:city": city, **extra}
    if street:
        tags["addr:street"] = street
    t = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items())
    i = next(_ids)
    if not way:
        return f'<node id="{i}" lat="{lat:.6f}" lon="{lon:.6f}">{t}</node>'
    a, b = next(_ids), next(_ids)  # a building: the address sits on its first node
    return (f'<node id="{a}" lat="{lat:.6f}" lon="{lon:.6f}"/><node id="{b}" lat="{lat + 0.0001:.6f}" lon="{lon:.6f}"/>'
            f'<way id="{i}"><nd ref="{a}"/><nd ref="{b}"/><nd ref="{a}"/><tag k="building" v="yes"/>{t}</way>')


def _road(area: str, name: str) -> str:
    lat, lon = AREAS[area]
    a, b, w = next(_ids), next(_ids), next(_ids)
    return (f'<node id="{a}" lat="{lat + 0.002:.6f}" lon="{lon:.6f}"/><node id="{b}" lat="{lat + 0.003:.6f}" lon="{lon:.6f}"/>'
            f'<way id="{w}"><nd ref="{a}"/><nd ref="{b}"/><tag k="highway" v="residential"/><tag k="name" v="{name}"/></way>')


OSM = "<?xml version='1.0' encoding='UTF-8'?>\n<osm version=\"0.6\" generator=\"test\">\n" + "\n".join([
    _addr("berlin", 0.0001, "5", "Hauptstraße", "10115", "Berlin"),
    _addr("berlin", 0.0002, "7", "Hauptstraße", "10115", "Berlin"),
    _addr("berlin", 0.0003, "16-18", "Hauptstraße", "10115", "Berlin", way=True),
    _addr("berlin", 0.0004, "3", "Müllerstraße", "10115", "Berlin"),
    _addr("berlin", 0.0005, "9a", "Müllerstraße", "10115", "Berlin"),
    _road("berlin", "Kastanienallee"),
    _addr("munich", 0.0001, "1", "Marienplatz", "80331", "München"),
    _addr("munich", 0.0002, "2", "Marienplatz", "80331", "München"),
    _addr("london", 0.0001, "10", "Downing Street", "SW1A 2AA", "London"),
    _addr("london", 0.0002, "11", "Downing Street", "SW1A 2AB", "London"),
    _addr("paris", 0.0001, "10", "Rue de la Paix", "75002", "Paris"),
    _addr("madrid", 0.0001, "12", "Calle Mayor", "28013", "Madrid"),
    _addr("madrid", 0.0002, "14bis", "Calle Mayor", "28013", "Madrid"),
    _addr("vaduz", 0.0001, "23", "Städtle", "9490", "Vaduz"),
    _addr("vaduz", 0.0002, "12", "Landstrasse", "9490", "Vaduz"),
    _addr("weissbad", 0.0001, "2", None, "9057", "Weissbad", **{"addr:place": "Ahorn", "addr:state": "AR"}),
    _addr("weissbad", 0.0002, "4", None, "9057", "Weissbad", **{"addr:place": "Ahorn"}),
]) + "\n</osm>\n"

PLACES = [  # the gazetteer: GeoNames names Munich in English, as it does
    {"name": "Berlin", "fcode": "PPLC", "country": "DE", "population": 3_400_000, "area": "berlin"},
    {"name": "Munich", "fcode": "PPLA", "country": "DE", "population": 1_260_000, "area": "munich"},
    {"name": "London", "fcode": "PPLC", "country": "GB", "population": 8_900_000, "area": "london"},
    {"name": "Paris", "fcode": "PPLC", "country": "FR", "population": 2_100_000, "area": "paris"},
    {"name": "Madrid", "fcode": "PPLC", "country": "ES", "population": 3_200_000, "area": "madrid"},
    {"name": "Vaduz", "fcode": "PPLC", "country": "LI", "population": 5_100, "area": "vaduz"},
    {"name": "Weissbad", "fcode": "PPL", "country": "CH", "population": 400, "area": "weissbad"},
]
for _p in PLACES:
    _p.update(lat=AREAS[_p["area"]][0], lon=AREAS[_p["area"]][1], admin1=None)


def resolve(q: str) -> list[dict]:
    name = q.split(",")[0]
    return [dict(p) for p in PLACES if name_key(p["name"]).startswith(name_key(name))]


def describe(lat: float, lon: float) -> dict:
    p = min(PLACES, key=lambda p: haversine_km(lat, lon, p["lat"], p["lon"]))
    return {"place": p["name"], "admin1": None, "country": p["country"], "distance_km": haversine_km(lat, lon, p["lat"], p["lon"])}


@pytest.fixture(scope="module")
def index_path(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("intl")
    osm = d / "europe.osm"
    osm.write_text(OSM, encoding="utf-8")
    out = d / "maps" / "addresses.sqlite"
    out.parent.mkdir()
    assert ba.main(["--osm-roads", str(osm), "--osm-points", str(osm), "--out", str(out)]) == 0
    return out


@pytest.fixture()
def idx(index_path):
    ix = AddressIndex(index_path)
    yield ix
    ix.close()


def search(idx, text, **kw):
    return idx.search(text, resolve_place=resolve, describe=describe, **kw)


def test_build_reads_international_data(index_path):
    db = sqlite3.connect(index_path)
    try:
        meta = dict(db.execute("SELECT key, value FROM meta"))
        pcs = {c for (c,) in db.execute("SELECT code FROM postcodes")}
        locs = {k: n for k, n in db.execute("SELECT key, n FROM localities")}
        nums = {(nt, n) for n, nt in db.execute("SELECT num, numtext FROM points")}
        regions = {r for (r,) in db.execute("SELECT DISTINCT region FROM streets")}
        streets = {k for (k,) in db.execute("SELECT key FROM streets")}
    finally:
        db.close()
    assert int(meta["localities"]) == len(locs) and locs["munchen"] == 2 and locs["berlin"] == 5
    assert {"10115", "SW1A2AA", "SW1A2AB", "SW1A", "9490", "28013", "9057"} <= pcs  # UK district "SW1A" too
    assert {("16-18", 16), ("16-18", 18), ("9a", 9), ("14bis", 14)} <= nums
    assert regions == {None}  # addr:state=AR is Appenzell, not Arkansas
    assert {"hauptstraße", "ahorn", "kastanienallee", "downing st"} <= streets  # addr:place and named roads too


def test_index_is_international(idx):
    assert idx.intl and idx.info()["counts"]["localities"] > 0


@pytest.mark.parametrize("text,label", [
    ("Hauptstraße 5, 10115 Berlin", "Hauptstraße 5, 10115 Berlin"),
    ("Hauptstrasse 5, Berlin", "Hauptstraße 5, 10115 Berlin"),
    ("Hauptstr. 7 Berlin", "Hauptstraße 7, 10115 Berlin"),
    ("Hauptstraße 18, Berlin", "Hauptstraße 16-18, 10115 Berlin"),
    ("Muellerstrasse 3, Berlin", "Müllerstraße 3, 10115 Berlin"),
    ("Müllerstraße 9A, Berlin", "Müllerstraße 9a, 10115 Berlin"),
    ("Marienplatz 1, München", "Marienplatz 1, 80331 München"),  # the gazetteer only knows "Munich"
    ("10 Downing Street, London SW1A 2AA", "10 Downing Street, London SW1A 2AA"),
    ("10 Downing Street, London SW1A 9ZZ", "10 Downing Street, London SW1A 2AA"),  # unknown code: its district
    ("10 rue de la Paix, 75002 Paris", "10 Rue de la Paix, 75002 Paris"),
    ("Calle Mayor 12, Madrid", "Calle Mayor 12, 28013 Madrid"),
    ("C/ Mayor 12, Madrid", "Calle Mayor 12, 28013 Madrid"),
    ("Calle Mayor 14 bis, 28013 Madrid", "Calle Mayor 14bis, 28013 Madrid"),
    ("Städtle 23, 9490 Vaduz", "Städtle 23, 9490 Vaduz"),
    ("Staedtle 23, Vaduz", "Städtle 23, 9490 Vaduz"),
    ("Landstraße 12, Vaduz", "Landstrasse 12, 9490 Vaduz"),
    ("Ahorn 2, 9057 Weissbad", "Ahorn 2, 9057 Weissbad"),
])
def test_exact_addresses(idx, text, label):
    r = search(idx, text)
    assert r and r[0]["precision"] == "exact" and r[0]["label"] == label, r[:1]


def test_results_carry_their_country_not_a_us_state(idx):
    r = search(idx, "Ahorn 2, 9057 Weissbad")[0]
    assert (r["country"], r["admin1"], r["postcode"]) == ("CH", None, "9057")
    uk = search(idx, "10 Downing Street, London")[0]
    assert (uk["name"], uk["country"], uk["postcode"]) == ("10 Downing Street", "GB", "SW1A 2AA")


def test_postcodes_and_streets(idx):
    r = search(idx, "SW1A 2AA")
    assert (r[0]["kind"], r[0]["name"], r[0]["label"]) == ("postcode", "SW1A 2AA", "SW1A 2AA, London")
    r = search(idx, "9490 Vaduz")  # a postcode and its town
    assert r[0]["kind"] == "postcode" and r[0]["label"] == "9490, Vaduz"
    r = search(idx, "Kastanienallee, Berlin")  # a named road without numbers
    assert (r[0]["kind"], r[0]["name"]) == ("street", "Kastanienallee")
    r = search(idx, "Nirgendwostraße 1, 10115 Berlin")  # no such street: at least the postcode
    assert [(x["kind"], x["label"]) for x in r] == [("postcode", "10115, Berlin")]


def test_location_search_puts_the_address_first(index_path):
    class Geo:
        def search_places(self, q, limit=10, near=None):
            return [dict(p, kind="city", label=p["name"], source="geonames", wiki_path=None) for p in resolve(q)][:limit]

        def where_am_i(self, lat, lon):
            return describe(lat, lon)

    class Loc:
        geo = Geo()

        def current(self):
            return None

    loc = Loc()
    loc.addr = AddressIndex(index_path)
    try:
        results, note = LocationService.search_detailed(loc, "Hauptstrasse 5, Berlin", 5)
        assert note is None and results[0]["label"] == "Hauptstraße 5, 10115 Berlin"
        results, _ = LocationService.search_detailed(loc, "Städtle 23, Vaduz", 5)  # read with the index's rules
        assert results[0]["label"] == "Städtle 23, 9490 Vaduz"
        results, _ = LocationService.search_detailed(loc, "Berlin", 5)
        assert results[0]["name"] == "Berlin"  # a place name stays a place
    finally:
        loc.addr.close()
