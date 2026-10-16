"""The local certificate authority: name constraints, rotation of old CAs, key at rest."""

from __future__ import annotations

import datetime as dt
import ipaddress
import os
import sys
from types import SimpleNamespace

import pytest

x509 = pytest.importorskip("cryptography.x509")
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.x509 import verification as xv  # noqa: E402
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID  # noqa: E402


@pytest.fixture()
def share(tmp_path, monkeypatch):
    from mimi import share as sh

    # a home Wi-Fi address, a public address and a carrier-grade NAT address
    monkeypatch.setattr(sh, "local_ipv4s", lambda: ["192.168.1.20", "8.8.8.8", "100.64.3.4"])
    certs = tmp_path / "certs"
    svc = SimpleNamespace(paths=SimpleNamespace(certs=certs), settings=None, events=None, auth=None)
    return sh, svc, lambda: sh.ShareService(svc)


def _load(p):
    return x509.load_pem_x509_certificate(p.read_bytes())


def _verify(ca, leaf, name):
    store = xv.Store([ca])
    subject = xv.IPAddress(ipaddress.ip_address(name)) if name[0].isdigit() else xv.DNSName(name)
    verifier = xv.PolicyBuilder().store(store).time(dt.datetime.now(dt.timezone.utc)).build_server_verifier(subject)
    return verifier.verify(leaf, [])


def _forge(ca_cert, ca_key, dns: list[str], ips: list[str] = ()):
    """What an attacker holding the CA key would mint."""
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.timezone.utc)
    san = [x509.DNSName(d) for d in dns] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    return (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, (dns or ips)[0])]))
            .issuer_name(ca_cert.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=30))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))


def test_ca_is_name_constrained_and_leaf_verifies(share):
    sh, svc, make = share
    s = make()
    srv_pem, srv_key = s.ensure_certs()
    ca = _load(s.ca_paths()[0])
    nc = ca.extensions.get_extension_for_class(x509.NameConstraints)
    assert nc.critical
    permitted = set(nc.value.permitted_subtrees)
    assert x509.DNSName("local") in permitted
    for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "127.0.0.0/8", "fc00::/7", "fe80::/10"):
        assert x509.IPAddress(ipaddress.ip_network(net)) in permitted
    assert ca.not_valid_after_utc - ca.not_valid_before_utc <= dt.timedelta(days=sh.CA_DAYS + 1)

    leaf = _load(srv_pem)  # the first certificate in the chain file
    ips = {str(i) for i in leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)}
    assert "192.168.1.20" in ips and "8.8.8.8" not in ips and "100.64.3.4" not in ips  # outside the constraints
    assert leaf.not_valid_after_utc <= ca.not_valid_after_utc
    for name in ("mimi.local", "192.168.1.20", "127.0.0.1"):
        _verify(ca, leaf, name)


def test_forged_certificate_for_a_real_site_is_rejected(share):
    sh, svc, make = share
    s = make()
    s.ensure_certs()
    ca = _load(s.ca_paths()[0])
    key = serialization.load_pem_private_key(sh.unprotect_key(s.ca_paths()[1].read_bytes()), None)
    for dns, ips, name in ((["example.com"], [], "example.com"), (["bank.example"], [], "bank.example"),
                           ([], ["8.8.8.8"], "8.8.8.8"), (["evil.local", "example.com"], [], "evil.local")):
        with pytest.raises(xv.VerificationError):
            _verify(ca, _forge(ca, key, dns, ips), name)
    _verify(ca, _forge(ca, key, ["printer.local"]), "printer.local")  # local names are fine


def _legacy_ca(certs):
    """The CA Mimi created before name constraints: ten years, unconstrained."""
    certs.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Mimi Local Authority")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(key, hashes.SHA256()))
    (certs / "mimi-ca.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (certs / "mimi-ca.key").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                          serialization.NoEncryption()))
    (certs / "server.pem").write_bytes(b"old")
    (certs / "server.key").write_bytes(b"old")
    return sh_fp(cert)


def sh_fp(cert):
    from mimi.share import fingerprint

    return fingerprint(cert)


def test_unconstrained_ca_is_rotated_with_a_notice(share):
    sh, svc, make = share
    old_fp = _legacy_ca(svc.paths.certs)
    s = make()  # startup migration
    assert not s.ca_paths()[1].exists() and not (svc.paths.certs / "server.key").exists()  # old key destroyed
    notice = s.ca_notice()
    assert notice and notice["old_fingerprint"] == old_fp and "local network" in notice["reason"]
    s.ensure_certs()
    info = s.ca_info()
    assert info["local_only"] and info["fingerprint_sha256"] != old_fp and info["notice"]
    s.ack_ca_notice()
    assert s.ca_info()["notice"] is None
    fp = info["fingerprint_sha256"]
    make().ensure_certs()  # a good CA is kept across restarts
    assert s.ca_info()["fingerprint_sha256"] == fp


def test_ca_key_is_private_at_rest(share):
    sh, svc, make = share
    s = make()
    s.ensure_certs()
    if os.name == "posix":
        assert (s.ca_paths()[1].stat().st_mode & 0o077) == 0
        assert ((svc.paths.certs / "server.key").stat().st_mode & 0o077) == 0
        assert (svc.paths.certs.stat().st_mode & 0o077) == 0
    # a key sealed with DPAPI on another (Windows) computer can't be opened here: rotate, don't crash
    if sys.platform != "win32":
        s.ca_paths()[1].write_bytes(sh._DPAPI_MAGIC + b"AAAA\n")
        assert "can't be read" in sh.ca_problem(*s.ca_paths())
        s.ensure_certs()
        assert s.ca_notice() and sh.ca_problem(*s.ca_paths()) is None


def test_leaf_names_are_sanitised():
    from mimi.share import leaf_dns_names, leaf_ips

    assert leaf_dns_names("My PC!") == ["mimi.local", "localhost", "mypc.local"]
    assert leaf_ips(["127.0.0.1", "10.1.2.3", "172.32.0.1", "172.20.0.1", "not-an-ip"]) == ["127.0.0.1", "10.1.2.3", "172.20.0.1"]
