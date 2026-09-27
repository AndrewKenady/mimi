"""Approve-on-device sign-in for phones and laptops on the network.

A browser that reaches Mimi over the network asks to sign in as someone. The Mimi
device shows "Allow <browser> to sign in as <name>? Code 4821" and the owner taps
Allow or Deny on the device itself. No PIN is needed, and nobody can approve from
the network: deciding requires the owner's session on the device's loopback port.

The requester gets a random poll token and claims the session with it once approved,
so a request id seen elsewhere is useless on its own. Requests expire after two
minutes, and each network address may have only a few open at once so nobody can
flood the device with dialogs.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time

TTL = 120           # seconds a request waits for a decision
CLAIM_WINDOW = 60   # seconds an approved request can still be claimed
MAX_PER_IP = 2      # open requests per network address (older ones are replaced)
MAX_OPEN = 6        # open requests overall
MIN_INTERVAL = 3    # seconds between new requests from one address


def describe_client(user_agent: str) -> str:
    """'Safari on iPhone', 'Chrome on Android', 'Edge on Windows'... from a User-Agent."""
    ua = user_agent or ""
    device = ("iPhone" if "iPhone" in ua else "iPad" if "iPad" in ua else "Android" if "Android" in ua
              else "Mac" if "Macintosh" in ua else "Windows" if "Windows" in ua else "Linux" if "Linux" in ua
              else "ChromeOS" if "CrOS" in ua else "")
    browser = ("Edge" if "Edg/" in ua else "Opera" if "OPR/" in ua else "Samsung Internet" if "SamsungBrowser" in ua
               else "Firefox" if re.search(r"Firefox|FxiOS", ua) else "Chrome" if re.search(r"Chrome|CriOS", ua)
               else "Safari" if "Safari" in ua else "")
    if browser and device:
        return f"{browser} on {device}"
    return browser or device or "A browser"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class PairingService:
    def __init__(self, auth, events):
        self.auth = auth
        self.events = events
        self._lock = threading.Lock()
        self._reqs: dict[str, dict] = {}
        self._last_by_ip: dict[str, float] = {}

    # ------------------------------------------------------------------ helpers
    def _purge(self, now: float) -> None:
        for rid, r in list(self._reqs.items()):
            done_at = r.get("decided_at") or r["created"]
            if (r["status"] == "pending" and now - r["created"] > TTL) or (r["status"] != "pending" and now - done_at > CLAIM_WINDOW):
                if r["status"] == "pending":
                    self._announce_done(r, "expired")
                del self._reqs[rid]

    @staticmethod
    def public(r: dict) -> dict:
        return {"id": r["id"], "name": r["user_name"], "code": r["code"], "client": r["client"], "ip": r["ip"],
                "created": r["created"], "expires": r["created"] + TTL}

    def _announce_done(self, r: dict, status: str) -> None:
        owner = self.auth.owner()
        if owner:
            self.events.publish("auth.request.done", {"id": r["id"], "status": status}, user_id=owner["id"])

    # ------------------------------------------------------------------ API
    def request(self, user: dict, user_agent: str, ip: str) -> dict:
        """Open a request. Raises ValueError with a friendly message when rate-limited."""
        now = time.time()
        with self._lock:
            self._purge(now)
            if now - self._last_by_ip.get(ip, 0) < MIN_INTERVAL:
                raise ValueError("Please wait a moment before asking again.")
            mine = sorted((r for r in self._reqs.values() if r["ip"] == ip and r["status"] == "pending"), key=lambda r: r["created"])
            while len(mine) >= MAX_PER_IP:  # replace this address's oldest open request
                old = mine.pop(0)
                self._reqs.pop(old["id"], None)
                self._announce_done(old, "replaced")
            if sum(1 for r in self._reqs.values() if r["status"] == "pending") >= MAX_OPEN:
                raise ValueError("Mimi has too many sign-in requests waiting. Try again in a minute.")
            self._last_by_ip[ip] = now
            poll = secrets.token_urlsafe(24)
            r = {
                "id": secrets.token_urlsafe(12), "user_id": user["id"], "user_name": user["name"],
                "code": f"{secrets.randbelow(10000):04d}", "client": describe_client(user_agent), "ip": ip,
                "created": now, "status": "pending", "poll_hash": _hash(poll),
            }
            self._reqs[r["id"]] = r
        owner = self.auth.owner()
        if owner:
            self.events.publish("auth.request", self.public(r), user_id=owner["id"])
        return {"id": r["id"], "code": r["code"], "poll": poll, "expires_in": TTL}

    def pending(self) -> list[dict]:
        with self._lock:
            self._purge(time.time())
            return [self.public(r) for r in self._reqs.values() if r["status"] == "pending"]

    def decide(self, rid: str, approve: bool) -> str:
        with self._lock:
            self._purge(time.time())
            r = self._reqs.get(rid)
            if not r:
                return "expired"
            if r["status"] != "pending":
                return r["status"]
            r["status"] = "approved" if approve else "denied"
            r["decided_at"] = time.time()
        self._announce_done(r, r["status"])
        return r["status"]

    def claim(self, rid: str, poll: str) -> tuple[str, dict | None]:
        """Poll a request. Returns (status, user); user is set once, when an approval is claimed."""
        with self._lock:
            self._purge(time.time())
            r = self._reqs.get(rid)
            if not r or not hmac.compare_digest(r["poll_hash"], _hash(poll or "")):
                return "expired", None
            if r["status"] != "approved":
                return r["status"], None
            del self._reqs[rid]  # one-time
        user = self.auth.get(r["user_id"])
        return ("approved", user) if user else ("expired", None)
