"""Windows refuses to delete or rename files an engine has open. The content manager and the
engine installer must say "close Mimi first" and leave things consistent, not crash halfway."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"mimi_scripts_{name}", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


fetch = _load("fetch")
sys.modules["fetch"] = fetch
content = _load("content")


def test_remove_reports_files_in_use_and_keeps_their_pack(tmp_path, monkeypatch, capsys):
    books = {"wikimed": [tmp_path / "mdwiki.zim"], "ifixit": [tmp_path / "ifixit.zim"]}
    for fs in books.values():
        for f in fs:
            f.write_bytes(b"x" * 10)
    state = {"added": ["wikimed", "ifixit"]}
    monkeypatch.setattr(content, "expand", lambda names: (list(books), None))
    monkeypatch.setattr(content, "region_from", lambda args: {})
    monkeypatch.setattr(content, "removal_targets", lambda pid, region: [f for f in books[pid] if f.exists()])
    monkeypatch.setattr(content.fetch, "load_state", lambda: dict(state))
    monkeypatch.setattr(content.fetch, "save_state", lambda s: state.update(s))
    monkeypatch.setattr(content.fetch, "_rel", lambda p: p.name)
    real_unlink = Path.unlink

    def unlink(self, *a, **k):
        if self.name == "mdwiki.zim":
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", unlink)
    rc = content.cmd_remove(SimpleNamespace(names=["wikimed", "ifixit"], yes=True))
    out = capsys.readouterr().out
    assert rc == 1 and "Close Mimi" in out and "mdwiki.zim" in out
    assert not (tmp_path / "ifixit.zim").exists() and (tmp_path / "mdwiki.zim").exists()
    assert state["added"] == ["wikimed"]  # only what was really removed leaves the list


def test_engine_swap_while_running_keeps_the_working_engine(tmp_path, monkeypatch):
    import zipfile

    z = tmp_path / "e.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("llama-server.exe", b"new")
    dest = tmp_path / "bin" / "llama-vulkan"
    dest.mkdir(parents=True)
    (dest / "llama-server.exe").write_bytes(b"old")
    real_rename = Path.rename

    def rename(self, target):
        if self == dest:
            raise PermissionError(5, "Access is denied")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", rename)
    with pytest.raises(fetch.DownloadError, match="close it"):
        fetch.extract_tree(z, dest)
    assert (dest / "llama-server.exe").read_bytes() == b"old"
    assert not dest.with_name(".llama-vulkan.unpacking").exists()
