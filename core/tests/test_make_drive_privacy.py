"""A portable drive never carries the local CA's private key, even with --include-my-data."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import make_drive


def test_personal_data_copy_leaves_the_ca_key_behind(tmp_path):
    src = tmp_path / "data"
    (src / "certs").mkdir(parents=True)
    (src / "certs" / "mimi-ca.key").write_text("private")
    (src / "uploads").mkdir()
    (src / "uploads" / "note.txt").write_text("mine")
    (src / "mimi.db").write_text("db")
    make_drive._copy_posix(src, tmp_path / "drive", None, make_drive.EXCLUDE_DIRS + make_drive.DATA_NEVER_COPIED, False)
    copied = sorted(p.relative_to(tmp_path / "drive").as_posix() for p in (tmp_path / "drive").rglob("*") if p.is_file())
    assert copied == ["mimi.db", "uploads/note.txt"]
    assert "certs" in make_drive.DATA_NEVER_COPIED
