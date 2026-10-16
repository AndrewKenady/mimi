"""Users, roles and sessions.

Roles:
  owner — the device owner (created during onboarding); full control.
  user  — a named person with their own chats, memories and settings.
  guest — a visitor on the shared network; temporary chats, no memory.

On the device itself (requests arriving on the loopback-only app port) the
owner is signed in automatically unless the owner enabled "require PIN".
Remote devices (phones on the Mimi network) always need a session cookie.

PIN policy (see docs/THREAT_MODEL.md):
  * A PIN is 4–8 digits. Any PIN unlocks the device's own lock screen, where
    guessing needs physical access and is rate limited.
  * Signing in over the network with a PIN needs at least NETWORK_MIN_PIN (6)
    digits. A shorter PIN is refused *before* it is checked (so the refusal
    reveals nothing) with a message saying how to choose a longer one. A
    password, or "Ask the Mimi device" (approve-on-device), always works.
  * New PIN hashes record the PIN's length, so the app can show "this PIN only
    works on the device" (``pin_network_ok``); older hashes learn it the next
    time the PIN is entered.
  * Wrong guesses are locked out per (source, account) and per account across
    all network sources; the counters live in SQLite, so restarting Core
    doesn't reset them.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass

from . import db as dbm

COLORS = ["#6EE7D2", "#8AB4FF", "#F5B971", "#F28FAD", "#B69CFF", "#7DD3A8", "#F6E27A", "#FF9E7A"]
SESSION_COOKIE = "mimi_session"
MIN_PIN, MAX_PIN = 4, 8
NETWORK_MIN_PIN = 6
SESSION_IDLE_DAYS = 30    # a session unused this long ends (checked on the server, whatever the cookie says)
SESSION_MAX_DAYS = 180    # and none lives longer than this
SHORT_PIN_MESSAGE = (f"PINs used from other devices need at least {NETWORK_MIN_PIN} digits. On the Mimi device, open "
                     f"Settings → Account and choose a longer PIN, or leave the PIN blank and choose “Ask the Mimi device”.")


def _valid_pin(pin: str) -> bool:
    return pin.isdigit() and MIN_PIN <= len(pin) <= MAX_PIN


def hash_secret(secret: str, *, pin: bool = False) -> str:
    """scrypt$<salt>$<hash>, plus $d<n> for a PIN of n digits (n ≤ 8 reveals next to nothing)."""
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(secret.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}" + (f"$d{len(secret)}" if pin else "")


def verify_secret(secret: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        return False
    try:
        parts = stored.split("$")
        if len(parts) not in (3, 4):
            return False
        salt_hex, h_hex = parts[1], parts[2]
        h = hashlib.scrypt(secret.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(h.hex(), h_hex)
    except (ValueError, TypeError):
        return False


def pin_digits(stored: str | None) -> int | None:
    """How many digits the stored PIN has, when the hash records it."""
    if not stored:
        return None
    parts = stored.split("$")
    if len(parts) == 4 and parts[3].startswith("d") and parts[3][1:].isdigit():
        return int(parts[3][1:])
    return None


def require_network_secret(secret: str) -> None:
    """Refuse a PIN too short for network sign-in, without checking it against any account.
    Call before looking the account up, so the answer is the same for every name."""
    if secret and secret.isdigit() and len(secret) < NETWORK_MIN_PIN:
        raise WeakSecretError(SHORT_PIN_MESSAGE)


@dataclass
class Ctx:
    user: dict
    session: str | None
    local: bool

    @property
    def id(self) -> str:
        return self.user["id"]

    @property
    def role(self) -> str:
        return self.user["role"]

    @property
    def is_owner(self) -> bool:
        return self.user["role"] == "owner"

    @property
    def is_guest(self) -> bool:
        return self.user["role"] == "guest"


def public_user(u: dict) -> dict:
    return {
        "id": u["id"],
        "name": u["name"],
        "role": u["role"],
        "color": u.get("color"),
        "has_pin": bool(u.get("pin_hash")),
        "has_password": bool(u.get("password_hash")),
        # False: the PIN only unlocks the device (too short for phones); None: no PIN, or not known yet
        "pin_network_ok": (None if not u.get("pin_hash") or pin_digits(u["pin_hash"]) is None
                           else pin_digits(u["pin_hash"]) >= NETWORK_MIN_PIN),  # type: ignore[operator]
        "created_at": u.get("created_at"),
    }


class AuthError(Exception):
    pass


class WeakSecretError(AuthError):
    """The secret is valid for the device but too weak for network sign-in."""


class Auth:
    def __init__(self, db: dbm.Database):
        self.db = db

    # --- users -------------------------------------------------------------
    def owner(self) -> dict | None:
        return self.db.one("SELECT * FROM users WHERE role='owner' ORDER BY created_at LIMIT 1")

    def has_owner(self) -> bool:
        return self.owner() is not None

    def get(self, user_id: str) -> dict | None:
        return self.db.one("SELECT * FROM users WHERE id=?", (user_id,))

    def by_name(self, name: str) -> dict | None:
        return self.db.one("SELECT * FROM users WHERE name=? COLLATE NOCASE", (name.strip(),))

    def list(self, include_guests: bool = False) -> list[dict]:
        q = "SELECT * FROM users" + ("" if include_guests else " WHERE role!='guest'") + " ORDER BY created_at"
        return self.db.all(q)

    def create(self, name: str, role: str, pin: str | None = None, password: str | None = None) -> dict:
        name = (name or "").strip()
        if not name or len(name) > 40:
            raise AuthError("Please choose a name (1–40 characters).")
        if role not in ("owner", "user", "guest"):
            raise AuthError("Invalid role")
        if pin is not None and pin != "" and not _valid_pin(pin):
            raise AuthError(f"PIN must be {MIN_PIN}–{MAX_PIN} digits.")
        if password is not None and password != "" and len(password) < 6:
            raise AuthError("Password must be at least 6 characters.")
        if self.by_name(name):
            if role == "guest":
                name = f"{name} ({secrets.token_hex(2)})"
            else:
                raise AuthError("That name is already taken.")
        count = self.db.scalar("SELECT COUNT(*) FROM users") or 0
        user = {
            "id": dbm.new_id("u_"),
            "name": name,
            "role": role,
            "color": COLORS[count % len(COLORS)],
            "pin_hash": hash_secret(pin, pin=True) if pin else None,
            "password_hash": hash_secret(password) if password else None,
            "created_at": dbm.now(),
        }
        self.db.execute(
            "INSERT INTO users(id,name,role,color,pin_hash,password_hash,created_at) VALUES(:id,:name,:role,:color,:pin_hash,:password_hash,:created_at)",
            user,
        )
        return self.get(user["id"])  # type: ignore[return-value]

    def update(self, user_id: str, *, name: str | None = None, pin: str | None = None, password: str | None = None, color: str | None = None) -> dict:
        u = self.get(user_id)
        if not u:
            raise AuthError("No such user")
        if name is not None:
            name = name.strip()
            other = self.by_name(name)
            if not name or (other and other["id"] != user_id):
                raise AuthError("That name is unavailable.")
            self.db.execute("UPDATE users SET name=? WHERE id=?", (name, user_id))
        if pin is not None:
            if pin == "":
                self.db.execute("UPDATE users SET pin_hash=NULL WHERE id=?", (user_id,))
            elif _valid_pin(pin):
                self.db.execute("UPDATE users SET pin_hash=? WHERE id=?", (hash_secret(pin, pin=True), user_id))
            else:
                raise AuthError(f"PIN must be {MIN_PIN}–{MAX_PIN} digits.")
        if password is not None:
            if password == "":
                self.db.execute("UPDATE users SET password_hash=NULL WHERE id=?", (user_id,))
            elif len(password) >= 6:
                self.db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_secret(password), user_id))
            else:
                raise AuthError("Password must be at least 6 characters.")
        if color is not None:
            self.db.execute("UPDATE users SET color=? WHERE id=?", (color, user_id))
        return self.get(user_id)  # type: ignore[return-value]

    def delete(self, user_id: str) -> None:
        self.db.execute("DELETE FROM users WHERE id=? AND role!='owner'", (user_id,))

    def verify(self, user: dict, secret: str, *, network: bool = False) -> bool:
        """Check a PIN or password. ``network=True`` (sign-in from another device) first refuses
        PINs shorter than NETWORK_MIN_PIN with WeakSecretError; the device's lock screen accepts them."""
        if network:
            require_network_secret(secret)
        if verify_secret(secret, user.get("pin_hash")):
            if pin_digits(user["pin_hash"]) is None and _valid_pin(secret):  # older hash: record the length
                self.db.execute("UPDATE users SET pin_hash=? WHERE id=?", (hash_secret(secret, pin=True), user["id"]))
            return True
        return verify_secret(secret, user.get("password_hash"))

    # --- sessions ----------------------------------------------------------
    def create_session(self, user_id: str, client: str = "", ip: str = "") -> str:
        token = secrets.token_urlsafe(32)
        self.db.execute(
            "INSERT INTO sessions(token,user_id,created_at,last_seen,client,ip) VALUES(?,?,?,?,?,?)",
            (token, user_id, dbm.now(), dbm.now(), client[:200], ip),
        )
        return token

    def resolve(self, token: str | None) -> dict | None:
        if not token:
            return None
        row = self.db.one("SELECT u.*, s.created_at AS s_created, s.last_seen AS s_seen FROM sessions s "
                          "JOIN users u ON u.id=s.user_id WHERE s.token=?", (token,))
        if row:
            now = dbm.now()
            created, seen = row.pop("s_created") or now, row.pop("s_seen") or row.get("created_at") or now
            if now - seen > SESSION_IDLE_DAYS * 86400 or now - created > SESSION_MAX_DAYS * 86400:
                self.end_session(token)
                return None
            self.db.execute("UPDATE sessions SET last_seen=? WHERE token=?", (dbm.now(), token))
            self.db.execute("UPDATE users SET last_seen=? WHERE id=?", (dbm.now(), row["id"]))
        return row

    def end_session(self, token: str) -> None:
        self.db.execute("DELETE FROM sessions WHERE token=?", (token,))

    def active_remote_sessions(self, since_seconds: float = 600) -> list[dict]:
        return self.db.all(
            "SELECT s.client, s.ip, s.last_seen, u.name, u.role, u.color FROM sessions s JOIN users u ON u.id=s.user_id "
            "WHERE s.ip NOT IN ('127.0.0.1','::1','') AND s.last_seen > ? ORDER BY s.last_seen DESC",
            (dbm.now() - since_seconds,),
        )


DEVICE_COOKIE = "mimi_device"
DEVICE_DAYS = 365


class KnownDevices:
    """Browsers that have signed in to an account before, so a wrong-guess flood from elsewhere on
    the network can't lock them out (see FailureGuard). Each holds a random token in a long-lived
    cookie; only its SHA-256 is stored. A token isn't a session: it grants nothing by itself, it
    only exempts its device from the account-wide guess budget (its own per-device limit stays)."""

    def __init__(self, db: dbm.Database) -> None:
        self.db = db
        db.execute("CREATE TABLE IF NOT EXISTS known_devices (token_hash TEXT NOT NULL, account TEXT NOT NULL, "
                   "created_at REAL NOT NULL, last_seen REAL NOT NULL, PRIMARY KEY (token_hash, account))")
        db.execute("DELETE FROM known_devices WHERE last_seen < ?", (time.time() - DEVICE_DAYS * 86400,))

    @staticmethod
    def _h(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def remember(self, token: str | None, account: str) -> str:
        """Mark this device as known for `account`; returns the token to (re)set in its cookie."""
        if not token or len(token) < 32:
            token = secrets.token_urlsafe(32)
        now = time.time()
        self.db.execute("INSERT INTO known_devices(token_hash, account, created_at, last_seen) VALUES(?,?,?,?) "
                        "ON CONFLICT(token_hash, account) DO UPDATE SET last_seen=excluded.last_seen",
                        (self._h(token), account.strip().lower(), now, now))
        return token

    def knows(self, token: str | None, account: str) -> bool:
        if not token:
            return False
        row = self.db.one("SELECT last_seen FROM known_devices WHERE token_hash=? AND account=?", (self._h(token), account.strip().lower()))
        return bool(row and time.time() - row["last_seen"] < DEVICE_DAYS * 86400)

    def forget_account(self, account: str) -> None:
        self.db.execute("DELETE FROM known_devices WHERE account=?", (account.strip().lower(),))


class FailureGuard:
    """Slows down guessing. After FREE_TRIES wrong PINs/passwords for a (source, account) pair,
    further tries are refused for a lockout that doubles each time (up to 15 minutes). Network
    sources also share a per-account budget (ACCOUNT_FREE_TRIES), so rotating addresses on the
    LAN doesn't buy more guesses; the device's own lock screen ("device") has its own counter, so
    guessing from the network can't lock the owner out of the device. Browsers that have signed in
    to the account before (KnownDevices, passed as known=True) skip that shared budget, so a guest
    spamming wrong PINs can't lock the owner's phones out either; they keep their own limit.

    With a database the counters are stored in SQLite (wall-clock times, each wait capped at
    MAX_LOCK so a clock change can't extend it), so restarting Core doesn't reset them. A success
    clears that source's record; records idle for a day are forgotten."""

    FREE_TRIES = 5
    ACCOUNT_FREE_TRIES = 20
    BASE_LOCK = 30.0
    MAX_LOCK = 900.0
    MAX_KEYS = 5000
    FORGET_AFTER = 86400.0
    ACCOUNT = "*"      # source used for the per-account (all network sources) counter
    DEVICE = "device"  # the device's own lock screen

    def __init__(self, db: dbm.Database | None = None) -> None:
        self._lock = threading.Lock()
        self._db = db
        self._state: dict[tuple[str, str], tuple[int, float, float]] = {}  # key -> (failures, locked_until, updated)
        if db is not None:
            db.execute("CREATE TABLE IF NOT EXISTS auth_failures (source TEXT NOT NULL, account TEXT NOT NULL, "
                       "failures INTEGER NOT NULL, locked_until REAL NOT NULL, updated_at REAL NOT NULL, "
                       "PRIMARY KEY (source, account))")
            db.execute("DELETE FROM auth_failures WHERE updated_at < ?", (time.time() - self.FORGET_AFTER,))

    # --- storage -------------------------------------------------------------
    def _get(self, key: tuple[str, str]) -> tuple[int, float, float]:
        if self._db is None:
            rec = self._state.get(key)
        else:
            row = self._db.one("SELECT failures, locked_until, updated_at FROM auth_failures WHERE source=? AND account=?", key)
            rec = (row["failures"], row["locked_until"], row["updated_at"]) if row else None
        if not rec or time.time() - rec[2] > self.FORGET_AFTER:
            return (0, 0.0, 0.0)
        return rec

    def _put(self, key: tuple[str, str], rec: tuple[int, float, float] | None) -> None:
        if self._db is None:
            if rec is None:
                self._state.pop(key, None)
            else:
                if key not in self._state and len(self._state) >= self.MAX_KEYS:
                    for k in sorted(self._state, key=lambda k: self._state[k][2])[: self.MAX_KEYS // 4]:
                        del self._state[k]  # forget the stalest records, never the newest
                self._state[key] = rec
            return
        if rec is None:
            self._db.execute("DELETE FROM auth_failures WHERE source=? AND account=?", key)
            return
        self._db.execute("INSERT INTO auth_failures(source, account, failures, locked_until, updated_at) VALUES(?,?,?,?,?) "
                         "ON CONFLICT(source, account) DO UPDATE SET failures=excluded.failures, "
                         "locked_until=excluded.locked_until, updated_at=excluded.updated_at", (*key, *rec))
        if (self._db.scalar("SELECT COUNT(*) FROM auth_failures") or 0) > self.MAX_KEYS:
            self._db.execute("DELETE FROM auth_failures WHERE rowid IN (SELECT rowid FROM auth_failures "
                             "ORDER BY updated_at LIMIT ?)", (self.MAX_KEYS // 4,))

    def _keys(self, source: str, account: str, known: bool = False) -> list[tuple[str, tuple[str, str]]]:
        acct = account.strip().lower()
        keys = [("source", (source, acct))]
        if source != self.DEVICE and not known:
            keys.append(("account", (self.ACCOUNT, acct)))
        return keys

    def _lock_for(self, kind: str, n: int) -> float:
        free = self.FREE_TRIES if kind == "source" else self.ACCOUNT_FREE_TRIES
        return 0.0 if n < free else min(self.MAX_LOCK, self.BASE_LOCK * 2 ** (n - free))

    # --- API -----------------------------------------------------------------
    def check(self, source: str, account: str, known: bool = False) -> float:
        """Seconds until another try is allowed (0 = go ahead)."""
        now = time.time()
        with self._lock:
            return max(max(0.0, min(self._get(key)[1] - now, self.MAX_LOCK)) for _, key in self._keys(source, account, known))

    def failed(self, source: str, account: str, known: bool = False) -> None:
        now = time.time()
        with self._lock:
            for kind, key in self._keys(source, account, known):
                n = self._get(key)[0] + 1
                self._put(key, (n, now + self._lock_for(kind, n), now))

    def succeeded(self, source: str, account: str) -> None:
        """Clears this source's record. The per-account budget only drains with time, so a
        right guess by the real person doesn't hand an attacker a fresh set of tries."""
        with self._lock:
            self._put((source, account.strip().lower()), None)
