"""Users, roles and sessions.

Roles:
  owner — the device owner (created during onboarding); full control.
  user  — a named person with their own chats, memories and settings.
  guest — a visitor on the shared network; temporary chats, no memory.

On the device itself (requests arriving on the loopback-only app port) the
owner is signed in automatically unless the owner enabled "require PIN".
Remote devices (phones on the MIMI network) always need a session cookie.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from . import db as dbm

COLORS = ["#6EE7D2", "#8AB4FF", "#F5B971", "#F28FAD", "#B69CFF", "#7DD3A8", "#F6E27A", "#FF9E7A"]
SESSION_COOKIE = "mimi_session"


def hash_secret(secret: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(secret.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def verify_secret(secret: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        return False
    try:
        _, salt_hex, h_hex = stored.split("$")
        h = hashlib.scrypt(secret.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(h.hex(), h_hex)
    except (ValueError, TypeError):
        return False


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
        "created_at": u.get("created_at"),
    }


class AuthError(Exception):
    pass


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
        if pin is not None and pin != "" and not (pin.isdigit() and 4 <= len(pin) <= 8):
            raise AuthError("PIN must be 4–8 digits.")
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
            "pin_hash": hash_secret(pin) if pin else None,
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
            elif pin.isdigit() and 4 <= len(pin) <= 8:
                self.db.execute("UPDATE users SET pin_hash=? WHERE id=?", (hash_secret(pin), user_id))
            else:
                raise AuthError("PIN must be 4–8 digits.")
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

    def verify(self, user: dict, secret: str) -> bool:
        return verify_secret(secret, user.get("pin_hash")) or verify_secret(secret, user.get("password_hash"))

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
        row = self.db.one("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?", (token,))
        if row:
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
