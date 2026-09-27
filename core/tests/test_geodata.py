"""Tests for mimi.geodata.

The geometry helpers and the missing-database behaviour are always tested. The
tests that query real data run against ``<root>/maps/places.sqlite`` and
``geowiki.sqlite`` (built by ``scripts/build_geodata.py``) and are skipped when
those files are absent.
"""

from __future__ import annotations

import re
import statistics
import sys
import time
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[1]
if str(CORE) not in sys.path:  # allow running from any directory
    sys.path.insert(0, str(CORE))

from mimi.geodata import (  # noqa: E402
    KM_PER_MILE,
    GeoData,
    _fts_term,
    _fts_tokens,
    _near_bonus,
    bounding_boxes,
    compass_point,
    haversine_km,
    initial_bearing_deg,
    name_key,
)
from mimi.paths import default_root  # noqa: E402

MAPS = default_root() / "maps"
HAVE_PLACES = (MAPS / "places.sqlite").is_file()
HAVE_WIKI = (MAPS / "geowiki.sqlite").is_file()

needs_places = pytest.mark.skipif(not HAVE_PLACES, reason="maps/places.sqlite not built (run scripts/build_geodata.py)")
needs_wiki = pytest.mark.skipif(not HAVE_WIKI, reason="maps/geowiki.sqlite not built (run scripts/build_geodata.py)")
needs_both = pytest.mark.skipif(not (HAVE_PLACES and HAVE_WIKI), reason="geodata databases not built")

WASHINGTON_MONUMENT = (38.8895, -77.0353)
CN_TOWER = (43.6426, -79.3871)
MAMMOTH_CAVE = (37.187, -86.100)
SPRINGFIELD_MO = (37.2090, -93.2923)
OLD_FAITHFUL = (44.4605, -110.8281)
AUSTIN = (30.30, -97.70)
MEMPHIS = (35.1495, -90.0490)
DENVER = (39.7392, -104.9903)
HALIFAX = (44.6488, -63.5752)
PORTLAND_OR = (45.5152, -122.6784)

NEARBY_KEYS = {
    "name", "kind", "categories", "lat", "lon", "distance_km", "distance_mi", "bearing_deg",
    "direction", "source", "wiki_path", "population", "admin1", "country", "score",
}


@pytest.fixture(scope="module")
def geo():
    g = GeoData(MAPS)
    yield g
    g.close()


# --- pure helpers ------------------------------------------------------------


def test_haversine_known_distances():
    assert haversine_km(0, 0, 1, 0) == pytest.approx(111.195, abs=0.01)  # one degree of latitude
    assert haversine_km(0, 0, 0, 180) == pytest.approx(20015.1, abs=0.5)  # half the equator
    assert haversine_km(10, 20, 10, 20) == 0.0
    # Washington Monument -> Statue of Liberty is about 327 km
    assert haversine_km(*WASHINGTON_MONUMENT, 40.6892, -74.0445) == pytest.approx(327, abs=3)


def test_initial_bearing_and_compass():
    assert initial_bearing_deg(0, 0, 1, 0) == pytest.approx(0)
    assert initial_bearing_deg(0, 0, 0, 1) == pytest.approx(90)
    assert initial_bearing_deg(0, 0, -1, 0) == pytest.approx(180)
    assert initial_bearing_deg(0, 0, 0, -1) == pytest.approx(270)
    expected = {0: "N", 22.4: "N", 22.6: "NE", 90: "E", 135: "SE", 180: "S", 225: "SW", 270: "W", 315: "NW", 359: "N", 360: "N"}
    for bearing, point in expected.items():
        assert compass_point(bearing) == point, bearing


def test_bounding_boxes_edge_cases():
    (box,) = bounding_boxes(38.9, -77.0, 16)
    assert box[0] < 38.9 < box[1] and box[2] < -77.0 < box[3]
    assert box[1] - box[0] == pytest.approx(2 * 16 / 111.195, rel=1e-6)
    # Aleutians: the circle crosses the antimeridian, so two boxes
    boxes = bounding_boxes(52.8, 179.95, 25)
    assert len(boxes) == 2 and {b[3] for b in boxes} >= {180.0} and {b[2] for b in boxes} >= {-180.0}
    # near a pole every longitude is inside
    (polar,) = bounding_boxes(89.9, 10.0, 50)
    assert polar[2:] == (-180.0, 180.0)


def test_name_key():
    assert name_key("Mt. St. Helens") == name_key("Mount Saint Helens")
    assert name_key("Montréal") == "montreal"
    assert name_key("The Dalles") == "dalles"
    assert name_key("St. John's") == name_key("St Johns") == name_key("Saint John’s") == "saint johns"


def test_fts_terms_match_saint_and_possessives():
    assert _fts_term("denver") == '"denver"*' and _fts_term("a") == '"a"'
    assert _fts_term("st") == '("st"* OR "saint")' and _fts_term("saint") == '("saint"* OR "st")'
    assert _fts_term("johns") == '("johns"* OR "john s")'
    assert _fts_term("cross") == '"cross"*'  # not "cros s"
    # a typed possessive stays one word, so it also finds the spelling without the apostrophe
    assert _fts_tokens("St. John's, MI") == ["st", "johns", "mi"] and _fts_tokens("Jo's") == ["jo", "s"]


def test_near_bonus_decays_smoothly_on_a_log_scale():
    distances = [0, 5, 25, 100, 500, 2000, 8000, 20_000]
    bonus = [_near_bonus(d, True, 50) for d in distances]
    assert bonus[0] == pytest.approx(60)
    assert all(a > b for a, b in zip(bonus, bonus[1:]))  # strictly decreasing, never flat
    assert bonus[-1] > 0  # no cutoff: the far side of the planet still ranks below the next state
    # far away, every doubling of the distance costs the same
    assert _near_bonus(4000, True, 50) - _near_bonus(8000, True, 50) == pytest.approx(6, abs=0.1)
    assert _near_bonus(2000, True, 50) - _near_bonus(4000, True, 50) == pytest.approx(6, abs=0.1)


def test_near_bonus_partial_names_share_it_by_importance():
    full = _near_bonus(10, True, 0)
    assert _near_bonus(10, True, 20) == full  # an exact town or admin name always gets all of it
    assert _near_bonus(10, False, 30) == pytest.approx(0.3 * full)  # a creek or hamlet: little
    assert _near_bonus(10, False, 90) == pytest.approx(0.9 * full)  # a city: nearly all
    assert _near_bonus(10, False, 125) == full
    assert _near_bonus(10, False, -10) == 0.0


def test_missing_databases_degrade_gracefully(tmp_path):
    g = GeoData(tmp_path)
    assert not g.available and not g.places_available and not g.wiki_available and not g
    assert g.nearby(*CN_TOWER) == []
    assert g.where_am_i(*CN_TOWER) == {}
    assert g.search_places("toronto") == []
    assert g.wiki_location("CN_Tower") is None
    assert g.info() == {"places": {"available": False}, "wiki": {"available": False}}
    g.close()


def test_pending_database_is_installed_on_open(tmp_path):
    """A rebuild that found the old file in use leaves '<name>.new'; opening installs it."""
    import sqlite3

    for name, marker in (("places.sqlite", "old"), ("places.sqlite.new", "new")):
        conn = sqlite3.connect(tmp_path / name)
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO meta VALUES ('attribution', ?)", (marker,))
        conn.commit()
        conn.close()
    g = GeoData(tmp_path)
    assert g.places_available and not g.wiki_available
    assert g.info()["places"]["attribution"] == "new"
    assert not (tmp_path / "places.sqlite.new").exists()
    g.close()


def test_invalid_coordinates_rejected(tmp_path):
    g = GeoData(tmp_path)
    with pytest.raises(ValueError):
        g.nearby(91, 0)
    with pytest.raises(ValueError):
        g.where_am_i(float("nan"), 0)


# --- where_am_i ------------------------------------------------------------------


@needs_places
def test_where_am_i_washington(geo):
    r = geo.where_am_i(*WASHINGTON_MONUMENT)
    assert (r["place"], r["admin1"], r["country"]) == ("Washington", "District of Columbia", "US")
    assert r["distance_km"] < 2
    assert r["distance_mi"] == pytest.approx(r["distance_km"] / KM_PER_MILE, abs=0.1)
    assert "Washington, District of Columbia" in r["description"]
    assert "Washington, District of Columbia" in r["description_mi"]
    assert r["direction"] in {"N", "NE", "E", "SE", "S", "SW", "W", "NW"}


@needs_places
def test_where_am_i_toronto(geo):
    r = geo.where_am_i(*CN_TOWER)
    assert (r["place"], r["admin1"], r["country"]) == ("Toronto", "Ontario", "CA")
    # the neighbourhood is reported separately, never as the primary answer
    assert r["locality"] is None or r["locality"]["name"] != "Toronto"


@needs_places
def test_where_am_i_rural_describes_distance_and_direction(geo):
    r = geo.where_am_i(*MAMMOTH_CAVE)
    assert r["admin1"] == "Kentucky" and r["population"] > 0
    assert re.fullmatch(r"\d+\.\d km (N|NE|E|SE|S|SW|W|NW) of .+, Kentucky", r["description"])
    assert re.fullmatch(r"\d+\.\d mi (N|NE|E|SE|S|SW|W|NW) of .+, Kentucky", r["description_mi"])
    # direction is FROM the place TO the query point
    b = initial_bearing_deg(r["lat"], r["lon"], *MAMMOTH_CAVE)
    assert compass_point(b) == r["direction"]


# --- nearby --------------------------------------------------------------------


@needs_places
def test_nearby_result_shape_and_order(geo):
    res = geo.nearby(*MAMMOTH_CAVE, radius_km=16, limit=15)
    assert 0 < len(res) <= 15
    for r in res:
        assert NEARBY_KEYS <= set(r)
        assert r["distance_km"] <= 16.2
        assert r["source"] in ("geonames", "wikipedia")
        assert compass_point(r["bearing_deg"]) == r["direction"]
    scores = [r["score"] for r in res]
    assert scores == sorted(scores, reverse=True)


@needs_both
def test_nearby_cn_tower(geo):
    res = geo.nearby(*CN_TOWER, radius_km=5)
    tower = [r for r in res if r["name"] == "CN Tower"]
    assert len(tower) == 1, [r["name"] for r in res]
    assert tower[0]["distance_km"] < 0.3
    assert tower[0]["wiki_path"] == "CN_Tower"


@needs_both
def test_nearby_washington_monument(geo):
    res = geo.nearby(*WASHINGTON_MONUMENT, radius_km=3)
    mon = [r for r in res if r["name"] == "Washington Monument"]
    assert len(mon) == 1, [r["name"] for r in res]
    assert mon[0]["wiki_path"] == "Washington_Monument"
    assert mon[0]["distance_km"] < 0.3


@needs_both
def test_nearby_merges_geonames_and_wikipedia_duplicates(geo):
    res = geo.nearby(*MAMMOTH_CAVE, radius_km=20)
    park = [r for r in res if name_key(r["name"]) == name_key("Mammoth Cave National Park")]
    assert len(park) == 1, [r["name"] for r in res]
    assert park[0]["source"] == "geonames"
    assert park[0]["wiki_path"] == "Mammoth_Cave_National_Park"
    assert park[0] == res[0]  # the national park is the headline attraction here


@needs_places
@pytest.mark.parametrize("kind", ["water", "towns", "nature", "history", "mountains", "culture"])
def test_nearby_kinds_filter(geo, kind):
    res = geo.nearby(*MAMMOTH_CAVE, radius_km=30, kinds=[kind], limit=10)
    assert res, kind
    assert all(kind in r["categories"] for r in res), [(r["name"], r["categories"]) for r in res]


@needs_places
def test_nearby_limit_and_all_kind(geo):
    assert len(geo.nearby(*WASHINGTON_MONUMENT, limit=5)) == 5
    assert geo.nearby(*MAMMOTH_CAVE, kinds="all", limit=5) == geo.nearby(*MAMMOTH_CAVE, limit=5)


# --- search --------------------------------------------------------------------


@needs_places
def test_search_places_basic(geo):
    top = geo.search_places("toronto")[0]
    assert (top["name"], top["admin1"], top["country"]) == ("Toronto", "Ontario", "CA")
    assert geo.search_places("") == []
    assert geo.search_places("   ") == []


@needs_places
def test_search_places_region_and_prefix(geo):
    assert geo.search_places("springfield, il")[0]["admin1"] == "Illinois"
    assert geo.search_places("Springfield, Illinois")[0]["admin1"] == "Illinois"
    assert geo.search_places("toronto on")[0]["admin1"] == "Ontario"
    names = [r["name"] for r in geo.search_places("mammoth ca", limit=5)]
    assert "Mammoth Cave National Park" in names


@needs_places
@pytest.mark.parametrize("query", ["St Johns, NL", "Saint John's, NL", "st johns nl", "St. John's"])
def test_search_places_without_apostrophe_or_abbreviation(geo, query):
    top = geo.search_places(query)[0]
    assert (top["name"], top["admin1"]) == ("St. John's", "Newfoundland and Labrador")


@needs_places
def test_search_places_near_prefers_closer_match(geo):
    res = geo.search_places("springfield", near=SPRINGFIELD_MO)
    assert res[0]["admin1"] == "Missouri"
    assert res[0]["distance_km"] < 10


@needs_places
@pytest.mark.parametrize("query, near, regions", [
    ("jackson", OLD_FAITHFUL, {"Wyoming"}),  # Jackson, WY (110 km) over Jackson, MS (2,240 km, 17x the people)
    ("jackson", MEMPHIS, {"Tennessee", "Mississippi"}),
    ("london", CN_TOWER, {"Ontario"}),
    ("paris", CN_TOWER, {"Ontario"}),
    ("georgetown", AUSTIN, {"Texas"}),
    ("salem", PORTLAND_OR, {"Oregon"}),
    ("windsor", HALIFAX, {"Nova Scotia"}),
])
def test_search_near_prefers_a_sizeable_namesake_close_by(geo, query, near, regions):
    top = geo.search_places(query, near=near)[0]
    assert name_key(top["name"]) == query and top["admin1"] in regions, top["label"]


@needs_places
def test_search_near_exact_names_beat_partial_ones(geo):
    """A museum named "Georgetown ..." next door ranks below every sizeable Georgetown."""
    res = geo.search_places("georgetown", near=AUSTIN, limit=5)
    assert [name_key(r["name"]) for r in res] == ["georgetown"] * 5, [r["label"] for r in res]
    res = geo.search_places("portland", near=PORTLAND_OR, limit=3)
    assert [name_key(r["name"]) for r in res] == ["portland"] * 3, [r["label"] for r in res]


@needs_places
@pytest.mark.parametrize("near", [DENVER, HALIFAX, MEMPHIS, PORTLAND_OR, OLD_FAITHFUL, None])
def test_search_partial_prefix_prefers_the_big_city(geo, near):
    """Creeks, parks and hamlets next door that start with "Den" do not outrank Denver."""
    top = geo.search_places("den", near=near)[0]
    assert (top["name"], top["admin1"]) == ("Denver", "Colorado"), top["label"]


@needs_places
def test_search_near_keeps_notable_partial_matches(geo):
    assert geo.search_places("mammoth", near=MEMPHIS)[0]["name"] == "Mammoth Cave National Park"
    names = [r["name"] for r in geo.search_places("richmond", near=CN_TOWER, limit=3)]
    assert "Richmond Hill" in names  # 185,000 people 25 km away, even if only a partial match


@needs_places
def test_search_near_exact_name_features_share_the_bonus_by_importance(geo):
    """Unpeopled features named exactly "Grand Canyon" 400 km away don't bury the national park."""
    res = geo.search_places("grand canyon", near=MEMPHIS)
    names = [r["name"] for r in res]
    assert "Grand Canyon National Park" in names[:2], [r["label"] for r in res[:5]]
    park = names.index("Grand Canyon National Park")
    assert not [r for r in res[:park] if "canyon" in (r["kind"] or "").lower()], [r["label"] for r in res[:park]]


@needs_places
@pytest.mark.parametrize("query", ["St. John's, MI", "St. John's, Michigan", "Saint Johns, MI"])
def test_search_typed_apostrophe_finds_the_spelling_without_one(geo, query):
    top = geo.search_places(query)[0]
    assert (name_key(top["name"]), top["admin1"]) == ("saint johns", "Michigan"), top["label"]


@needs_places
def test_search_near_keeps_region_filters(geo):
    assert geo.search_places("springfield, il", near=PORTLAND_OR)[0]["admin1"] == "Illinois"
    assert geo.search_places("georgetown, sc", near=AUSTIN)[0]["admin1"] == "South Carolina"
    assert geo.search_places("toronto on", near=OLD_FAITHFUL)[0]["admin1"] == "Ontario"


@needs_wiki
@pytest.mark.parametrize("query, near, top", [
    ("paris", OLD_FAITHFUL, 3),
    ("rome", OLD_FAITHFUL, 3),
    ("paris", None, 1),
    ("london", OLD_FAITHFUL, 5),  # untyped coordinates, but Wikipedia's primary topic
    ("berlin", None, 3),
    ("moscow", AUSTIN, 5),
])
def test_search_world_famous_places_stay_reachable(geo, query, near, top):
    path = query.capitalize()
    res = geo.search_places(query, near=near)
    assert any(r["wiki_path"] == path for r in res[:top]), [r["label"] for r in res]


@needs_both
@pytest.mark.parametrize("query, path, village", [
    ("london", "London", "London, Texas"),  # 180 people, 185 km from Austin
    ("berlin", "Berlin", "Berlin, Wisconsin"),
    ("moscow", "Moscow", "Moscow, Pennsylvania"),
])
def test_search_primary_topic_beats_small_namesakes_nearer(geo, query, path, village):
    """A capital with an untyped Wikipedia article outranks US villages a state or two away."""
    res = geo.search_places(query, near=AUSTIN)
    labels = [r["label"] for r in res]
    ranks = {r["wiki_path"]: i for i, r in enumerate(res) if r["wiki_path"]}
    small = next(i for i, lbl in enumerate(labels) if lbl.startswith(village))
    assert ranks.get(path, 99) < small, labels


@needs_wiki
def test_search_primary_topic_needs_the_exact_title(geo):
    """"The Den" (a London stadium) matches "den" only after dropping "the": no boost."""
    res = geo.search_places("den", near=HALIFAX, limit=5)
    assert res[0]["name"] == "Denver" and all(r["wiki_path"] != "The_Den" for r in res[:3])


@needs_wiki
def test_search_places_outside_north_america_uses_wikipedia(geo):
    res = geo.search_places("paris", limit=5)
    assert any(r["wiki_path"] == "Paris" for r in res), [r["label"] for r in res]


@needs_wiki
def test_wiki_location(geo):
    loc = geo.wiki_location("Statue of Liberty")
    assert loc is not None and loc["path"] == "Statue_of_Liberty"
    assert loc["lat"] == pytest.approx(40.6892, abs=0.01) and loc["lon"] == pytest.approx(-74.0445, abs=0.01)
    assert geo.wiki_location("This article does not exist 12345") is None


@needs_both
def test_info_reports_attribution(geo):
    info = geo.info()
    assert "GeoNames" in info["places"]["attribution"]
    assert "Wikipedia" in info["wiki"]["attribution"]


# --- speed -----------------------------------------------------------------------


@needs_places
def test_queries_are_fast(geo):
    """Target is < 50 ms per call; the assertion allows 2x headroom for a busy machine."""
    calls = [
        ("where_am_i DC", lambda: geo.where_am_i(*WASHINGTON_MONUMENT)),
        ("where_am_i Toronto", lambda: geo.where_am_i(*CN_TOWER)),
        ("where_am_i Manhattan", lambda: geo.where_am_i(40.7580, -73.9855)),
        ("nearby DC", lambda: geo.nearby(*WASHINGTON_MONUMENT)),
        ("nearby Manhattan", lambda: geo.nearby(40.7580, -73.9855)),
        ("nearby Toronto water", lambda: geo.nearby(*CN_TOWER, kinds=["water"])),
        ("search springfield", lambda: geo.search_places("springfield", near=SPRINGFIELD_MO)),
    ]
    slow = {}
    for label, fn in calls:
        fn()  # warm the page cache
        times = []
        for _ in range(5):
            t = time.perf_counter()
            fn()
            times.append((time.perf_counter() - t) * 1000)
        median = statistics.median(times)
        if median > 100:
            slow[label] = round(median, 1)
    assert not slow, f"slow geodata calls (median ms): {slow}"
