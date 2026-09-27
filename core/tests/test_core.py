"""Unit and API tests for MIMI Core (no model or network needed)."""

import json

import pytest


# --------------------------------------------------------------------- settings
def test_settings_defaults_and_validation(paths):
    from mimi.db import Database
    from mimi.settings import SettingsError, SettingsStore

    s = SettingsStore(Database(paths.db_file))
    assert s.device("general").units == "imperial"
    assert len(s.device("sharing").wifi_password) >= 8
    pw = s.device("sharing").wifi_password
    assert s.device("sharing").wifi_password == pw  # stable once generated
    s.update("user", "appearance", {"accent": "#FF0000", "font_scale": 1.2}, user_id="u1")
    assert s.user("u1", "appearance").accent == "#FF0000"
    with pytest.raises(SettingsError):
        s.update("user", "appearance", {"accent": "red"}, user_id="u1")
    with pytest.raises(SettingsError):
        s.update("device", "nope", {})
    assert s.user("g1", "privacy", role="guest").memory == "off"
    s.reset("user", "appearance", user_id="u1")
    assert s.user("u1", "appearance").accent == "#6EE7D2"


# --------------------------------------------------------------------- auth
def test_auth_users_and_secrets(paths):
    from mimi.auth import Auth, AuthError
    from mimi.db import Database

    a = Auth(Database(paths.db_file))
    owner = a.create("Ada", "owner", pin="2468")
    assert a.verify(owner, "2468") and not a.verify(owner, "1111")
    with pytest.raises(AuthError):
        a.create("ada", "user", password="secret1")  # names are case-insensitive unique
    g = a.create("Guest", "guest")
    g2 = a.create("Guest", "guest")  # guests get a unique suffix
    assert g["name"] != g2["name"]
    tok = a.create_session(owner["id"], "test", "127.0.0.1")
    assert a.resolve(tok)["id"] == owner["id"]
    a.end_session(tok)
    assert a.resolve(tok) is None


# --------------------------------------------------------------------- chat helpers
def test_grounding_heuristic_and_citations():
    from mimi.chat import heuristic_title, looks_factual, sanitize_citations

    assert looks_factual("What is the tallest mountain in Canada?")
    assert looks_factual("how do I treat a burn")
    assert not looks_factual("hi")
    assert not looks_factual("write a poem about rain")
    assert not looks_factual("2+2")
    assert sanitize_citations("It is tall [1]. Named after X [3].\n\n[1] made-up reference", 1) == "It is tall [1]. Named after X."
    assert sanitize_citations("Boil it [1, 2].\n\nSources:\n[1] a", 2) == "Boil it [1, 2]."
    assert heuristic_title("hey mimi, what's the weather like on Mars in winter and summer?").startswith("What's the weather")


def test_calculator_tool_is_safe():
    import asyncio

    from mimi import tools

    st = None
    r = asyncio.run(tools.calculate({"expression": "sqrt(16) + 2^3"}, st, None))
    assert r.ok and r.text.endswith("= 12.0")
    bad = asyncio.run(tools.calculate({"expression": "__import__('os').system('x')"}, st, None))
    assert not bad.ok


def test_tool_arg_parsing():
    from mimi.tools import parse_args

    assert parse_args('{"query": "x"}') == {"query": "x"}
    assert parse_args("{'query': 'x'}") == {"query": "x"}
    assert parse_args("garbage") == {}


# --------------------------------------------------------------------- library passages
HTML = """<html><body><h1>Burn</h1><div class="mw-parser-output">
<table class="infobox"><tr><td><img src="./_assets_/a/Hand.jpg" width="300" height="180"></td></tr></table>
<p>A burn is an injury to <a class="mirror-link" href="Skin">skin</a> or other tissues caused by heat, cold or chemicals.</p>
<h2>Signs</h2><p>Superficial burns cause redness and pain lasting a few days without blisters at all.</p>
<h2>Management</h2><p>Cool the burn with running water for twenty minutes and cover it with a clean dressing.</p>
</div></body></html>"""


def test_passage_extraction_keeps_link_text_and_finds_management():
    from mimi.kiwix import extract_passage, render_reader

    title, text, image = extract_passage(HTML, "how to treat a burn", 1000, book="mdwiki_x", path="Burn")
    assert title == "Burn"
    assert "injury to skin" in text  # link text preserved
    assert "Cool the burn" in text  # intent synonyms pull in Management
    assert image == "/kiwix/content/mdwiki_x/_assets_/a/Hand.jpg"
    r = render_reader(HTML, "mdwiki_x_2025-11", "Burn", "mdwiki_x", "MDWiki")
    assert r["toc"][0]["title"] == "Signs"
    assert 'href="/library/read/mdwiki_x/Skin"' in r["html"]


# --------------------------------------------------------------------- routing
def test_polyline6_decoding():
    from mimi.routing import decode_polyline6, fmt_duration

    # "_izlhA~rlgdF_{geC~ywl@_kwzCn`{nI" is the reference example scaled to precision 6
    pts = decode_polyline6("_izlhA~rlgdF_{geC~ywl@_kwzCn`{nI")
    assert pts[0] == pytest.approx([-120.2, 38.5])
    assert pts[-1] == pytest.approx([-126.453, 43.252])
    assert fmt_duration(7953) == "2 h 13 min"
    assert fmt_duration(30) == "1 min"


def test_nmea_parsing():
    from mimi.location import parse_nmea

    fix = parse_nmea("$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A")
    assert fix["lat"] == pytest.approx(48.1173, abs=1e-4) and fix["lon"] == pytest.approx(11.5167, abs=1e-4)
    assert parse_nmea("$GPRMC,123519,V,,,,,,,230394,,,*6A") is None


# --------------------------------------------------------------------- API
def test_onboarding_and_local_auto_login(client):
    b = client.get("/api/bootstrap").json()
    assert b["needs_setup"] is True and b["me"] is None
    r = client.post("/api/auth/setup", json={"name": "Ada", "pin": "1234"})
    assert r.status_code == 200
    # a second setup is refused
    assert client.post("/api/auth/setup", json={"name": "Eve"}).status_code == 409
    me = client.get("/api/auth/me").json()
    assert me["user"]["name"] == "Ada" and me["user"]["role"] == "owner"


def test_settings_api_roundtrip(client):
    client.post("/api/auth/setup", json={"name": "Ada"})
    r = client.patch("/api/settings/user/appearance", json={"theme": "light"})
    assert r.status_code == 200 and r.json()["theme"] == "light"
    assert client.patch("/api/settings/user/appearance", json={"theme": "neon"}).status_code == 422
    exported = client.get("/api/settings/export").json()
    assert "wifi_password" not in exported["device"]["sharing"]


def test_memory_api(client):
    client.post("/api/auth/setup", json={"name": "Ada"})
    m = client.post("/api/memories", json={"text": "Vegetarian", "category": "preference"}).json()
    lst = client.get("/api/memories").json()["memories"]
    assert [x["text"] for x in lst] == ["Vegetarian"]
    client.patch(f"/api/memories/{m['id']}", json={"pinned": True})
    assert client.get("/api/memories").json()["memories"][0]["pinned"] == 1
    assert client.delete("/api/memories").json()["deleted"] == 1


def test_chat_crud_and_guest_restrictions(client):
    client.post("/api/auth/setup", json={"name": "Ada"})
    c = client.post("/api/chats", json={"title": "Trip"}).json()
    assert client.get(f"/api/chats/{c['id']}").json()["title"] == "Trip"
    client.patch(f"/api/chats/{c['id']}", json={"pinned": True})
    assert client.get("/api/chats").json()["chats"][0]["pinned"] == 1
    assert client.delete(f"/api/chats/{c['id']}").json()["ok"] is True
    # device settings are owner-only: a guest session gets 403
    from fastapi.testclient import TestClient

    guest = TestClient(client.app, base_url="http://phone")
    guest.cookies.clear()
    tok = client.app.state.svc.auth.create_session(client.app.state.svc.auth.create("Visitor", "guest")["id"])
    guest.cookies.set("mimi_session", tok)
    assert guest.patch("/api/settings/device/general", json={"units": "metric"}).status_code == 403
    assert guest.get("/api/memories").status_code == 403


def test_owner_gets_full_access_from_another_device(client):
    """Network access: a phone/laptop on the LAN signs in as the owner with a PIN."""
    client.post("/api/auth/setup", json={"name": "Ada", "pin": "2468"})
    from fastapi.testclient import TestClient

    phone = TestClient(client.app, base_url="https://phone")
    assert phone.get("/api/chats").status_code == 401
    assert phone.post("/api/auth/login", json={"name": "ada", "secret": "0000"}).status_code == 401
    r = phone.post("/api/auth/login", json={"name": "ada", "secret": "2468"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "owner"
    b = phone.get("/api/bootstrap").json()
    assert b["me"]["name"] == "Ada" and b["local"] is False
    assert all(b["features"][k] is not False for k in ("chat", "memory", "files", "settings"))
    assert phone.patch("/api/settings/device/general", json={"units": "metric"}).status_code == 200
    assert phone.get("/api/memories").status_code == 200
    # device-only actions stay on the device
    assert phone.post("/api/system/shutdown").status_code == 403


def test_unauthenticated_remote_is_rejected(client):
    client.post("/api/auth/setup", json={"name": "Ada"})
    from fastapi.testclient import TestClient

    remote = TestClient(client.app, base_url="https://phone")
    # A request that isn't on the device's loopback app port must sign in first.
    assert remote.get("/api/chats").status_code == 401
    assert remote.get("/api/bootstrap").json()["me"] is None
    # …and cannot run onboarding or shut the device down.
    assert remote.post("/api/system/shutdown").status_code == 403
