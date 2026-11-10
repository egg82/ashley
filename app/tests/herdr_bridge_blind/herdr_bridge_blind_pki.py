"""Certificates for the herdr bridge blind suite: a CA the bridge trusts, clients it signed, a CA it does not trust,
and the bridge's own self-signed certificate. Keys are EC so a handshake costs next to nothing."""

import datetime
import hashlib
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

DAY = datetime.timedelta(days=1)


@dataclass(frozen=True)
class Pair:
    cert_pem: bytes
    key_pem: bytes
    key: ec.EllipticCurvePrivateKey
    cert: x509.Certificate


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _pair(
    cn: str,
    issuer: Pair | None,
    ca: bool,
    start: datetime.timedelta = -DAY,
    end: datetime.timedelta = 30 * DAY,
    sans: tuple[str, ...] = (),
) -> Pair:
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.datetime.now(datetime.UTC)
    signer = issuer.key if issuer else key
    builder = (
        x509.CertificateBuilder()
        .subject_name(_name(cn))
        .issuer_name(issuer.cert.subject if issuer else _name(cn))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now + start)
        .not_valid_after(now + end)
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    )
    if sans:
        builder = builder.add_extension(x509.SubjectAlternativeName([x509.DNSName(s) for s in sans]), critical=False)
    cert = builder.sign(signer, hashes.SHA256())
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return Pair(cert.public_bytes(serialization.Encoding.PEM), key_pem, key, cert)


@dataclass(frozen=True)
class Pki:
    ca: Pair
    other_ca: Pair
    client: Pair
    foreign_client: Pair
    expired_client: Pair
    self_signed_client: Pair
    server: Pair


def make_pki() -> Pki:
    ca = _pair("ashley-bridges", None, True)
    other = _pair("someone-elses-ca", None, True)
    return Pki(
        ca=ca,
        other_ca=other,
        client=_pair("ashley", ca, False),
        foreign_client=_pair("ashley", other, False),
        expired_client=_pair("ashley", ca, False, start=-10 * DAY, end=-2 * DAY),
        self_signed_client=_pair("ashley", None, False),
        server=_pair("bridge", None, False, sans=("localhost",)),
    )


def write_pair(pair: Pair, cert: Path, key: Path) -> None:
    cert.write_bytes(pair.cert_pem)
    key.write_bytes(pair.key_pem)
    key.chmod(0o600)


def der_fingerprint(pem: bytes) -> str:
    cert = x509.load_pem_x509_certificate(pem)
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
