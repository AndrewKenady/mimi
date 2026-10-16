"""PIN policy for network sign-in, server-side session expiry and persistent lockouts."""

from __future__ import annotations

import time

import pytest


@pytest.fixture()
def auth(paths):
    from mimi.auth import Auth
    from mimi.db import Database

    db = Database(paths.db_file)
    return Auth(db), db


def test_short_pins_unlock_the_device_but_not_network_sign_in(auth):
    from mimi.auth import WeakSecretError, public_user, require_network_secret

    a, _ = auth
    owner = a.create("Ada", "owner", pin="2468")
    assert public_user(owner)["pin_network_ok"] is False
    assert a.verify(owner, "2468")  # the device's lock screen
    with pytest.raises(WeakSecretError) as e:
        a.verify(owner, "2468", network=True)
    assert "6 digits" in str(e.value) and "Ask the Mimi device" in str(e.value)
    with pytest.raises(WeakSecretError):  # refused before any account is checked: no oracle
        require_network_secret("0000")
    require_network_secret("")  # blank is handled by the sign-in page (approve-on-device)
    require_network_secret("pass1")  # passwords aren't PINs

    a.update(owner["id"], pin="246813")
    owner = a.get(owner["id"])
    assert public_user(owner)["pin_network_ok"] is True
    assert a.verify(owner, "246813", network=True) and not a.verify(owner, "246800", network=True)

    bob = a.create("Bob", "user", password="correct horse")
    assert a.verify(bob, "correct horse", network=True)
    assert public_user(bob)["pin_network_ok"] is None


def test_legacy_pin_hash_learns_its_length(auth):
    from mimi.auth import hash_secret, pin_digits, public_user

    a, db = auth
    u = a.create("Ada", "owner")
    db.execute("UPDATE users SET pin_hash=? WHERE id=?", (hash_secret("1234"), u["id"]))  # a hash from before this change
    u = a.get(u["id"])
    assert public_user(u)["pin_network_ok"] is None
    assert a.verify(u, "1234")
    assert pin_digits(a.get(u["id"])["pin_hash"]) == 4 and a.verify(a.get(u["id"]), "1234")


def test_sessions_expire_on_the_server(auth):
    from mimi.auth import SESSION_IDLE_DAYS, SESSION_MAX_DAYS

    a, db = auth
    u = a.create("Ada", "owner")
    idle = a.create_session(u["id"], "phone", "192.168.1.5")
    old = a.create_session(u["id"], "phone", "192.168.1.6")
    fresh = a.create_session(u["id"], "phone", "192.168.1.7")
    db.execute("UPDATE sessions SET last_seen=? WHERE token=?", (time.time() - SESSION_IDLE_DAYS * 86400 - 60, idle))
    db.execute("UPDATE sessions SET created_at=? WHERE token=?", (time.time() - SESSION_MAX_DAYS * 86400 - 60, old))
    assert a.resolve(idle) is None and a.resolve(old) is None
    assert db.scalar("SELECT COUNT(*) FROM sessions WHERE token IN (?,?)", (idle, old)) == 0
    assert a.resolve(fresh)["id"] == u["id"] and "s_created" not in a.resolve(fresh)


def test_lockout_survives_a_restart(auth):
    from mimi.auth import FailureGuard

    _, db = auth
    g = FailureGuard(db)
    for _ in range(FailureGuard.FREE_TRIES):
        assert g.check("192.168.1.9", "Ada") == 0
        g.failed("192.168.1.9", "Ada")
    assert g.check("192.168.1.9", "ada") > 0
    g2 = FailureGuard(db)  # Core restarted
    assert 0 < g2.check("192.168.1.9", "ADA") <= FailureGuard.MAX_LOCK
    assert g2.check("192.168.1.10", "Ada") == 0  # another source still gets its own tries
    assert g2.check(FailureGuard.DEVICE, "owner") == 0
    g2.succeeded("192.168.1.9", "Ada")
    assert g2.check("192.168.1.9", "Ada") == 0


def test_rotating_addresses_hits_the_account_budget(auth):
    from mimi.auth import FailureGuard

    _, db = auth
    g = FailureGuard(db)
    for i in range(FailureGuard.ACCOUNT_FREE_TRIES):
        g.failed(f"10.0.0.{i}", "Ada")  # a fresh address for every guess
    assert g.check("10.0.1.1", "Ada") > 0  # a brand-new address is refused too
    assert g.check(FailureGuard.DEVICE, "Ada") == 0  # …but the device's own lock screen isn't
    assert FailureGuard(db).check("10.0.1.2", "Ada") > 0


def test_in_memory_guard_still_works():
    from mimi.auth import FailureGuard

    g = FailureGuard()
    for _ in range(FailureGuard.FREE_TRIES):
        g.failed("a", "x")
    assert g.check("a", "x") > 0 and g.check("b", "x") == 0
