"""scripts/fetch.py: resumable, verified downloads; archives; manifests and tiers."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import sys
import tarfile
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"mimi_scripts_{name}", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


fetch = _load("fetch")

BLOB = os.urandom(3 * 1024 * 1024 + 123)
SHA = hashlib.sha256(BLOB).hexdigest()


class Server:
    """A tiny HTTP file server with Range support and knobs for misbehaving."""

    def __init__(self):
        self.requests: list[dict] = []
        self.cut_after: int | None = None  # first response dies after this many bytes
        self.ignore_range = False
        self.body = BLOB
        srv = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                rng = self.headers.get("Range")
                srv.requests.append({"path": self.path, "range": rng})
                body, start = srv.body, 0
                if rng and not srv.ignore_range:
                    start = int(rng.split("=")[1].split("-")[0])
                    if start >= len(body):
                        self.send_response(416)
                        self.end_headers()
                        return
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
                else:
                    self.send_response(200)
                chunk = body[start:]
                self.send_header("Content-Length", str(len(chunk)))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                if srv.cut_after is not None:
                    n, srv.cut_after = srv.cut_after, None
                    self.wfile.write(chunk[:n])
                    self.wfile.flush()
                    self.close_connection = True
                    try:
                        self.connection.shutdown(2)
                    except OSError:
                        pass
                    return
                self.wfile.write(chunk)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/file.bin"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def srv():
    s = Server()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MIMI_CONTENT", str(tmp_path / "content"))
    monkeypatch.setenv("MIMI_NO_ARIA2", "1")
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("no_proxy", "*")


def test_plain_download_is_verified_and_atomic(srv, tmp_path):
    dest = tmp_path / "out" / "file.bin"
    fetch.download(srv.url, dest, sha256=SHA, size=len(BLOB))
    assert dest.read_bytes() == BLOB
    assert not dest.with_name("file.bin.part").exists()


def test_interrupted_download_resumes_with_range(srv, tmp_path):
    srv.cut_after = 1_000_000
    dest = tmp_path / "file.bin"
    fetch.download(srv.url, dest, sha256=SHA, size=len(BLOB))
    assert dest.read_bytes() == BLOB
    assert len(srv.requests) == 2
    assert srv.requests[0]["range"] is None
    assert srv.requests[1]["range"] == "bytes=1000000-"


def test_partial_file_resumes_on_next_run(srv, tmp_path):
    dest = tmp_path / "file.bin"
    dest.with_name("file.bin.part").write_bytes(BLOB[:2_000_000])
    fetch.download(srv.url, dest, sha256=SHA, size=len(BLOB))
    assert dest.read_bytes() == BLOB
    assert srv.requests == [{"path": "/file.bin", "range": "bytes=2000000-"}]


def test_truncated_final_file_is_not_treated_as_complete(srv, tmp_path):
    # What the old fetch.py left behind: a truncated file under its final name.
    dest = tmp_path / "file.bin"
    dest.write_bytes(BLOB[:500_000])
    fetch.download(srv.url, dest, sha256=SHA, size=len(BLOB))
    assert dest.read_bytes() == BLOB
    assert srv.requests[0]["range"] == "bytes=500000-"


def test_complete_file_is_skipped_without_network(srv, tmp_path):
    dest = tmp_path / "file.bin"
    dest.write_bytes(BLOB)
    fetch.download(srv.url, dest, sha256=SHA, size=len(BLOB))
    assert srv.requests == []


def test_bad_hash_is_rejected_and_nothing_is_kept(srv, tmp_path):
    dest = tmp_path / "file.bin"
    with pytest.raises(fetch.IntegrityError):
        fetch.download(srv.url, dest, sha256="0" * 64, size=len(BLOB))
    assert not dest.exists()
    assert not dest.with_name("file.bin.part").exists()


def test_wrong_size_is_rejected(srv, tmp_path):
    srv.body = BLOB[:-10]
    dest = tmp_path / "file.bin"
    with pytest.raises(fetch.DownloadError):
        fetch.download(srv.url, dest, sha256=SHA, size=len(BLOB))
    assert not dest.exists()


def test_server_ignoring_range_restarts_cleanly(srv, tmp_path):
    srv.ignore_range = True
    dest = tmp_path / "file.bin"
    dest.with_name("file.bin.part").write_bytes(b"garbage" * 1000)
    fetch.download(srv.url, dest, sha256=SHA, size=len(BLOB))
    assert dest.read_bytes() == BLOB


def test_oversized_part_is_discarded(srv, tmp_path):
    dest = tmp_path / "file.bin"
    dest.with_name("file.bin.part").write_bytes(BLOB + b"extra")
    fetch.download(srv.url, dest, sha256=SHA, size=len(BLOB))
    assert dest.read_bytes() == BLOB


def test_falls_back_to_a_mirror(srv, tmp_path):
    dest = tmp_path / "file.bin"
    fetch.download("http://127.0.0.1:9/nothing-here", dest, sha256=SHA, size=len(BLOB), mirrors=[srv.url])
    assert dest.read_bytes() == BLOB


def test_dry_run_downloads_nothing(srv, tmp_path):
    dest = tmp_path / "file.bin"
    fetch.download(srv.url, dest, sha256=SHA, size=len(BLOB), dry=True)
    assert not dest.exists() and srv.requests == []


# --------------------------------------------------------------------------- archives
def _tar(path: Path, members: list[tuple[str, bytes | None, str | None]]) -> Path:
    with tarfile.open(path, "w:gz") as tf:
        for name, data, link in members:
            ti = tarfile.TarInfo(name)
            if link is not None:
                ti.type, ti.linkname = tarfile.SYMTYPE, link
                tf.addfile(ti)
            else:
                ti.size, ti.mode = len(data), 0o755
                tf.addfile(ti, io.BytesIO(data))
    return path


@pytest.mark.skipif(os.name == "nt", reason="symlinks")
def test_extract_tree_strips_root_and_keeps_safe_symlinks(tmp_path):
    a = _tar(tmp_path / "x.tar.gz", [("llama-b1/llama-server", b"#!bin", None), ("llama-b1/libllama.so.0.5", b"lib", None),
                                     ("llama-b1/libllama.so", None, "libllama.so.0.5"), ("llama-b1/evil", None, "../../etc/passwd")])
    dest = tmp_path / "bin" / "llama-cpu"
    fetch.extract_tree(a, dest, strip_root=True)
    assert (dest / "llama-server").read_bytes() == b"#!bin"
    assert os.access(dest / "llama-server", os.X_OK)
    assert (dest / "libllama.so").is_symlink() and (dest / "libllama.so").read_bytes() == b"lib"
    assert not (dest / "evil").exists()
    # re-extracting replaces the folder atomically
    fetch.extract_tree(a, dest, strip_root=True)
    assert sorted(p.name for p in dest.iterdir()) == ["libllama.so", "libllama.so.0.5", "llama-server"]


def test_extract_rejects_path_traversal(tmp_path):
    a = _tar(tmp_path / "bad.tar.gz", [("../outside", b"x", None)])
    with pytest.raises(fetch.DownloadError):
        fetch.extract_tree(a, tmp_path / "dest")
    assert not (tmp_path / "outside").exists()


def test_extract_files_from_zip(tmp_path):
    z = tmp_path / "p.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("README.md", "hi")
        zf.writestr("pmtiles", b"\x7fELF")
    out = tmp_path / "bin" / "pmtiles"
    out.parent.mkdir()
    fetch.extract_files(z, {"pmtiles": out})
    assert out.read_bytes() == b"\x7fELF"
    if os.name != "nt":
        assert os.access(out, os.X_OK)


# --------------------------------------------------------------------------- manifests
def test_every_static_download_is_pinned_and_hashed():
    for plat, rs in fetch.load_json("runtimes.json")["platforms"].items():
        for r in rs:
            assert len(r["sha256"]) == 64 and r["size"] > 0, (plat, r["id"])
            assert "/latest/" not in r["url"]
    for pid, p in fetch.all_packs().items():
        for it in p["items"]:
            if it["type"] == "file":
                assert "/resolve/main/" not in it["url"], (pid, it["url"])
                if it.get("sha256") is None:
                    assert pid == "addresses" and "statcan" in it["url"], f"{pid}: {it['url']} has no sha256"


def test_tiers_extend_and_dedupe_maps():
    lite, std = fetch.load_tier("lite"), fetch.load_tier("standard")
    assert set(lite["packs"]) <= set(std["packs"])
    assert std["region"] == "us-canada" and lite["region"] == "us"
    items = fetch.plan(std["packs"], fetch.resolve_region("us-canada"))
    worlds = [i for i in items if i.kind == "world"]
    tiles = [i for i in items if i.kind == "tiles"]
    assert [w.spec["maxzoom"] for w in worlds] == [11]
    assert [t.spec["maxzoom"] for t in tiles] == [14]
    assert all(p in fetch.all_packs() for p in std["packs"])


def test_every_profile_model_can_be_downloaded():
    """A profile that names a model no pack provides would silently fall back forever."""
    cfg = json.loads((ROOT / "config" / "models.json").read_text("utf-8"))
    packs = fetch.all_packs()
    shipped = {it["path"] for p in packs.values() for it in p["items"] if it["type"] == "file"}
    for prof, spec in cfg["profiles"].items():
        for mid in {m for role in ("main", "quick", "reader") for m in spec[role]} | {spec["embed"]}:
            for key in ("file", "mmproj"):  # what Core loads ("draft" is unused, see BENCHMARKS.md)
                f = cfg["models"][mid].get(key)
                assert not f or f in shipped, f"{prof}: {mid} needs {f}, which no pack downloads"
    for prof, spec in cfg["profiles"].items():
        carried = {it["path"] for it in packs[spec["pack"]]["items"]}
        assert any(cfg["models"][m]["file"] in carried for m in spec["main"]), f"{prof}: {spec['pack']} has none of its main models"


def test_plus_and_max_tiers_are_standard_plus_one_model():
    std = set(fetch.load_tier("standard")["packs"])
    for tier, pack, gb in (("plus", "llm-plus", (14, 17)), ("max", "llm-max", (20, 24))):
        t = fetch.load_tier(tier)
        assert set(t["packs"]) - std == {pack} and t["region"] == "us-canada"
        size = sum(it["size"] for it in fetch.all_packs()[pack]["items"]) / 1e9
        assert gb[0] < size < gb[1], (tier, size)


def test_lite_tier_size_is_in_budget():
    lite = fetch.load_tier("lite")
    items = fetch.plan(lite["packs"], fetch.resolve_region("uk"))
    total = sum(i.size or 0 for i in items)
    assert 10e9 < total < 20e9, total


def test_regional_items_follow_the_region():
    us = fetch.plan(["addresses"], fetch.resolve_region("us"))
    assert [i.spec.get("arg") for i in us if i.kind == "file"] == ["--tiger", "--zips"]
    build = next(i for i in us if i.kind == "build")
    args = build.build_args()
    assert args[0] == "--tiger" and "--nar" not in args
    assert not any(i.kind == "osm" for i in us)  # the US index is TIGER's, as before
    assert fetch.pack_problem("addresses", fetch.resolve_region("japan"))  # block addresses: none
    assert fetch.pack_problem("addresses", fetch.resolve_region("canada")) is None
    assert fetch.pack_problem("addresses", fetch.resolve_region("uk")) is None  # from OpenStreetMap
    routing = next(i for i in fetch.plan(["routing"], fetch.resolve_region("uk")) if i.spec.get("script") == "scripts/build_routing.py")
    assert routing.build_args()[:3] == ["--regions", "europe/united-kingdom", "europe/ireland-and-northern-ireland"]


def test_custom_bbox_region():
    r = fetch.resolve_region(bbox="-111.1,40.9,-104.0,45.1")
    assert r["bbox"] == [-111.1, 40.9, -104.0, 45.1]
    assert fetch.pack_problem("routing", r) and fetch.pack_problem("places", r)
    with pytest.raises(SystemExit):
        fetch.resolve_region(bbox="1,2,3")


def test_map_region_conflict_and_upgrade(tmp_path):
    maps = Path(os.environ["MIMI_CONTENT"]) / "maps"
    maps.mkdir(parents=True)
    (maps / "tiles.pmtiles").write_bytes(b"x")
    (maps / "tiles.json").write_text(json.dumps({"region": "us", "bounds": [-125.0, 24.3, -66.9, 49.5], "maxzoom": 13}))
    us13 = fetch.plan(["map-region"], fetch.resolve_region("us"))[0]
    us14 = fetch.plan(["map-region-detail"], fetch.resolve_region("us"))[0]
    uk13 = fetch.plan(["map-region"], fetch.resolve_region("uk"))[0]
    assert us13.installed() and not us14.installed() and us14.conflict() is None
    assert not uk13.installed() and "replaces" in uk13.conflict()
    # world.pmtiles from before world.json existed counts as zoom 0-11
    (maps / "world.pmtiles").write_bytes(b"x")
    assert fetch.plan(["world-detail"], fetch.resolve_region("us"))[0].installed()


def _zim(n_body: int) -> bytes:
    """A minimal ZIM-shaped file: its header's checksumPos says the file is 80 + n_body + 16 bytes."""
    import struct

    head = bytearray(80)
    struct.pack_into("<I", head, 0, 72173914)
    struct.pack_into("<Q", head, 72, 80 + n_body)
    return bytes(head) + b"z" * n_body + b"m" * 16


def test_zim_targets_match_whole_names(tmp_path):
    z = Path(os.environ["MIMI_CONTENT"]) / "zim"
    z.mkdir(parents=True)
    (z / "mdwiki_en_all_2025-11.zim").write_bytes(_zim(10))
    (z / "mdwiki_en_all_maxi_2025-11.zim.part").write_bytes(b"xx")
    item = next(i for i in fetch.plan(["library-essentials"], fetch.resolve_region("us")) if i.spec.get("name") == "mdwiki_en_all_maxi")
    assert not item.installed() and item.partial_bytes() == 2
    (z / "mdwiki_en_all_maxi_2025-11.zim").write_bytes(_zim(10))
    assert item.installed()


def test_truncated_zim_is_not_installed(tmp_path):
    z = Path(os.environ["MIMI_CONTENT"]) / "zim"
    z.mkdir(parents=True)
    f = z / "zimgit-water_en_2024-08.zim"
    f.write_bytes(_zim(1000)[:500])  # what the old downloader could leave behind
    item = next(i for i in fetch.plan(["library-essentials"], fetch.resolve_region("us")) if i.spec.get("name") == "zimgit-water_en")
    assert not fetch.zim_complete(f) and not item.installed()
    f.write_bytes(_zim(1000))
    assert fetch.zim_complete(f) and item.installed()
    f.write_bytes(b"not a zim file at all" * 10)
    assert not fetch.zim_complete(f)


def test_parse_metalink():
    xml = b"""<?xml version="1.0"?><metalink xmlns="urn:ietf:params:xml:ns:metalink"><file name="a_2024-01.zim">
      <size>42</size><hash type="md5">x</hash><hash type="sha-256">ab12</hash>
      <url priority="2">https://b/a.zim</url><url priority="1">https://a/a.zim</url></file></metalink>"""
    m = fetch.parse_metalink(xml)
    assert m == {"name": "a_2024-01.zim", "size": 42, "sha256": "ab12", "urls": ["https://a/a.zim", "https://b/a.zim"]}


def test_platform_keys_agree_with_core():
    from mimi.paths import platform_key

    cases = [("linux", "x86_64"), ("linux", "aarch64"), ("darwin", "arm64"), ("win32", "AMD64"), ("darwin", "x86_64")]
    for system, machine in cases:
        assert fetch.platform_key(system, machine) == platform_key(system, machine)
    assert fetch.platform_key("linux", "aarch64") == "linux-arm64"
    assert fetch.platform_key("win32", "AMD64") == "win-x64"
    assert fetch.platform_key("win32", "ARM64") == platform_key("win32", "ARM64") == "win-x64"  # x64 engines under emulation
    runtimes = fetch.load_json("runtimes.json")["platforms"]
    for plat, rs in runtimes.items():
        for r in rs:
            for t in fetch.runtime_targets(r):
                assert t.relative_to(fetch.ROOT).parts[:2] == ("bin", plat)


def _zip(tmp_path: Path, names: list[str]) -> Path:
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for n in names:
            zf.writestr(n, b"x")
    return z


def test_extract_strips_only_a_top_folder_every_member_shares(tmp_path):
    # kiwix-tools for Windows ships its files at the zip's root: "strip_root" must not empty it
    flat = _zip(tmp_path, ["kiwix-serve.exe", "icudt74.dll", "kiwix-manage.exe"])
    fetch.extract_tree(flat, tmp_path / "flat", strip_root=True)
    assert sorted(p.name for p in (tmp_path / "flat").iterdir()) == ["icudt74.dll", "kiwix-manage.exe", "kiwix-serve.exe"]
    rooted = tmp_path / "r.tar.gz"
    with tarfile.open(rooted, "w:gz") as tf:
        for n in ("kiwix-tools_linux-x86_64-3.8.1/kiwix-serve", "kiwix-tools_linux-x86_64-3.8.1/lib/libz.so"):
            ti = tarfile.TarInfo(n)
            ti.size = 1
            tf.addfile(ti, io.BytesIO(b"x"))
    fetch.extract_tree(rooted, tmp_path / "rooted", strip_root=True)
    assert (tmp_path / "rooted" / "kiwix-serve").exists() and (tmp_path / "rooted" / "lib" / "libz.so").exists()


def test_an_engine_that_did_not_unpack_is_never_marked_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "ROOT", tmp_path)
    r = {"id": "kiwix-tools", "unzip_to": "bin/x/kiwix", "exe": "kiwix-serve"}
    (tmp_path / "bin/x/kiwix").mkdir(parents=True)
    assert not fetch.runtime_ready(r)  # an empty folder is not an installed engine
    (tmp_path / "bin/x/kiwix/kiwix-serve.exe").write_text("")
    assert fetch.runtime_ready(r)


# --------------------------------------------------------------------------- one OpenStreetMap extract, several builds
class _Builds:
    """Stand-ins for the region's extract download and the builds that read it: they record what
    they were given and whether the extract was still on disk."""

    def __init__(self, monkeypatch, fail: str | None = None):
        self.calls: list[tuple] = []
        self.downloads = 0

        def fake_download(region, dest_dir=None, dry=False):
            self.downloads += 1
            p = fetch.osm_extract_path(region, dest_dir)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"pbf")
            return p

        def fake_build(item, dry):
            script = Path(item.spec["script"]).name
            self.calls.append((item.pack, script, list(item.extra_args), all(p.exists() for p in _extracts(item.region))))
            if fail == f"{item.pack}/{script}":
                raise fetch.subprocess.CalledProcessError(1, script)
            for t in item.targets():
                t.parent.mkdir(parents=True, exist_ok=True)
                t.write_text("built")

        monkeypatch.setattr(fetch, "download_osm_extract", fake_download)
        monkeypatch.setattr(fetch.Item, "_fetch_build", fake_build)


def _extracts(region: dict) -> list[Path]:
    return [fetch.osm_extract_path(r) for r in region["geofabrik"]]


def test_one_download_feeds_addresses_pois_and_routing(monkeypatch):
    uk = fetch.resolve_region("uk")
    items = fetch.plan(["addresses", "routing"], uk)  # the standard tier's order
    assert [i.kind for i in items].count("osm") == 1
    pois = next(i for i in items if i.spec.get("script") == "scripts/build_geodata.py")
    assert pois.build_args()[:4] == ["--only", "pois", "--osm", str(_extracts(uk)[0])] and str(_extracts(uk)[1]) in pois.build_args()
    b = _Builds(monkeypatch)
    assert fetch.run(fetch.todo(items)) == []
    assert b.downloads == 2  # the region's two Geofabrik files, once
    assert b.calls == [("addresses", "build_addresses.py", [], True), ("routing", "build_geodata.py", [], True),
                       ("routing", "build_routing.py", [], True)]  # routing is last: it may free the extract early
    assert not any(p.exists() for p in _extracts(uk))  # gone once the last reader is done


def test_routing_keeps_the_extract_for_a_later_build(monkeypatch):
    uk = fetch.resolve_region("uk")
    b = _Builds(monkeypatch)
    assert fetch.run(fetch.todo(fetch.plan(["routing", "addresses"], uk))) == []
    assert [c[1:3] for c in b.calls] == [("build_geodata.py", []), ("build_routing.py", ["--keep-download"]),
                                         ("build_addresses.py", [])]
    assert all(c[3] for c in b.calls) and not any(p.exists() for p in _extracts(uk))


def test_us_addresses_do_not_read_the_extract():
    us = fetch.resolve_region("us")
    items = fetch.plan(["routing", "addresses"], us)
    osm = next(i for i in items if i.kind == "osm")
    assert {Path(b.spec["script"]).name for b in items if b.kind == "build" and fetch.reads(b, osm)} == {
        "build_geodata.py", "build_routing.py"}
    assert not any(fetch.reads(b, osm) for b in items if b.pack == "addresses" and b.kind == "build")


def test_a_failed_build_keeps_the_extract_for_the_next_run(monkeypatch):
    uk = fetch.resolve_region("uk")
    b = _Builds(monkeypatch, fail="routing/build_geodata.py")
    errors = fetch.run(fetch.todo(fetch.plan(["routing", "addresses"], uk)))
    assert len(errors) == 1 and errors[0].startswith("routing:")
    assert [c[:2] for c in b.calls] == [("routing", "build_geodata.py"), ("addresses", "build_addresses.py")]
    assert all(p.exists() for p in _extracts(uk))  # routing still needs it: kept, so running again resumes
    _Builds(monkeypatch)
    todo = fetch.todo(fetch.plan(["routing", "addresses"], uk))
    assert [i.kind for i in todo] == ["osm", "build", "build"]  # the extract (on disk) and the two routing builds
    assert fetch.run(todo) == [] and not any(p.exists() for p in _extracts(uk))
    assert fetch.todo(fetch.plan(["routing", "addresses"], uk)) == []  # all built: nothing to fetch again


def test_osm_extract_download_is_md5_checked(srv, monkeypatch):
    monkeypatch.setattr(fetch, "geofabrik_url", lambda region: srv.url)
    md5 = hashlib.md5(BLOB).hexdigest()
    monkeypatch.setattr(fetch, "fetch_bytes", lambda url, timeout=120: f"{md5}  file.bin\n".encode())
    p = fetch.download_osm_extract("europe/nowhere")
    assert p == fetch.cache_dir() / "osm" / "file.bin" and p.read_bytes() == BLOB
    n = len(srv.requests)
    assert fetch.download_osm_extract("europe/nowhere") == p and len(srv.requests) == n  # on disk: no network
    p.unlink()
    monkeypatch.setattr(fetch, "fetch_bytes", lambda url, timeout=120: b"0" * 32 + b"  file.bin\n")
    with pytest.raises(fetch.IntegrityError, match="MD5"):
        fetch.download_osm_extract("europe/nowhere")
    assert not p.exists() and not p.with_name(p.name + ".part").exists()


def test_osm_item_in_the_plan():
    uk = fetch.resolve_region("uk")
    osm = next(i for i in fetch.plan(["addresses"], uk) if i.kind == "osm")
    assert osm.temporary and "united-kingdom" in osm.label and not osm.installed()
    assert [i.kind for i in fetch.plan(["routing"], fetch.resolve_region("japan"))] == ["osm", "build", "build"]
