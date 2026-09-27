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
from collections import deque

TTL = 120              # seconds a request waits for a decision
CLAIM_WINDOW = 60      # seconds an approved request can still be claimed
MAX_OPEN = 6           # open requests overall (one per network address)
ATTEMPTS_PER_MIN = 6   # sign-in asks per address per minute, counted before the account lookup
DENY_BLOCK = 600       # after Deny, that address can't ask again for 10 minutes
TRACKED_IPS = 2000     # bound on per-address bookkeeping (many spoofed/IPv6 sources)


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
    """Pending sign-in requests. All timing uses the monotonic clock, so changing the
    system time can't freeze expiries or lock phones out."""

    def __init__(self, auth, events):
        self.auth = auth
        self.events = events
        self._lock = threading.Lock()
        self._reqs: dict[str, dict] = {}
        self._attempts: dict[str, deque] = {}
        self._blocked: dict[str, float] = {}
        self._paused_until = 0.0

    # ------------------------------------------------------------------ helpers
    def _purge(self, now: float) -> None:
        for rid, r in list(self._reqs.items()):
            done_at = r.get("decided_at") or r["created"]
            if (r["status"] == "pending" and now - r["created"] > TTL) or (r["status"] != "pending" and now - done_at > CLAIM_WINDOW):
                if r["status"] == "pending":
                    self._announce_done(r, "expired")
                del self._reqs[rid]
        for ip, until in list(self._blocked.items()):
            if until <= now:
                del self._blocked[ip]

    @staticmethod
    def public(r: dict) -> dict:
        left = max(0.0, r["created"] + TTL - time.monotonic())
        return {"id": r["id"], "name": r["user_name"], "code": r["code"], "client": r["client"], "ip": r["ip"],
                "expires": time.time() + left}  # wall-clock expiry for the device's countdown

    def _announce_done(self, r: dict, status: str) -> None:
        owner = self.auth.owner()
        if owner:
            self.events.publish("auth.request.done", {"id": r["id"], "status": status}, user_id=owner["id"])

    def _refuse_if_blocked(self, ip: str, now: float) -> None:
        if self._paused_until > now:
            raise ValueError("The Mimi device isn't taking sign-in requests right now. Use your PIN, or try again later.")
        if self._blocked.get(ip, 0) > now:
            raise ValueError("The Mimi device declined. Try again in a few minutes, or use your PIN.")

    # ------------------------------------------------------------------ API
    def throttle(self, ip: str) -> None:
        """Count one sign-in ask from this address, before the account lookup, so the 404 for
        unknown names can't be probed quickly and hits and misses are limited alike."""
        now = time.monotonic()
        with self._lock:
            self._purge(now)
            self._refuse_if_blocked(ip, now)
            q = self._attempts.get(ip)
            if q is None:
                if len(self._attempts) >= TRACKED_IPS:  # forget the stalest addresses
                    for k in sorted(self._attempts, key=lambda k: self._attempts[k][-1] if self._attempts[k] else 0)[: TRACKED_IPS // 4]:
                        del self._attempts[k]
                q = self._attempts[ip] = deque(maxlen=ATTEMPTS_PER_MIN)
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= ATTEMPTS_PER_MIN:
                raise ValueError("Please wait a moment before asking again.")
            q.append(now)

    def request(self, user: dict, user_agent: str, ip: str) -> dict:
        """Open a request (one per address: a new ask replaces that address's open one).
        Raises ValueError with a friendly message when refused."""
        now = time.monotonic()
        with self._lock:
            self._purge(now)
            self._refuse_if_blocked(ip, now)
            for old in [r for r in self._reqs.values() if r["ip"] == ip and r["status"] == "pending"]:
                self._reqs.pop(old["id"], None)
                self._announce_done(old, "replaced")
            if sum(1 for r in self._reqs.values() if r["status"] == "pending") >= MAX_OPEN:
                raise ValueError("Mimi has too many sign-in requests waiting. Try again in a minute.")
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
            self._purge(time.monotonic())
            return [self.public(r) for r in self._reqs.values() if r["status"] == "pending"]

    def decide(self, rid: str, approve: bool) -> str:
        """Allow or deny. Deny also silences that address for a while and drops its other asks,
        so one device on the network can't keep a dialog over the screen."""
        now = time.monotonic()
        done: list[tuple[dict, str]] = []
        with self._lock:
            self._purge(now)
            r = self._reqs.get(rid)
            if not r:
                return "expired"
            if r["status"] != "pending":
                return r["status"]
            r["status"] = "approved" if approve else "denied"
            r["decided_at"] = now
            done.append((r, r["status"]))
            if not approve:
                self._blocked[r["ip"]] = now + DENY_BLOCK
                for other in [x for x in self._reqs.values() if x["ip"] == r["ip"] and x["status"] == "pending"]:
                    other["status"], other["decided_at"] = "denied", now
                    done.append((other, "denied"))
        for x, status in done:
            self._announce_done(x, status)
        return r["status"]

    def pause(self, seconds: float = 600) -> None:
        """Owner asked for quiet: refuse new asks for a while and decline the open ones."""
        now = time.monotonic()
        with self._lock:
            self._paused_until = now + seconds
            open_ = [r for r in self._reqs.values() if r["status"] == "pending"]
            for r in open_:
                r["status"], r["decided_at"] = "denied", now
        for r in open_:
            self._announce_done(r, "denied")

    def claim(self, rid: str, poll: str) -> tuple[str, dict | None]:
        """Poll a request. Returns (status, user); user is set once, when an approval is claimed."""
        with self._lock:
            self._purge(time.monotonic())
            r = self._reqs.get(rid)
            if not r or not hmac.compare_digest(r["poll_hash"], _hash(poll or "")):
                return "expired", None
            if r["status"] != "approved":
                return r["status"], None
            del self._reqs[rid]  # one-time
        user = self.auth.get(r["user_id"])
        return ("approved", user) if user else ("expired", None)
