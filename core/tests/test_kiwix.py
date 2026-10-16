"""KiwixService's choice of which ZIM files to hand to kiwix-serve."""

import logging
import struct


def _zim(body: int = 4000) -> bytes:
    """A ZIM-shaped file: 80-byte header (magic, checksumPos), a body, then the 16-byte checksum."""
    head = bytearray(80)
    struct.pack_into("<I", head, 0, 72173914)
    struct.pack_into("<Q", head, 72, 80 + body)
    return bytes(head) + b"z" * body + b"m" * 16


def test_truncated_zim_is_not_served(paths, caplog):
    from mimi.db import Database
    from mimi.events import EventBus
    from mimi.kiwix import KiwixService, zim_complete
    from mimi.settings import SettingsStore

    paths.zim.mkdir(parents=True, exist_ok=True)
    whole = paths.zim / "wikivoyage_en_all_maxi_2026-01.zim"
    cut = paths.zim / "mdwiki_en_all_maxi_2025-11.zim"
    whole.write_bytes(_zim())
    cut.write_bytes(_zim()[:2500])
    (paths.zim / "notes.zim").write_bytes(b"not a zim file " * 100)

    assert zim_complete(whole) and not zim_complete(cut)
    svc = KiwixService(paths, SettingsStore(Database(paths.db_file)), EventBus())
    with caplog.at_level(logging.WARNING):
        assert svc.zim_files() == [whole]
    warned = [r.getMessage() for r in caplog.records if cut.name in r.getMessage()]
    assert warned and "python scripts/content.py add" in warned[0]
