"""The certificate the keeper's control port is served under: one self-signed pair per Bridge pod, made by the app when
it makes the pod's Secret, mounted into the pod from that Secret and trusted by the app as the only certificate it will
accept for that pod (`ashley.mail.proton_login_http`). The Secret is the authenticated channel that already carries the
pod's token, so no certificate authority is involved."""

import ssl
from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

CERT_KEY = "tls.crt"
KEY_KEY = "tls.key"
VALID_DAYS = 30


def make(now: datetime | None = None) -> dict[str, str]:
    """A new certificate and private key as PEM text, under the Secret keys `CERT_KEY` and `KEY_KEY`."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ashley-mail-bridge-keeper")])
    start = now or datetime.now(UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(start - timedelta(minutes=5))
            .not_valid_after(start + timedelta(days=VALID_DAYS))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    return {CERT_KEY: cert.public_bytes(serialization.Encoding.PEM).decode(),
            KEY_KEY: key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()).decode()}


def trusting(cert_pem: str) -> ssl.SSLContext:
    """A client context that accepts exactly this certificate, whatever name the Service is reached under."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_verify_locations(cadata=cert_pem)
    return context
