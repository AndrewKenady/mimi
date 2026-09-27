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
import contextlib
import datetime as dt
import io
import ipaddress
import socket
import subprocess
import sys
from pathlib import Path

import psutil

from . import log

L = log.get("share")
RULE_NAME = "Mimi Share"
LEGACY_RULE_NAMES = ("MIMI Share",)  # rules created before the rename still count


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

    # --- certificates ------------------------------------------------------------------
    @property
    def cdir(self) -> Path:
        return self.svc.paths.certs

    def ca_paths(self) -> tuple[Path, Path]:
        return self.cdir / "mimi-ca.pem", self.cdir / "mimi-ca.key"

    def ensure_certs(self) -> tuple[Path, Path]:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

        ca_pem, ca_key_path = self.ca_paths()
        now = dt.datetime.now(dt.timezone.utc)
        if not ca_pem.exists() or not ca_key_path.exists():
            key = ec.generate_private_key(ec.SECP256R1())
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Mimi Local Authority"), x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Mimi")])
            cert = (
                x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=3650))
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False, key_encipherment=False,
                                             data_encipherment=False, key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                .sign(key, hashes.SHA256())
            )
            ca_key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            ca_pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        ca_cert = x509.load_pem_x509_certificate(ca_pem.read_bytes())
        ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), None)

        srv_pem, srv_key = self.cdir / "server.pem", self.cdir / "server.key"
        ips = ["127.0.0.1", *local_ipv4s()]
        need = True
        if srv_pem.exists() and srv_key.exists():
            try:
                c = x509.load_pem_x509_certificate(srv_pem.read_bytes())
                san = c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
                have = {str(i) for i in san.get_values_for_type(x509.IPAddress)}
                need = not set(ips) <= have or c.not_valid_after_utc < now + dt.timedelta(days=30)
            except Exception:
                need = True
        if need:
            key = ec.generate_private_key(ec.SECP256R1())
            host = socket.gethostname().lower()
            dns = ["mimi.local", "localhost", f"{host}.local"]
            san = [x509.DNSName(d) for d in dns] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
            cert = (
                x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "mimi.local")]))
                .issuer_name(ca_cert.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=397))
                .add_extension(x509.SubjectAlternativeName(san), critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
                .sign(ca_key, hashes.SHA256())
            )
            srv_key.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
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
            esc = lambda s: "".join("\\" + c if c in '\\;,:"' else c for c in s)  # noqa: E731
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
