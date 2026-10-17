"""Fuel stations and health services from OpenStreetMap: scripts/build_geodata.py --only pois on a
tiny synthetic extract (XML, and the same converted to PBF), then GeoData.nearby, the API and the
nearby_places tool. No network."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[1]
ROOT = CORE.parent
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from mimi import tools
from mimi.auth import Ctx
from mimi.geodata import SERVICE_KINDS, GeoData, _parse_kinds, haversine_km

_spec = importlib.util.spec_from_file_location("build_geodata", ROOT / "scripts" / "build_geodata.py")
bg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bg)

HERE = (46.5000, 7.0000)  # a lakeside town that doesn't exist


def _square(first_id: int, lat: float, lon: float, d: float = 0.0004) -> tuple[str, str]:
    """Four nodes around (lat, lon) and the <nd> refs of a closed way through them."""
    pts = [(lat - d, lon - d), (lat - d, lon + d), (lat + d, lon + d), (lat + d, lon - d)]
    nodes = "".join(f'<node id="{first_id + i}" lat="{a:.6f}" lon="{b:.6f}"/>' for i, (a, b) in enumerate(pts))
    refs = "".join(f'<nd ref="{first_id + i}"/>' for i in range(4)) + f'<nd ref="{first_id}"/>'
    return nodes, refs


def _tags(**kw) -> str:
    return "".join(f'<tag k="{k.replace("__", ":")}" v="{v}"/>' for k, v in kw.items())


canopy_n, canopy_w = _square(11, 46.50108, 7.00008, 0.00003)
hosp_n, hosp_w = _square(21, 46.5050, 7.0050)
park1_n, park1_w = _square(31, 46.5200, 7.0200)
park2_n, park2_w = _square(5_000_000_001, 46.5210, 7.0210)  # node ids past the first IdFilter window

OSM = f"""<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6" generator="test">
  <bounds minlat="46.4" minlon="6.9" maxlat="46.9" maxlon="7.4"/>
  <node id="1" lat="46.5010" lon="7.0000">{_tags(amenity="fuel", name="Garage du Lac", brand="Esso", opening_hours="24/7",
                                                  phone="+41 21 000 00 00", fuel__diesel="yes", fuel__lpg="no")}</node>
  <node id="2" lat="46.5052" lon="7.0058">{_tags(amenity="hospital", phone="+41 21 111 11 11")}</node>
  <node id="3" lat="46.5049" lon="7.0049">{_tags(healthcare="hospital")}</node>
  <node id="4" lat="46.4990" lon="7.0010">{_tags(healthcare="clinic", name="Permanence Médicale")}</node>
  <node id="5" lat="46.5002" lon="7.0003">{_tags(amenity="pharmacy", healthcare="pharmacy", name="Pharmacie du Lac",
                                                  opening_hours="Mo-Sa 08:00-19:00")}</node>
  <node id="6" lat="46.5040" lon="7.0060">{_tags(emergency="ambulance_station", name="Ambulances de la Côte")}</node>
  <node id="7" lat="46.5001" lon="7.0001">{_tags(amenity="fuel", name="Fleet depot", access="private")}</node>
  <node id="8" lat="46.5003" lon="7.0002">{_tags(**{"disused__amenity": "fuel", "name": "Old garage"})}</node>
  <node id="9" lat="46.5004" lon="7.0004">{_tags(amenity="doctors", name="Dr. Example")}</node>
  <node id="10" lat="46.5005" lon="7.0005">{_tags(emergency="defibrillator")}</node>
  <node id="15" lat="46.8000" lon="7.3000">{_tags(amenity="fuel", name="Station du Col")}</node>
  {canopy_n}{hosp_n}{park1_n}{park2_n}
  <way id="100">{canopy_w}{_tags(amenity="fuel")}</way>
  <way id="101">{hosp_w}{_tags(amenity="hospital", healthcare="hospital", name="Hôpital de la Côte", emergency="yes",
                               addr__street="Rue du Lac", addr__housenumber="12", addr__postcode="1110", addr__city="Morges",
                               addr__country="CH")}</way>
  <way id="201">{park1_w}</way>
  <way id="202">{park2_w}</way>
  <relation id="200"><member type="way" ref="201" role="outer"/><member type="way" ref="202" role="outer"/>
    {_tags(type="multipolygon", amenity="hospital", name="Clinique du Parc", emergency="no")}</relation>
</osm>
"""
# A neighboring extract: it repeats node 1 (the border overlap) and adds a pharmacy outside the first file.
OSM2 = f"""<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6" generator="test">
  <node id="1" lat="46.5010" lon="7.0000">{_tags(amenity="fuel", name="Garage du Lac", brand="Esso")}</node>
  <node id="16" lat="47.6000" lon="8.1000">{_tags(amenity="pharmacy", name="Pharmacie du Nord")}</node>
</osm>
"""


@pytest.fixture(scope="module")
def maps(tmp_path_factory) -> Path:
    import osmium

    d = tmp_path_factory.mktemp("pois")
    src = d / "src"
    src.mkdir()
    (src / "lake.osm").write_text(OSM, encoding="utf-8")
    (src / "north.osm").write_text(OSM2, encoding="utf-8")
    pbf = src / "north.osm.pbf"  # PBF as Geofabrik ships it (this one has no header box)
    with osmium.SimpleWriter(str(pbf)) as w:
        for o in osmium.FileProcessor(str(src / "north.osm")):
            w.add(o)
    out, work = d / "maps", d / "work"
    out.mkdir()
    work.mkdir()
    assert bg.main(["--only", "pois", "--osm", str(src / "lake.osm"), str(pbf), "--maps-dir", str(out), "--work-dir", str(work)]) == 0
    assert list(work.iterdir()) == []  # scratch and build files are gone
    return out


@pytest.fixture()
def geo(maps):
    g = GeoData(maps)
    yield g
    g.close()


def _rows(maps: Path) -> dict[str, tuple]:
    db = sqlite3.connect(maps / "pois.sqlite")
    try:
        return {osm: (kind, name, lat, lon, json.loads(tags or "{}"))
                for osm, kind, name, lat, lon, tags in db.execute("SELECT osm, kind, name, lat, lon, tags FROM pois")}
    finally:
        db.close()


# --------------------------------------------------------------------------- the build
def test_kinds_and_tags():
    assert bg.poi_kind({"amenity": "fuel"}) == "fuel"
    assert bg.poi_kind({"healthcare": "hospital"}) == bg.poi_kind({"amenity": "hospital"}) == "hospital"
    assert bg.poi_kind({"amenity": "clinic"}) == bg.poi_kind({"healthcare": "clinic", "amenity": "doctors"}) == "clinic"
    assert bg.poi_kind({"emergency": "ambulance_station"}) == "ambulance"
    assert bg.poi_kind({"amenity": "pharmacy"}) == bg.poi_kind({"healthcare": "pharmacy"}) == "pharmacy"
    for no in ({"amenity": "fuel", "access": "private"}, {"amenity": "fuel", "disused": "yes"}, {"amenity": "doctors"},
               {"emergency": "defibrillator"}, {"disused:amenity": "fuel"}, {}):
        assert bg.poi_kind(no) is None, no
    t = bg.poi_tags({"contact:phone": "+1 555", "fuel:diesel": "yes", "fuel:octane_95": "maybe", "brand": " Shell ",
                     "website": "https://example.com"})
    assert t == {"phone": "+1 555", "fuel:diesel": "yes", "brand": "Shell"}


def test_dedupe_merges_one_place_mapped_twice():
    def poi(osm, kind, name, lat, lon, **tags):
        return {"osm": osm, "kind": kind, "name": name, "lat": lat, "lon": lon, "tags": tags}

    kept, merged = bg.dedupe_pois([
        poi("n1", "fuel", "BP", 46.5, 7.0, brand="BP", opening_hours="24/7"),
        poi("w1", "fuel", None, 46.50015, 7.0),  # its bare canopy, 17 m away
        poi("n2", "fuel", "BP", 46.5009, 7.0, brand="BP"),  # 100 m: another BP across the road
        poi("w2", "hospital", "St. Mary", 46.6, 7.0, emergency="yes"),
        poi("n3", "hospital", "St Mary", 46.6020, 7.0, phone="+1"),  # 220 m: the same campus
        poi("n4", "hospital", None, 46.6005, 7.0, phone="+2"),  # unnamed, but its own phone: a place of its own
        poi("n5", "pharmacy", "BP", 46.5, 7.0),  # a different kind is never merged
    ])
    assert merged == 2 and len(kept) == 5 and {"n1", "n2", "n4", "n5"} <= {p["osm"] for p in kept}
    mary = next(p for p in kept if p["kind"] == "hospital" and p["name"])
    assert mary["tags"] == {"emergency": "yes", "phone": "+1"}  # one St Mary, with what both knew


def test_build_contents(maps):
    rows = _rows(maps)
    kinds = {}
    for kind, *_ in rows.values():
        kinds[kind] = kinds.get(kind, 0) + 1
    assert kinds == {"fuel": 2, "hospital": 3, "clinic": 1, "pharmacy": 2, "ambulance": 1}
    assert "n7" not in rows and "n8" not in rows and "n9" not in rows and "n10" not in rows  # private, disused, doctors, AED
    assert "w100" not in rows and "n3" not in rows  # the canopy and the bare hospital node merged into their places
    kind, name, lat, lon, tags = rows["n1"]
    assert (kind, name) == ("fuel", "Garage du Lac")
    assert tags == {"brand": "Esso", "opening_hours": "24/7", "phone": "+41 21 000 00 00", "fuel:diesel": "yes", "fuel:lpg": "no"}
    kind, name, lat, lon, tags = rows["w101"]  # an area: the mean of its nodes (the closing node once)
    assert (lat, lon) == pytest.approx((46.5050, 7.0050), abs=1e-6)
    assert tags["emergency"] == "yes" and tags["addr:street"] == "Rue du Lac" and tags["addr:country"] == "CH"
    kind, name, lat, lon, tags = rows["r200"]  # a multipolygon: placed from its ways, one past the 2^31 id window
    assert name == "Clinique du Parc" and 46.5200 < lat < 46.5210 and 7.0200 < lon < 7.0210 and tags["emergency"] == "no"
    assert rows["n2"][1] is None and rows["n2"][4]["phone"] == "+41 21 111 11 11"  # unnamed, kept for its phone
    assert list(rows).count("n1") == 1 and rows["n16"][1] == "Pharmacie du Nord"  # the overlap once; the second file read
    db = sqlite3.connect(maps / "pois.sqlite")
    try:
        meta = dict(db.execute("SELECT key, value FROM meta"))
        assert db.execute("SELECT count(*) FROM pois_rtree").fetchone()[0] == len(rows)
    finally:
        db.close()
    assert "OpenStreetMap" in meta["attribution"] and json.loads(meta["row_counts_by_kind"])["fuel"] == 2
    bounds = json.loads(meta["bounds"])
    assert bounds[0] == [6.9, 46.4, 7.4, 46.9]  # the XML file's <bounds>
    assert bounds[1] == pytest.approx([8.0, 47.5, 8.2, 47.7])  # no header box: the places it holds, plus 0.1 degree


def test_failed_build_keeps_the_old_table(tmp_path):
    maps = tmp_path / "maps"
    maps.mkdir()
    (maps / "pois.sqlite").write_bytes(b"old table")
    with pytest.raises(SystemExit):
        bg.main(["--only", "pois", "--osm", str(tmp_path / "missing.osm.pbf"), "--maps-dir", str(maps), "--work-dir", str(tmp_path)])
    with pytest.raises(SystemExit):
        bg.main(["--only", "pois", "--maps-dir", str(maps), "--work-dir", str(tmp_path)])  # no --osm
    assert (maps / "pois.sqlite").read_bytes() == b"old table"


# --------------------------------------------------------------------------- nearby
def test_kind_filter_ids_and_aliases():
    assert _parse_kinds("fuel") == {"fuel"} and _parse_kinds("gas station") == {"fuel"} and _parse_kinds("petrol") == {"fuel"}
    assert _parse_kinds(["health"]) == {"hospital", "clinic", "pharmacy", "ambulance"}
    assert _parse_kinds("emergency room") == {"hospital"} and _parse_kinds("drugstore") == {"pharmacy"}
    assert _parse_kinds(["nature", "fuel"]) == {"nature", "fuel"} and _parse_kinds("all") is None
    assert set(SERVICE_KINDS) == {"fuel", "hospital", "clinic", "pharmacy", "ambulance"}


def test_nearest_fuel_and_its_details(geo):
    assert geo.pois_available and geo.pois_cover(*HERE) and not geo.pois_cover(10.0, 10.0)
    r = geo.nearby(*HERE, radius_km=5, kinds=["fuel"])
    assert [p["name"] for p in r] == ["Garage du Lac"]  # Station du Col is 40 km out; the depot is private
    f = r[0]
    assert (f["kind"], f["categories"], f["source"], f["unnamed"], f["osm"]) == ("fuel", ["fuel"], "osm", False, "n1")
    assert (f["brand"], f["opening_hours"], f["phone"], f["fuels"]) == ("Esso", "24/7", "+41 21 000 00 00", ["diesel"])
    assert f["direction"] == "N" and f["distance_km"] == pytest.approx(0.11, abs=0.01)
    assert {"name", "kind", "categories", "lat", "lon", "distance_km", "distance_mi", "bearing_deg", "direction", "source",
            "wiki_path", "population", "admin1", "country", "score"} <= set(f)


def test_hospitals_nearest_first_with_emergency_departments(geo):
    r = geo.nearby(*HERE, radius_km=10, kinds="hospital")
    assert [p["distance_km"] for p in r] == sorted(p["distance_km"] for p in r)
    by = {p["osm"]: p for p in r}
    cote = by["w101"]
    assert cote["emergency"] == "yes" and cote["categories"] == ["health", "hospital"]
    assert cote["address"] == "Rue du Lac 12, 1110 Morges"  # written the Swiss way (addr:country)
    assert by["r200"]["emergency"] == "no"
    assert by["n2"]["unnamed"] and by["n2"]["name"] == "Hospital" and "emergency" not in by["n2"]


def test_health_kinds_and_all(geo):
    kinds = {p["kind"] for p in geo.nearby(*HERE, radius_km=10, kinds=["health"], limit=50)}
    assert kinds == {"hospital", "clinic", "pharmacy", "ambulance"}
    assert geo.nearby(*HERE, radius_km=10) == []  # "all" means notable places, not services (and there are none here)
    mixed = geo.nearby(*HERE, radius_km=10, kinds=["fuel", "towns"])
    assert mixed and all(p["kind"] == "fuel" for p in mixed)


def test_search_widens_until_one_is_found(geo):
    r = geo.nearby(46.79, 7.29, radius_km=1, kinds=["fuel"])  # Station du Col is 1.4 km away
    assert r[0]["name"] == "Station du Col" and r[0]["distance_km"] > 1
    r = geo.nearby_services(46.4996, 6.9996, radius_km=0.05, kinds=["pharmacy"], limit=1)
    assert r[0]["name"] == "Pharmacie du Lac" and r[0]["distance_km"] > 0.05


def test_outside_the_osm_area_hospitals_come_from_geonames(maps, tmp_path):
    """A GeoNames HSP stands in where pois.sqlite doesn't reach (the other side of a border)."""
    d = tmp_path / "maps"
    d.mkdir()
    (d / "pois.sqlite").write_bytes((maps / "pois.sqlite").read_bytes())
    db = sqlite3.connect(d / "places.sqlite")
    db.executescript(bg.PLACES_SCHEMA)
    bg.write_meta(db, {"countries": "CH"})
    db.execute("INSERT INTO places VALUES (1, 'Kantonsspital', 'Kantonsspital', 47.0, 8.0, 'S', 'HSP', 'hospital', 'CH', "
               "'Zug', 0, 400)")
    db.execute("INSERT INTO places_rtree VALUES (1, 47.0, 47.0, 8.0, 8.0)")
    db.commit()
    db.close()
    g = GeoData(d)
    try:
        r = g.nearby(47.01, 8.01, radius_km=5, kinds=["hospital"])
        assert [(p["name"], p["source"], p["country"]) for p in r] == [("Kantonsspital", "geonames", "CH")]
        assert g.nearby(47.01, 8.01, radius_km=5, kinds=["fuel"]) == []  # GeoNames has no fuel stations
    finally:
        g.close()


# --------------------------------------------------------------------------- the API and the model's tool
@pytest.fixture()
def svc(client, maps):
    client.post("/api/auth/setup", json={"name": "Ada"})
    s = client.app.state.svc
    s.location.geo = GeoData(maps)
    s.location.current = lambda: {"lat": HERE[0], "lon": HERE[1], "source": "manual"}
    yield s
    s.location.geo.close()


def test_api_nearby_services(client, svc):
    r = client.get("/api/location/nearby", params={"kind": "fuel", "radius": 5}).json()
    assert r["services"] is True and [p["name"] for p in r["places"]] == ["Garage du Lac"]
    r = client.get("/api/location/nearby", params={"kind": "hospital,pharmacy", "radius": 10, "limit": 50}).json()
    assert {p["kind"] for p in r["places"]} == {"hospital", "pharmacy"}
    far = client.get("/api/location/nearby", params={"kind": "fuel", "lat": 10, "lon": 10}).json()
    assert far["services"] is False and far["places"] == []
    assert client.get("/api/maps/info").json()["services"] is True
    assert client.get("/api/location").json()["geodata"]["services"] is True


def _state():
    user = {"id": "u1", "name": "Ada", "role": "owner"}
    return tools.TurnState(ctx=Ctx(user, None, True), chat_id="c", message_id="m", query="", mode={}, vision=False)


def test_tool_answers_nearest_hospital_and_gas_station(svc):
    res = asyncio.run(tools.run("nearby_places", '{"kind": "hospital"}', _state(), svc))
    assert res.ok and res.label == "Looked for hospitals"
    first = res.text.splitlines()[1]
    assert first.startswith("- Hôpital de la Côte (hospital)") and "has an emergency department" in first
    assert "Rue du Lac 12, 1110 Morges" in first and "emergency number" in res.text
    assert "unnamed hospital" in res.text and "no emergency department" in res.text  # Clinique du Parc
    fuel = asyncio.run(tools.run("nearby_places", '{"kind": "fuel", "radius_km": 2}', _state(), svc))
    assert fuel.ok and "Garage du Lac (fuel station)" in fuel.text and "open 24/7" in fuel.text and "fuels: diesel" in fuel.text
    assert fuel.data["places"][0]["osm"] == "n1"
    schema = next(t for t in tools.TOOLS if t.name == "nearby_places").parameters
    assert {"fuel", "hospital", "clinic", "pharmacy", "ambulance", "health"} <= set(schema["properties"]["kind"]["enum"])


def test_tool_says_when_there_is_no_services_data(svc, tmp_path):
    svc.location.geo.close()
    svc.location.geo = GeoData(tmp_path)  # no pois.sqlite: lite tier, or directions not installed
    res = asyncio.run(tools.run("nearby_places", '{"kind": "fuel"}', _state(), svc))
    assert not res.ok and "no offline data on fuel stations" in res.text and "routing" in res.text


def test_distances_are_real(geo):
    for p in geo.nearby(*HERE, radius_km=10, kinds=["health"], limit=50):
        assert p["distance_km"] == pytest.approx(haversine_km(*HERE, p["lat"], p["lon"]), abs=0.01)
