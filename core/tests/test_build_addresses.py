"""Tests for scripts/build_addresses.py on tiny synthetic inputs (never the real data files)."""

from __future__ import annotations

import csv
import gzip
import importlib.util
import io
import os
import sqlite3
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[1]
ROOT = CORE.parent
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from mimi.address_norm import VERSION, street_key  # noqa: E402
from mimi.routing import decode_polyline6  # noqa: E402

_spec = importlib.util.spec_from_file_location("build_addresses", ROOT / "scripts" / "build_addresses.py")
ba = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ba)

E6 = 1_000_000

TIGER = {
    "tiger/99001.csv": [
        "199;101;odd;Glenbrooke Ln;Autauga;AL;36066;LINESTRING(-86.418881 32.490945,-86.420629 32.490954)",
        # the two middle vertices are within 5 m of the start and are dropped
        "100;198;even;N Main St;Autauga;AL;36067;LINESTRING(-86.45 32.45,-86.45001 32.45,-86.45002 32.45,-86.46 32.45)",
        "1;99;all;North Main Street;Autauga;AL;36067;LINESTRING(-86.451 32.451,-86.452 32.451)",
        "bad;row",
        "x;99;odd;Bad Number Rd;Autauga;AL;36067;LINESTRING(-86.451 32.451,-86.452 32.451)",
    ],
    "tiger/56001.csv": ["2;10;even;Main St;Albany;WY;82070;LINESTRING(-105.59 41.31,-105.58 41.31)"],
}

ADDR_COLS = ("LOC_GUID,ADDR_GUID,APT_NO_LABEL,CIVIC_NO,CIVIC_NO_SUFFIX,OFFICIAL_STREET_NAME,OFFICIAL_STREET_TYPE,"
             "OFFICIAL_STREET_DIR,PROV_CODE,CSD_ENG_NAME,CSD_FRE_NAME,CSD_TYPE_ENG_CODE,CSD_TYPE_FRE_CODE,MAIL_STREET_NAME,"
             "MAIL_STREET_TYPE,MAIL_STREET_DIR,MAIL_MUN_NAME,MAIL_PROV_ABVN,MAIL_POSTAL_CODE,BG_DLS_LSD,BG_DLS_QTR,BG_DLS_SCTN,"
             "BG_DLS_TWNSHP,BG_DLS_RNG,BG_DLS_MRD,BG_X,BG_Y,BF_REPPOINT_X,BF_REPPOINT_Y,BU_N_CIVIC_ADD,BU_USE").split(",")
LOC_COLS = ("LOC_GUID,CSD_CODE,FED_CODE,FED_ENG_NAME,FED_FRE_NAME,ER_CODE,ER_ENG_NAME,ER_FRE_NAME,BG_LATITUDE,BG_LONGITUDE,"
            "BF_REPPOINT_LATITUDE,BF_REPPOINT_LONGITUDE").split(",")


def _addr(guid, civic, name, stype, sdir, prov, postal, apt="", suffix=""):
    rec = dict.fromkeys(ADDR_COLS, "")
    rec.update(LOC_GUID=guid, ADDR_GUID=guid + "-a" + apt, APT_NO_LABEL=apt, CIVIC_NO=civic, CIVIC_NO_SUFFIX=suffix,
               OFFICIAL_STREET_NAME=name, OFFICIAL_STREET_TYPE=stype, OFFICIAL_STREET_DIR=sdir, PROV_CODE=prov,
               MAIL_STREET_NAME=name.upper(), MAIL_STREET_TYPE=stype, MAIL_STREET_DIR=sdir, MAIL_POSTAL_CODE=postal)
    return [rec[c] for c in ADDR_COLS]


def _loc(guid, bg=None, bf=None):
    rec = dict.fromkeys(LOC_COLS, "")
    rec.update(LOC_GUID=guid, FED_ENG_NAME="Côte-ouest")
    if bg:
        rec.update(BG_LATITUDE=str(bg[0]), BG_LONGITUDE=str(bg[1]))
    if bf:
        rec.update(BF_REPPOINT_LATITUDE=str(bf[0]), BF_REPPOINT_LONGITUDE=str(bf[1]))
    return [rec[c] for c in LOC_COLS]


def _csv(header, rows, encoding="utf-8-sig") -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue().encode(encoding)


OSM = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6" generator="test">
  <node id="1" lat="41.310" lon="-105.590"/>
  <node id="2" lat="41.311" lon="-105.590"/>
  <node id="3" lat="41.312" lon="-105.590"/>
  <node id="4" lat="41.350" lon="-105.590"/>
  <node id="5" lat="41.351" lon="-105.590"/>
  <node id="6" lat="41.320" lon="-105.591"/>
  <node id="7" lat="41.321" lon="-105.591"/>
  <node id="8" lat="41.3150" lon="-105.5850">
    <tag k="addr:housenumber" v="2502"/><tag k="addr:street" v="18th Street"/>
    <tag k="addr:postcode" v="82070-1234"/><tag k="addr:state" v="WY"/>
  </node>
  <node id="9" lat="41.3160" lon="-105.5860"/>
  <node id="10" lat="41.3161" lon="-105.5860"/>
  <node id="11" lat="41.3161" lon="-105.5861"/>
  <node id="5000000000" lat="41.450" lon="-105.590"/>
  <node id="5000000001" lat="41.451" lon="-105.590"/>
  <node id="5000000002" lat="41.452" lon="-105.590"/>
  <way id="100"><nd ref="1"/><nd ref="2"/><nd ref="3"/>
    <tag k="highway" v="residential"/><tag k="name" v="Grand Avenue"/></way>
  <way id="101"><nd ref="4"/><nd ref="5"/><tag k="highway" v="primary"/><tag k="ref" v="WY 59"/></way>
  <way id="102"><nd ref="6"/><nd ref="7"/><tag k="highway" v="footway"/><tag k="name" v="Secret Path"/></way>
  <way id="103"><nd ref="9"/><nd ref="10"/><nd ref="11"/><nd ref="9"/>
    <tag k="building" v="yes"/><tag k="addr:housenumber" v="10;12"/><tag k="addr:street" v="Grand Avenue"/></way>
  <way id="104"><nd ref="5000000000"/><nd ref="5000000001"/><nd ref="5000000002"/>
    <tag k="highway" v="service"/><tag k="name" v="Far Id Road"/></way>
</osm>
"""


@pytest.fixture(scope="module")
def inputs(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("inputs")
    tiger = d / "tiger.csv.tar.gz"
    with tarfile.open(tiger, "w:gz") as tar:
        for name, rows in TIGER.items():
            data = ("from;to;interpolation;street;city;state;postcode;geometry\n" + "\n".join(rows) + "\n").encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    zips = d / "zips.csv.gz"
    with gzip.open(zips, "wt", encoding="utf-8") as f:
        f.write("postcode,lat,lon\n36066,32.47,-86.43\n82070,41.28,-105.60\n")
    nar = d / "nar.zip"
    with zipfile.ZipFile(nar, "w") as zf:
        zf.writestr("Addresses/Address_10.csv", _csv(ADDR_COLS, [
            _addr("g1", "21", "Lakeside", "TRAIL", "", "10", "A2H0H4"),
            _addr("g2", "27", "Pinchgut Lake", "RD", "", "10", "A2H 0H4"),
            _addr("g3", "6", "6", "HWY", "", "10", "A2H0H5"),
            _addr("g4", "9", "Nowhere", "ST", "", "10", "A2H0H4"),  # its location has no coordinates
            _addr("g5", "21", "Lakeside", "TRAIL", "", "10", "A2H0H4", apt="4"),
            _addr("g1", "21", "Lakeside", "TRAIL", "", "10", "A2H0H4"),  # an exact duplicate
        ]))
        zf.writestr("Locations/Location_10.csv", _csv(LOC_COLS, [
            _loc("g1", bg=(48.95, -57.95)), _loc("g2", bg=(48.951, -57.951)), _loc("g3", bf=(48.96, -57.96)),
            _loc("g4"), _loc("g5", bg=(48.95, -57.95)),
        ]))
        zf.writestr("Addresses/Address_24_part_1.csv", _csv(ADDR_COLS, [
            _addr("g6", "123", "Principale", "RUE", "", "24", "J8X1A1")]))
        part2 = _csv(ADDR_COLS, [_addr("g7", "15", "du Lac-Wilson", "CH", "", "24", "J8X1A2"),
                                 _addr("g8", "5", "Sherbrooke", "RUE", "O", "24", "J8X1A2", suffix="A")])
        part2 += _csv([], [_addr("g9", "7", "de l'Église", "RUE", "", "24", "J8X1A2")], encoding="cp1252")[1:]
        zf.writestr("Addresses/Address_24_part_2.csv", part2)
        zf.writestr("Locations/Location_24.csv", _csv(LOC_COLS, [
            _loc("g6", bg=(45.48, -75.70)), _loc("g7", bg=(45.481, -75.701)), _loc("g8", bg=(45.482, -75.702)),
            _loc("g9", bg=(45.483, -75.703))]))
        zf.writestr("Addresses/Address_35.csv", _csv(ADDR_COLS, [_addr("g10", "1", "King", "ST", "W", "35", "M5V1A1")]))
        zf.writestr("Locations/Location_35.csv", _csv(LOC_COLS, [_loc("g10", bg=(43.64, -79.39))]))
    osm = d / "tiny.osm"
    osm.write_text(OSM, encoding="utf-8")
    return {"tiger": tiger, "zips": zips, "nar": nar, "osm": osm}


def _build(inputs: dict[str, Path], out: Path, *extra: str) -> int:
    return ba.main(["--tiger", str(inputs["tiger"]), "--zips", str(inputs["zips"]), "--nar", str(inputs["nar"]),
                    "--nar-provinces", "10", "24", "--osm-roads", str(inputs["osm"]), "--osm-points", str(inputs["osm"]),
                    "--out", str(out), *extra])


@pytest.fixture(scope="module")
def built(inputs, tmp_path_factory):
    out = tmp_path_factory.mktemp("maps") / "addresses.sqlite"
    env = {v: os.environ.get(v) for v in ba.TMP_VARS}
    assert _build(inputs, out) == 0
    assert {v: os.environ.get(v) for v in ba.TMP_VARS} == env
    db = sqlite3.connect(out)
    yield out, db
    db.close()


def _street(db, key):
    rows = db.execute("SELECT id, name, cell, lat, lon, region, postcode FROM streets WHERE key = ?", (key,)).fetchall()
    assert len(rows) == 1, (key, rows)
    return rows[0]


def test_schema_meta_and_no_leftovers(built):
    out, db = built
    assert sorted(p.name for p in out.parent.iterdir()) == ["addresses.sqlite"]
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'index') AND name NOT LIKE 'sqlite_%'")}
    assert {"meta", "streets", "ranges", "points", "postcodes",
            "streets_key", "streets_base", "ranges_sid", "points_sid"} <= names
    cols = [r[1] for r in db.execute("PRAGMA table_info(ranges)")]
    assert cols == ["sid", "lo", "hi", "parity", "rev", "postcode", "geom"]
    meta = dict(db.execute("SELECT key, value FROM meta"))
    assert meta["norm_version"] == str(VERSION) and meta["built_at"]
    for table in ("streets", "ranges", "points", "postcodes"):
        assert int(meta[table]) == db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    assert "OpenStreetMap" in meta["attribution"]


def test_street_ids_and_uniqueness(built):
    _, db = built
    assert db.execute("SELECT count(*) FROM (SELECT 1 FROM streets GROUP BY key, cell HAVING count(*) > 1)").fetchone()[0] == 0
    for table in ("ranges", "points"):
        assert db.execute(f"SELECT count(*) FROM {table} WHERE sid NOT IN (SELECT id FROM streets)").fetchone()[0] == 0
    # every point lies in its street's cell
    for lat, lon, cell in db.execute("SELECT p.lat, p.lon, s.cell FROM points p JOIN streets s ON s.id = p.sid"):
        assert ba.cell_of(lat / E6, lon / E6) == cell
    assert all(base for (base,) in db.execute("SELECT base FROM streets"))


def test_tiger_ranges(built):
    _, db = built
    assert db.execute("SELECT count(*) FROM ranges").fetchone()[0] == 4  # the two malformed rows are skipped
    sid = _street(db, "glenbrooke ln")[0]
    (lo, hi, parity, rev, pc, geom), = db.execute("SELECT lo, hi, parity, rev, postcode, geom FROM ranges WHERE sid = ?", (sid,))
    assert (lo, hi, parity, rev, pc) == (101, 199, 1, 1, "36066")
    assert decode_polyline6(geom) == [[-86.418881, 32.490945], [-86.420629, 32.490954]]

    sid, name, _, _, _, region, _ = _street(db, "n main st")  # "N Main St" and "North Main Street" share a key and cell
    assert (name, region) == ("North Main Street", "al")
    rows = db.execute("SELECT lo, hi, parity, rev, geom FROM ranges WHERE sid = ? ORDER BY lo", (sid,)).fetchall()
    assert [r[:4] for r in rows] == [(1, 99, 0, 0), (100, 198, 2, 0)]
    assert decode_polyline6(rows[1][4]) == [[-86.45, 32.45], [-86.46, 32.45]]  # near-duplicate vertices dropped


def test_polyline_and_simplify_round_trip():
    line = [(32.45 + i * 0.0003, -86.45 - (i % 3) * 0.0002) for i in range(12)]
    kept, mid = ba.simplify_line(line)
    assert kept[0] == line[0] and kept[-1] == line[-1] and len(kept) == len(line)
    assert line[0][0] < mid[0] < line[-1][0]
    enc = ba.encode_polyline((round(a * E6), round(b * E6)) for a, b in kept)
    decoded = [v for lon, lat in decode_polyline6(enc) for v in (lat, lon)]
    assert decoded == pytest.approx([v for p in kept for v in p], abs=1e-6)


def test_nar_points(built):
    _, db = built
    sid = _street(db, "lakeside trl")[0]
    pts = db.execute("SELECT numtext, unit, lat, lon, postcode, source FROM points WHERE sid = ? ORDER BY unit", (sid,)).fetchall()
    assert pts == [("21", None, 48950000, -57950000, "A2H0H4", "nar"), ("21", "4", 48950000, -57950000, "A2H0H4", "nar")]
    assert _street(db, "pinchgut lake rd")[6] == "A2H0H4"  # "A2H 0H4" normalized
    hwy = _street(db, "hwy 6")  # "6 HWY" in the register
    assert (hwy[1], hwy[3], hwy[4]) == ("Highway 6", 48960000, -57960000)  # building-footprint point as the fallback
    assert not db.execute("SELECT 1 FROM streets WHERE key = 'nowhere st'").fetchall()
    assert not db.execute("SELECT 1 FROM streets WHERE region = 'on'").fetchall()  # province 35 wasn't asked for


def test_nar_french_names_and_encodings(built):
    _, db = built
    assert _street(db, "rue principale")[1:6:4] == ("Rue Principale", "qc")
    assert _street(db, street_key("Chemin du Lac-Wilson"))[1] == "Chemin du Lac-Wilson"
    sid, name, *_ = _street(db, street_key("Rue Sherbrooke Ouest"))
    assert name == "Rue Sherbrooke Ouest"
    assert db.execute("SELECT numtext FROM points WHERE sid = ?", (sid,)).fetchall() == [("5A",)]
    assert _street(db, street_key("Rue de l'Église"))[1] == "Rue de l'Église"  # a cp1252 line in a UTF-8 file


def test_osm(built):
    _, db = built
    grand = _street(db, "grand ave")
    assert (grand[1], grand[3], grand[4], grand[5]) == ("Grand Avenue", 41311000, -105590000, "wy")  # the middle node
    assert sorted(db.execute("SELECT numtext, lat, lon, source FROM points WHERE sid = ?", (grand[0],)).fetchall()) == [
        ("10", 41316000, -105586000, "osm"), ("12", 41316000, -105586000, "osm")]  # a building's first node
    assert _street(db, "hwy 59")[1] == "WY 59"  # from ref
    assert _street(db, "far id rd")[5] == "wy"  # node ids past the first IdFilter window; region from the next cell
    assert not db.execute("SELECT 1 FROM streets WHERE key = 'secret path'").fetchall()
    sid, _, _, _, _, region, pc = _street(db, "18th st")
    assert (region, pc) == ("wy", "82070")
    assert db.execute("SELECT numtext, source FROM points WHERE sid = ?", (sid,)).fetchall() == [("2502", "osm")]


def test_postcodes(built):
    _, db = built
    pc = {r[0]: r[1:] for r in db.execute("SELECT code, lat, lon, region FROM postcodes")}
    assert pc["36066"] == (32470000, -86430000, "al")
    assert pc["82070"][2] == "wy"
    assert pc["36067"][2] == "al"  # only in TIGER: the mean of its segments
    assert pc["A2H0H4"] == (48950333, -57950333, "nl")
    assert pc["A2H"][2] == "nl" and pc["J8X"][2] == "qc" and "J8X1A2" in pc


def test_failed_build_keeps_the_old_index(inputs, tmp_path):
    out = tmp_path / "addresses.sqlite"
    out.write_bytes(b"old index")
    bad = tmp_path / "bad.tar.gz"
    bad.write_bytes(b"not a tarball")
    with pytest.raises(tarfile.TarError):
        ba.main(["--tiger", str(bad), "--zips", str(inputs["zips"]), "--out", str(out)])
    assert out.read_bytes() == b"old index"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["addresses.sqlite", "bad.tar.gz"]


def test_nar_street_names():
    assert ba.nar_street("Lakeside", "TRAIL", "", False) == "Lakeside Trail"
    assert ba.nar_street("KING", "ST", "W", False) == "King St W"
    assert ba.nar_street("Principale", "RUE", "", True) == "Rue Principale"
    assert ba.nar_street("Saint-Laurent", "BOUL", "", True) == "Boulevard Saint-Laurent"
    assert ba.nar_street("Centre", "PL", "", False) == "Centre Pl"
    assert ba.nar_street("Centre", "PL", "", True) == "Place Centre"
    assert ba.nar_street("DU LAC-WILSON", "CH", "", True) == "Chemin du Lac-Wilson"
    assert ba.nar_street("401", "HWY", "", False) == "Highway 401"
    assert street_key(ba.nar_street("Sherbrooke", "RUE", "O", True)) == street_key("Rue Sherbrooke Ouest")


@pytest.mark.parametrize("combine_max", [None, 1], ids=["combined", "flushed"])
def test_street_in_two_states_in_one_cell(tmp_path, monkeypatch, combine_max):
    """State St in Bristol is the TN/VA line: the street keeps no region, so each side's numbers
    are found under its own state (whether the combiner or the final merge sees both)."""
    if combine_max:
        monkeypatch.setattr(ba, "COMBINE_MAX", combine_max)
    tiger = tmp_path / "tiger.tar.gz"
    rows = ["101;199;odd;State St;Sullivan;TN;37620;LINESTRING(-82.19 36.5952,-82.18 36.5952)",
            "100;198;even;State St;Bristol;VA;24201;LINESTRING(-82.19 36.5948,-82.18 36.5948)",
            "1;99;odd;Volunteer Pkwy;Sullivan;TN;37620;LINESTRING(-82.19 36.58,-82.18 36.58)"]
    with tarfile.open(tiger, "w:gz") as tar:
        data = ("from;to;interpolation;street;city;state;postcode;geometry\n" + "\n".join(rows) + "\n").encode()
        info = tarfile.TarInfo("tiger/47163.csv")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    zips = tmp_path / "zips.csv.gz"
    with gzip.open(zips, "wt", encoding="utf-8") as f:
        f.write("postcode,lat,lon\n37620,36.58,-82.18\n24201,36.61,-82.18\n")
    out = tmp_path / "maps" / "addresses.sqlite"
    out.parent.mkdir()
    assert ba.main(["--tiger", str(tiger), "--zips", str(zips), "--out", str(out)]) == 0
    db = sqlite3.connect(out)
    try:
        assert _street(db, "state st")[5] is None  # not painted over by the cell's TN majority either
        assert _street(db, "volunteer pkwy")[5] == "tn"
        assert db.execute("SELECT count(*) FROM streets WHERE region = ''").fetchone()[0] == 0
    finally:
        db.close()
    from mimi.address import AddressIndex
    ix = AddressIndex(out)
    try:
        va = ix.search("150 State St, VA")
        assert (va[0]["name"], va[0]["precision"], va[0]["admin1"]) == ("150 State St", "interpolated", "Virginia")
        tn = ix.search("151 State St, TN")
        assert (tn[0]["name"], tn[0]["precision"], tn[0]["admin1"]) == ("151 State St", "interpolated", "Tennessee")
    finally:
        ix.close()
