"""Share Mimi with phones nearby: "Connect to Mimi" → https://mimi.local

* A local certificate authority (generated on first use) signs a certificate
  for mimi.local and the device's IP addresses. Phones can install the CA once
  from /cert so the microphone and camera work in their browser.
* A second HTTPS listener serves the same app to the local network.
* zeroconf answers mDNS queries for mimi.local — no internet or DNS server needed.
* Windows firewall and Mobile Hotspot helpers need the owner's consent (UAC).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import datetime as dt
import io
import ipaddress
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil

from . import log

L = log.get("share")
RULE_NAME = "Mimi Share"
LEGACY_RULE_NAMES = ("MIMI Share",)  # rules created before the rename still count

# --------------------------------------------------------------------------- local CA policy
# The CA is name-constrained (RFC 5280 §4.2.1.10): a phone that installs it trusts it only for
# these names and addresses, so even a stolen copy of the key can't impersonate a real website.
CA_PERMITTED_DNS = ("local", "localhost")  # "local" covers mimi.local and <hostname>.local
CA_PERMITTED_NETS = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "127.0.0.0/8",
                     "fc00::/7", "fe80::/10", "::1/128")
CA_DAYS = 730      # two years; Mimi replaces it (and says so) 30 days before it runs out
CA_RENEW_DAYS = 30
LEAF_DAYS = 397    # never longer than the CA itself
_DPAPI_MAGIC = b"MIMI-DPAPI-1\n"


def ca_name_constraints():
    from cryptography import x509

    return x509.NameConstraints(
        permitted_subtrees=[x509.DNSName(d) for d in CA_PERMITTED_DNS]
        + [x509.IPAddress(ipaddress.ip_network(n)) for n in CA_PERMITTED_NETS],
        excluded_subtrees=None,
    )


def _permitted_ip(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(a in ipaddress.ip_network(n) for n in CA_PERMITTED_NETS if ipaddress.ip_network(n).version == a.version)


def leaf_ips(ips: list[str]) -> list[str]:
    """Addresses the server certificate may name. A public or carrier-grade NAT address would put
    the certificate outside the CA's constraints and make phones reject it, so those are left out
    (phones on such a network use https://mimi.local instead)."""
    return [i for i in dict.fromkeys(ips) if _permitted_ip(i)]


def leaf_dns_names(hostname: str) -> list[str]:
    host = "".join(c for c in (hostname or "").lower() if c.isalnum() or c == "-").strip("-")[:63]
    return list(dict.fromkeys(["mimi.local", "localhost", *([f"{host}.local"] if host else [])]))


def fingerprint(cert) -> str:
    from cryptography.hazmat.primitives import hashes

    return cert.fingerprint(hashes.SHA256()).hex(":").upper()


def _name_constraints(cert):
    from cryptography import x509

    try:
        ext = cert.extensions.get_extension_for_class(x509.NameConstraints)
    except x509.ExtensionNotFound:
        return None
    return ext if ext.critical else None


def ca_problem(ca_pem: Path, ca_key: Path) -> str | None:
    """Why an existing CA must be replaced, or None when it's fine to keep."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    try:
        cert = x509.load_pem_x509_certificate(ca_pem.read_bytes())
    except Exception:
        return "the certificate file was missing or unreadable"
    ext = _name_constraints(cert)
    if ext is None:
        return "it wasn't limited to the local network"
    want = ca_name_constraints()
    if set(ext.value.permitted_subtrees or []) != set(want.permitted_subtrees or []):
        return "its local-network limits were out of date"
    now = dt.datetime.now(dt.UTC)
    if cert.not_valid_after_utc - now < dt.timedelta(days=CA_RENEW_DAYS):
        return "it was about to expire"
    if cert.not_valid_after_utc - cert.not_valid_before_utc > dt.timedelta(days=CA_DAYS + 2):
        return "it was valid for too long"
    try:
        key = serialization.load_pem_private_key(unprotect_key(ca_key.read_bytes()), None)
    except Exception:
        return "its key can't be read on this computer (was the drive moved?)"
    if key.public_key().public_numbers() != cert.public_key().public_numbers():
        return "its key didn't match"
    return None


# --------------------------------------------------------------------------- key at rest
def _restrict_dir(path: Path) -> None:
    if os.name == "posix":
        with contextlib.suppress(OSError):
            os.chmod(path, 0o700)


def _write_private(path: Path, data: bytes) -> None:
    """Write a file only the current user can read (POSIX mode 0600; on Windows the data
    folder already sits in the user's profile or on their drive)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    if os.name == "posix":
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _shred(path: Path) -> None:
    """Best-effort overwrite, then delete (SSDs may keep old blocks; this is still better than unlink)."""
    try:
        size = path.stat().st_size
    except OSError:
        return
    with contextlib.suppress(OSError):
        with open(path, "r+b") as f:
            f.write(os.urandom(size))
            f.flush()
            os.fsync(f.fileno())
    with contextlib.suppress(OSError):
        path.unlink()


def _dpapi(data: bytes, protect: bool) -> bytes:
    """Windows DPAPI (current user): the blob only opens under this Windows account on this PC."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(b: bytes):
        buf = ctypes.create_string_buffer(b, len(b))
        return Blob(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    src, _keep1 = blob(data)
    entropy, _keep2 = blob(b"Mimi local certificate authority")
    out = Blob()
    if not fn(ctypes.byref(src), "Mimi CA key" if protect else None, ctypes.byref(entropy), None, None, 0x1, ctypes.byref(out)):
        raise OSError(ctypes.get_last_error(), "DPAPI failed")  # type: ignore[attr-defined]
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def protect_key(pem: bytes) -> bytes:
    """Seal the CA key for storage: DPAPI on Windows (so a copied drive is useless without this
    Windows login), otherwise PEM in a 0600 file."""
    if sys.platform == "win32":
        try:
            return _DPAPI_MAGIC + base64.b64encode(_dpapi(pem, True)) + b"\n"
        except Exception as e:  # pragma: no cover - Windows only
            L.warning("couldn't protect the CA key with DPAPI (%s); storing it as a private file", e)
    return pem


def unprotect_key(data: bytes) -> bytes:
    if data.startswith(_DPAPI_MAGIC):
        if sys.platform != "win32":
            raise ValueError("this key is sealed to a Windows account")
        return _dpapi(base64.b64decode(data[len(_DPAPI_MAGIC):].strip()), False)
    return data


def interfaces() -> list[dict]:
    """IPv4 addresses other devices can reach, with a friendly network name."""
    out = []
    stats = psutil.net_if_stats()
    for name, addrs in psutil.net_if_addrs().items():
        st = stats.get(name)
        if st and not st.isup:
            continue
        low = name.lower()
        if any(k in low for k in ("vethernet", "wsl", "hyper-v", "virtualbox", "vmware", "loopback", "bluetooth")):
            continue
        for a in addrs:
            if a.family != socket.AF_INET:
                continue
            ip = ipaddress.ip_address(a.address)
            if ip.is_loopback or ip.is_link_local:
                continue
            kind = "hotspot" if a.address.startswith("192.168.137.") else ("wifi" if ("wi-fi" in low or "wlan" in low or "wireless" in low) else ("ethernet" if "ethernet" in low else "network"))
            label = {"hotspot": "Mimi hotspot", "wifi": "Wi-Fi", "ethernet": "Ethernet"}.get(kind, name)
            out.append({"ip": a.address, "interface": name, "kind": kind, "label": label})
    order = {"wifi": 0, "ethernet": 1, "hotspot": 2, "network": 3}
    return sorted(out, key=lambda i: (order[i["kind"]], i["ip"]))


def local_ipv4s() -> list[str]:
    return [i["ip"] for i in interfaces()]


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


class ShareService:
    def __init__(self, svc):
        self.svc = svc
        self.server = None
        self.task: asyncio.Task | None = None
        self.zc = None
        self.zc_info = None
        self.error: str | None = None
        self.hotspot_state: dict | None = None
        self.port: int | None = None
        self.redirect = None
        self.redirect_task: asyncio.Task | None = None
        self.redirect_port: int | None = None
        self._ca_info_cache: tuple | None = None
        try:  # retire an old, unconstrained CA at startup even if sharing stays off
            self._migrate_ca()
        except Exception as e:
            L.warning("certificate check failed: %s", e)

    # --- certificates ------------------------------------------------------------------
    @property
    def cdir(self) -> Path:
        return self.svc.paths.certs

    def ca_paths(self) -> tuple[Path, Path]:
        return self.cdir / "mimi-ca.pem", self.cdir / "mimi-ca.key"

    def _notice_path(self) -> Path:
        return self.cdir / "ca-notice.json"

    def _migrate_ca(self) -> None:
        """At startup: retire a CA that phones shouldn't keep trusting (made before name
        constraints, expiring, or whose key can't be read on this computer)."""
        ca_pem, ca_key = self.ca_paths()
        if not ca_pem.exists() and not ca_key.exists():
            return
        reason = ca_problem(ca_pem, ca_key)
        if reason:
            self._rotate_ca(reason)

    def _rotate_ca(self, reason: str) -> None:
        """Destroy the old CA (and the server certificate it signed) and leave a notice: phones
        that installed the old one must remove it and install the new one from /cert."""
        ca_pem, ca_key = self.ca_paths()
        old_fp = None
        with contextlib.suppress(Exception):
            from cryptography import x509

            old_fp = fingerprint(x509.load_pem_x509_certificate(ca_pem.read_bytes()))
        for f in (ca_key, self.cdir / "server.key", ca_pem, self.cdir / "server.pem"):
            _shred(f)
        self._ca_info_cache = None
        _write_private(self._notice_path(), json.dumps({"rotated_at": time.time(), "reason": reason, "old_fingerprint": old_fp,
                                                        "acknowledged": False}).encode())
        L.warning("retired the local certificate authority (%s); phones must install the new one from /cert", reason)

    def ca_notice(self) -> dict | None:
        """The pending "re-install the certificate on your phones" notice, if any."""
        try:
            n = json.loads(self._notice_path().read_text("utf-8"))
        except (OSError, ValueError):
            return None
        return None if n.get("acknowledged") else n

    def ack_ca_notice(self) -> None:
        n = self.ca_notice()
        if n:
            _write_private(self._notice_path(), json.dumps({**n, "acknowledged": True}).encode())

    def ca_info(self) -> dict | None:
        """What a person needs to check the certificate on a phone: fingerprint, expiry, scope."""
        ca_pem = self.ca_paths()[0]
        try:
            st = ca_pem.stat()
        except OSError:
            return None
        key = (st.st_mtime_ns, st.st_size)
        if self._ca_info_cache and self._ca_info_cache[0] == key:
            info = self._ca_info_cache[1]
        else:
            try:
                from cryptography import x509

                c = x509.load_pem_x509_certificate(ca_pem.read_bytes())
                info = {"name": c.subject.rfc4514_string(), "fingerprint_sha256": fingerprint(c),
                        "not_after": c.not_valid_after_utc.isoformat(), "local_only": _name_constraints(c) is not None}
            except Exception:
                return None
            self._ca_info_cache = (key, info)
        return {**info, "notice": self.ca_notice()}

    def ensure_certs(self) -> tuple[Path, Path]:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

        self.cdir.mkdir(parents=True, exist_ok=True)
        _restrict_dir(self.cdir)
        ca_pem, ca_key_path = self.ca_paths()
        now = dt.datetime.now(dt.UTC)
        problem = ca_problem(ca_pem, ca_key_path) if (ca_pem.exists() or ca_key_path.exists()) else None
        if problem:
            self._rotate_ca(problem)
        if not ca_pem.exists() or not ca_key_path.exists():
            key = ec.generate_private_key(ec.SECP256R1())
            # The date in the name tells people which "Mimi" certificate on their phone is current.
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Mimi Local Authority {now:%Y-%m-%d} (local network only)"),
                              x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Mimi")])
            cert = (
                x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
                .not_valid_after(now + dt.timedelta(days=CA_DAYS))
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False, key_encipherment=False,
                                             data_encipherment=False, key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
                # Phones that trust this CA trust it only for local names and private addresses: a copy
                # of the key can't be used to impersonate any real website.
                .add_extension(ca_name_constraints(), critical=True)
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                .sign(key, hashes.SHA256())
            )
            _write_private(ca_key_path, protect_key(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                                       serialization.NoEncryption())))
            ca_pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            self._ca_info_cache = None
            L.info("created a local certificate authority (local names and private addresses only)")
        ca_cert = x509.load_pem_x509_certificate(ca_pem.read_bytes())
        ca_key = serialization.load_pem_private_key(unprotect_key(ca_key_path.read_bytes()), None)

        srv_pem, srv_key = self.cdir / "server.pem", self.cdir / "server.key"
        ips = leaf_ips(["127.0.0.1", *local_ipv4s()])
        need = True
        if srv_pem.exists() and srv_key.exists():
            try:
                c = x509.load_pem_x509_certificate(srv_pem.read_bytes())
                c.verify_directly_issued_by(ca_cert)  # signed by the current CA (not a retired one)
                san = c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
                have = {str(i) for i in san.get_values_for_type(x509.IPAddress)}
                need = not set(ips) <= have or c.not_valid_after_utc < now + dt.timedelta(days=30)
            except Exception:
                need = True
        if need:
            key = ec.generate_private_key(ec.SECP256R1())
            dns = leaf_dns_names(socket.gethostname())
            san = [x509.DNSName(d) for d in dns] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
            cert = (
                x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "mimi.local")]))
                .issuer_name(ca_cert.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - dt.timedelta(days=1))
                .not_valid_after(min(now + dt.timedelta(days=LEAF_DAYS), ca_cert.not_valid_after_utc - dt.timedelta(hours=1)))
                .add_extension(x509.SubjectAlternativeName(san), critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=False, crl_sign=False, content_commitment=False, key_encipherment=False,
                                             data_encipherment=False, key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
                .sign(ca_key, hashes.SHA256())
            )
            # uvicorn reads this key from a file path, so it stays PEM (0600); it can only vouch for local names.
            _write_private(srv_key, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            srv_pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM) + ca_cert.public_bytes(serialization.Encoding.PEM))
            L.info("issued local certificate for %s", ", ".join(dns + ips))
        return srv_pem, srv_key

    def ca_der(self) -> bytes:
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization

        self.ensure_certs()
        return x509.load_pem_x509_certificate(self.ca_paths()[0].read_bytes()).public_bytes(serialization.Encoding.DER)

    # --- server ------------------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    async def start(self, app) -> None:
        """Serve Mimi to the local network over HTTPS (+ an HTTP → HTTPS redirect)."""
        if self.running:
            return
        import uvicorn

        cfg = self.svc.settings.device("sharing")
        cert, key = await asyncio.to_thread(self.ensure_certs)

        class _Server(uvicorn.Server):
            @contextlib.contextmanager
            def capture_signals(self):  # the main server owns signal handling
                yield

        self.error = None
        # Try the configured port, then a common alternative if it's taken or blocked.
        for port in dict.fromkeys([cfg.https_port, 8443, 9443]):
            if not _port_free(port):
                continue
            config = uvicorn.Config(app, host="0.0.0.0", port=port, ssl_certfile=str(cert), ssl_keyfile=str(key),
                                    log_config=None, access_log=False, lifespan="off", ws_ping_interval=20)
            server = _Server(config)
            task = asyncio.create_task(self._serve(server, port))
            await asyncio.sleep(0.6)
            if not task.done():
                self.server, self.task, self.port = server, task, port
                break
        else:
            self.error = f"Couldn't listen on port {cfg.https_port} or 8443. Another program may be using them."
        if self.running:
            await self._start_redirect(app)
            await asyncio.to_thread(self._mdns_start, self.port)
            L.info("sharing on https://%s", ", ".join(f"{i['ip']}:{self.port}" for i in interfaces()))
        self.svc.events.publish("share", self.status(owner=False), sticky=True)

    async def _serve(self, server, port: int) -> None:
        try:
            await server.serve()
        except SystemExit:
            self.error = f"Port {port} is busy or blocked."
        except Exception as e:
            self.error = str(e)
            L.exception("share server failed")

    async def _start_redirect(self, app) -> None:
        """Plain http://<ip>/ → the HTTPS address (so typing the bare IP just works)."""
        import uvicorn

        target_port = self.port

        async def redirect(scope, receive, send):
            if scope["type"] != "http":
                return
            host = dict(scope.get("headers") or []).get(b"host", b"").decode().split(":")[0] or "mimi.local"
            suffix = "" if target_port == 443 else f":{target_port}"
            location = f"https://{host}{suffix}{scope.get('path', '/')}"
            await send({"type": "http.response.start", "status": 307, "headers": [(b"location", location.encode()), (b"content-length", b"0")]})
            await send({"type": "http.response.body", "body": b""})

        class _Server(uvicorn.Server):
            @contextlib.contextmanager
            def capture_signals(self):
                yield

        for port in (80, 8080):
            if _port_free(port):
                srv = _Server(uvicorn.Config(redirect, host="0.0.0.0", port=port, log_config=None, access_log=False, lifespan="off"))
                task = asyncio.create_task(self._serve(srv, port))
                await asyncio.sleep(0.3)
                if not task.done():
                    self.redirect, self.redirect_task, self.redirect_port = srv, task, port
                    return

    async def stop(self) -> None:
        for srv, task in ((self.server, self.task), (self.redirect, self.redirect_task)):
            if srv:
                srv.should_exit = True
            if task:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(task, timeout=5)
        self.server = self.task = self.redirect = self.redirect_task = None
        self.port = self.redirect_port = None
        await asyncio.to_thread(self._mdns_stop)
        self.svc.events.publish("share", self.status(owner=False), sticky=True)

    def _mdns_start(self, port: int) -> None:
        try:
            from zeroconf import IPVersion, ServiceInfo, Zeroconf

            ips = [i["ip"] for i in interfaces()]
            if not ips:
                return
            self.zc = Zeroconf(ip_version=IPVersion.V4Only)
            self.zc_info = ServiceInfo(
                "_https._tcp.local.", "Mimi._https._tcp.local.", port=port,
                addresses=[socket.inet_aton(i) for i in ips], server="mimi.local.",
                properties={"path": "/", "name": "Mimi"},
            )
            self.zc.register_service(self.zc_info, allow_name_change=True)
            L.info("mDNS: mimi.local → %s", ", ".join(ips))
        except Exception as e:
            L.warning("mDNS unavailable: %s", e)
            self.zc = None

    def _mdns_stop(self) -> None:
        if self.zc:
            with contextlib.suppress(Exception):
                if self.zc_info:
                    self.zc.unregister_service(self.zc_info)
                self.zc.close()
        self.zc = None

    # --- status & QR ---------------------------------------------------------------------------
    def urls(self) -> dict:
        port = self.port or self.svc.settings.device("sharing").https_port
        suffix = "" if port == 443 else f":{port}"
        addrs = [{**i, "url": f"https://{i['ip']}{suffix}/"} for i in interfaces()]
        return {"name": f"https://mimi.local{suffix}/", "ips": [a["url"] for a in addrs], "addresses": addrs}

    def status(self, owner: bool = True) -> dict:
        cfg = self.svc.settings.device("sharing")
        out = {
            "enabled": cfg.enabled, "running": self.running, "error": self.error, "ssid": cfg.ssid, "network_mode": cfg.network_mode,
            "port": self.port or cfg.https_port, "redirect_port": self.redirect_port, "urls": self.urls(), "mdns": self.zc is not None,
            "ips": [i["ip"] for i in interfaces()],
            # fingerprint/expiry to compare on a phone; "notice" is set after the CA was replaced,
            # until the owner dismisses it (phones must remove the old certificate and install the new one)
            "ca": self.ca_info(),
        }
        if owner:
            o = self.svc.auth.owner()
            out.update(wifi_password=cfg.wifi_password, firewall=self.firewall_ok(), clients=self.svc.auth.active_remote_sessions(),
                       hotspot=self.hotspot_state, owner_can_sign_in=bool(o and (o.get("pin_hash") or o.get("password_hash"))),
                       owner_name=o["name"] if o else None)
        return out

    def qr_svg(self, kind: str) -> str:
        import qrcode
        import qrcode.image.svg

        cfg = self.svc.settings.device("sharing")
        if kind == "wifi":
            esc = lambda s: "".join("\\" + c if c in '\\;,:"' else c for c in s)
            data = f"WIFI:T:WPA;S:{esc(cfg.ssid)};P:{esc(cfg.wifi_password)};;"
        else:
            u = self.urls()
            # The IP address works everywhere; some Android phones can't resolve mimi.local.
            data = u["name"] if kind == "name" or not u["ips"] else u["ips"][0]
        img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
        buf = io.BytesIO()
        img.save(buf)
        return buf.getvalue().decode("utf-8")

    # --- Windows helpers (need consent) --------------------------------------------------------
    def firewall_ok(self) -> bool | None:
        if sys.platform != "win32":
            return None
        try:
            for name in (RULE_NAME, *LEGACY_RULE_NAMES):
                r = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule", f"name={name} (HTTPS)"], capture_output=True, text=True,
                                   timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)  # type: ignore[attr-defined]
                if r.returncode == 0 and "Enabled" in (r.stdout or ""):
                    return True
            return False
        except Exception:
            return None

    def request_firewall_rule(self) -> bool:
        """Ask Windows (UAC prompt) to allow inbound HTTPS + mDNS for Mimi on local networks."""
        if sys.platform != "win32":
            return False
        ports = ",".join(str(p) for p in dict.fromkeys([self.port or self.svc.settings.device("sharing").https_port, 8443, 80, 8080]))
        ps = (
            f"New-NetFirewallRule -DisplayName '{RULE_NAME} (HTTPS)' -Name 'MIMI-HTTPS' -Direction Inbound -Protocol TCP -LocalPort {ports} "
            f"-Action Allow -Profile Private,Public -ErrorAction SilentlyContinue; "
            f"New-NetFirewallRule -DisplayName '{RULE_NAME} (mDNS)' -Name 'MIMI-mDNS' -Direction Inbound -Protocol UDP -LocalPort 5353 "
            f"-Action Allow -Profile Private,Public -ErrorAction SilentlyContinue"
        )
        import ctypes

        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe", f'-NoProfile -WindowStyle Hidden -Command "{ps}"', None, 0)
        return rc > 32

    def hotspot(self, on: bool) -> dict:
        """Start/stop Windows Mobile Hotspot with Mimi's SSID (best effort; see docs/SHARING.md)."""
        cfg = self.svc.settings.device("sharing")
        script = HOTSPOT_PS.replace("__SSID__", cfg.ssid.replace("'", "''")).replace("__PASS__", cfg.wifi_password.replace("'", "''")).replace("__ON__", "$true" if on else "$false")
        try:
            r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, timeout=60,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            out = (r.stdout or "").strip().splitlines()
            status = out[-1] if out else (r.stderr or "unknown").strip()[:200]
        except Exception as e:
            status = f"error: {e}"
        self.hotspot_state = {"on": on, "status": status}
        return self.hotspot_state


HOTSPOT_PS = r"""
$ErrorActionPreference = 'Stop'
try {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $m = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
  $a = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' } | Select-Object -First 1
  function AwaitOp($op, $t) { $task = $m.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait(-1) | Out-Null; $task.Result }
  function AwaitAct($op) { $task = $a.Invoke($null, @($op)); $task.Wait(-1) | Out-Null }
  $profile = [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]::GetInternetConnectionProfile()
  if ($null -eq $profile) { $profile = ([Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]::GetConnectionProfiles() | Select-Object -First 1) }
  if ($null -eq $profile) { 'no-connection-profile'; exit }
  $mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]::CreateFromConnectionProfile($profile)
  if (__ON__) {
    $cfg = $mgr.GetCurrentAccessPointConfiguration(); $cfg.Ssid = '__SSID__'; $cfg.Passphrase = '__PASS__'
    AwaitAct ($mgr.ConfigureAccessPointAsync($cfg))
    $r = AwaitOp ($mgr.StartTetheringAsync()) ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult])
  } else {
    $r = AwaitOp ($mgr.StopTetheringAsync()) ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult])
  }
  [string]$r.Status
} catch { 'error: ' + $_.Exception.Message }
"""
