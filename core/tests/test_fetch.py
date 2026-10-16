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
    assert fetch.pack_problem("addresses", fetch.resolve_region("uk"))
    assert fetch.pack_problem("addresses", fetch.resolve_region("canada")) is None
    routing = fetch.plan(["routing"], fetch.resolve_region("uk"))[0]
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


def test_zim_targets_match_whole_names(tmp_path):
    z = Path(os.environ["MIMI_CONTENT"]) / "zim"
    z.mkdir(parents=True)
    (z / "mdwiki_en_all_2025-11.zim").write_bytes(b"x")
    (z / "mdwiki_en_all_maxi_2025-11.zim.part").write_bytes(b"xx")
    item = next(i for i in fetch.plan(["library-essentials"], fetch.resolve_region("us")) if i.spec.get("name") == "mdwiki_en_all_maxi")
    assert not item.installed() and item.partial_bytes() == 2
    (z / "mdwiki_en_all_maxi_2025-11.zim").write_bytes(b"x")
    assert item.installed()


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
    runtimes = fetch.load_json("runtimes.json")["platforms"]
    for plat, rs in runtimes.items():
        for r in rs:
            for t in fetch.runtime_targets(r):
                assert t.relative_to(fetch.ROOT).parts[:2] == ("bin", plat)
