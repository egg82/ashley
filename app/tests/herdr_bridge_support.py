"""Shared by the herdr bridge suites: the answers captured from the real `herdr` CLI (tests/herdr_captured, see its
README), a Runner that replays them and records what the bridge asked, and a bridge built over a state directory."""

import datetime
import hashlib
import json
import threading
import time
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from herdr_bridge.api import Api, Request, Response
from herdr_bridge.auth import PERSON_FILE, TOKEN_FILE, Auth, token_digest
from herdr_bridge.config import Config
from herdr_bridge.files import Limits
from herdr_bridge.herdr import Herdr
from herdr_bridge.install import fingerprint
from herdr_bridge.ledger import Ledger
from herdr_bridge.runner import Outcome
from herdr_bridge.server import make_server
from herdr_bridge.sessions import Sessions
from herdr_bridge.transcripts import Transcripts

CAPTURED = Path(__file__).resolve().parent / "herdr_captured"
TOKEN = "t0ken-for-tests"
PERSON = "7"
DEFAULT_ROOT = "/tmp"

# Session ids in the captured list, by what the capture shows. The throwaway is the one the capture started.
THROWAWAY = "49c1528a-4e2c-533b-9e55-c73b5959602d"


def captured(name: str) -> str:
    return (CAPTURED / name).read_text()


def ok(name: str) -> Outcome:
    return Outcome(0, captured(name), "")


def failed(name: str) -> Outcome:
    return Outcome(1, "", captured(name))


def listing(statuses: Mapping[str, str] | None = None, drop: Sequence[str] = (),
            cwds: Mapping[str, str] | None = None) -> Outcome:
    """The captured `agent list`, with the status of the named sessions replaced (the capture holds idle, working and
    done, and a blocked or unknown agent is the same record with another value), the cwd of the named sessions
    replaced, and the dropped sessions removed."""
    data = json.loads(captured("agent_list.json"))
    data["result"]["agents"] = [a for a in data["result"]["agents"] if a["agent_session"]["value"] not in drop]
    for agent in data["result"]["agents"]:
        agent["agent_status"] = (statuses or {}).get(agent["agent_session"]["value"], agent["agent_status"])
        agent["cwd"] = (cwds or {}).get(agent["agent_session"]["value"], agent["cwd"])
    return Outcome(0, json.dumps(data), "")


def session_ids() -> list[str]:
    agents = json.loads(captured("agent_list.json"))["result"]["agents"]
    return [a["agent_session"]["value"] for a in agents]


class FakeHerdr:
    """A Runner answering each exact argument list from a table, and failing on any other: a command the bridge was
    never meant to send shows as an unexpected call."""

    def __init__(self, replies: Mapping[tuple[str, ...], Outcome | Exception | list[Outcome]]) -> None:
        """A list of outcomes answers successive calls in order, the last one repeating."""
        self.replies = dict(replies)
        self.calls: list[tuple[str, ...]] = []

    def run(self, args: Sequence[str], timeout_s: float) -> Outcome:
        key = tuple(args)
        self.calls.append(key)
        if key not in self.replies:
            raise AssertionError(f"unexpected herdr call: {key}")
        reply = self.replies[key]
        if isinstance(reply, list):
            reply = reply.pop(0) if len(reply) > 1 else reply[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


class ListLog:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def emit(self, line: str) -> None:
        self.lines.append(line)


class Bridge:
    def __init__(self, state: Path, runner: FakeHerdr, roots: tuple[str, ...] = (DEFAULT_ROOT,),
                 limits: Limits = Limits(), clock: Callable[[], float] = time.time) -> None:
        (state / TOKEN_FILE).write_text(token_digest(TOKEN) + "\n")
        self.state = state
        self.runner = runner
        self.log = ListLog()
        herdr = Herdr(runner)
        self.pauses: list[float] = []
        claude = state.parent / "claude"
        self.projects = claude / "projects"
        self.ledger = Ledger(claude / "sent-prompts.jsonl", clock)
        sessions = Sessions(herdr, roots, 5000, self.log, Transcripts(self.projects, self.ledger), 2.0, self.pauses.append)
        self.api = Api(Auth(state), sessions, herdr, self.log, limits)

    def person_on_disk(self) -> str | None:
        path = self.state / PERSON_FILE
        return path.read_text().strip() if path.exists() else None

    def get(self, path: str, query: Mapping[str, str] | None = None, **headers: str) -> Response:
        return self.api.handle(Request("GET", path, query or {}, self.headers(headers), b""))

    def post(self, path: str, body: object, **headers: str) -> Response:
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        return self.api.handle(Request("POST", path, {}, self.headers(headers), raw))

    @staticmethod
    def headers(overrides: Mapping[str, str]) -> dict[str, str]:
        base = {"authorization": f"Bearer {TOKEN}", "x-ashley-person": PERSON}
        return {**base, **{k.replace("_", "-"): v for k, v in overrides.items()}}


def digest8(session_id: str) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()[:8]


@dataclass
class Issued:
    cert: Path
    key: Path
    pem: bytes


def issue(directory: Path, name: str, issuer: tuple[x509.Name, ec.EllipticCurvePrivateKey] | None = None) -> Issued:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    signer_name, signer_key = issuer or (subject, key)
    now = datetime.datetime.now(datetime.timezone.utc)
    builder = (x509.CertificateBuilder().subject_name(subject).issuer_name(signer_name).public_key(key.public_key())
               .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=1))
               .not_valid_after(now + datetime.timedelta(days=1))
               .add_extension(x509.BasicConstraints(ca=issuer is None, path_length=None), critical=True))
    pem = builder.sign(signer_key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM)
    cert, keyfile = directory / f"{name}.pem", directory / f"{name}.key"
    cert.write_bytes(pem)
    keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    return Issued(cert, keyfile, pem)


def ca_with_client(directory: Path, name: str) -> tuple[Path, Issued]:
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name + "-ca")])
    now = datetime.datetime.now(datetime.timezone.utc)
    ca_pem = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
              .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=1))
              .not_valid_after(now + datetime.timedelta(days=1))
              .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
              .sign(ca_key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM))
    ca_file = directory / f"{name}-ca.pem"
    ca_file.write_bytes(ca_pem)
    return ca_file, issue(directory, name + "-client", (ca_name, ca_key))


@dataclass
class Served:
    port: int
    pin: str
    bridge: Bridge


@contextmanager
def serving(root: Path, ca: Path, runner: FakeHerdr, roots: tuple[str, ...] = (DEFAULT_ROOT,),
            limits: Limits = Limits()) -> Generator[Served]:
    """The real bridge server over real TLS on a free local port, serving only clients certified by `ca`, with a
    self-signed certificate of its own made under `root`. `pin` is the fingerprint `init` would print."""
    state = root / "state"
    (state / "tls").mkdir(parents=True)
    server_cert = issue(state / "tls", "server")
    (state / "tls" / "cert.pem").write_bytes(server_cert.pem)
    (state / "tls" / "key.pem").write_bytes(server_cert.key.read_bytes())
    bridge = Bridge(state, runner, roots, limits)
    config = Config("127.0.0.1", 0, roots, str(state), str(ca), max_file_bytes=limits.max_file_bytes,
                    max_files=limits.max_files)
    server = make_server(config, bridge.api, bridge.log)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield Served(server.server_address[1], fingerprint(state / "tls" / "cert.pem"), bridge)
    finally:
        server.shutdown()
        server.server_close()
