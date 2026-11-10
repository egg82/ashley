"""Blind contract tests for part 4, "Bridge as a leased singleton" (decisions.md, "Her mail is a port with two adapters,
and Proton's runs as a leased Bridge", subsection "Bridge runs as a leased singleton whose vault outlives its pod"):
the real app on a real database, a fake Kubernetes API at `ashley.runs.kube_api.KubeApi`'s boundary, the keeper run as
its own program against a fake app and a fake Bridge (`mail_bridge_blind_keeper_support`), and no Proton. Everything the
design does not name is guessed once, in ASSUMPTIONS below; a test never guesses on its own. The same list, with the
design sentence under each, is in `~/scratch/ashley/mail/bridge-blind/assumptions.txt`.

HOW THE BUILD DECIDED WHAT THE DESIGN LEFT OPEN (the blind suite guessed each differently, `assumptions.txt` B1-B14 and
G1-G7; this support file is the one place that maps the guesses to the build, and no test changes what it asserts):

- the config is `ashley.mail.config.MailConfig` (`tick_s` is the job's look interval); the record is `ashley.mail.
  proton_bridge.ProtonBridge` (`holder`, `raise_epoch`, `pod_started`, `add_account`, `accounts`), read here as a
  `State` straight from its table; a pod is named for its epoch, so a test's pod names are aliases (`ALIASES`);
- the keeper's routes are under `/api/mail-bridge/keeper`, a heartbeat carries `certificate_sha256` and is answered 204, an
  event is a `state` or a `sync` (the suite's `kind` is mapped);
- the singleton is `BridgeKeeping(...).run`; `KubeApi` has `create_secret(namespace, name, labels, data)`, `secret`, `secrets`;
- the room's login is `/api/mail-bridge/login`, `/login/two-factor` and `/login/mailbox-password`, each with a label,
  answering `two_factor`, `mailbox_password` or `connected`; the keeper's control port is TLS under the certificate in
  the pod's Secret, with the same step names;
- the keeper is `deploy/mail-bridge/keeper.py` run by `keeper.main()` from environment `BRIDGE_*`, its Bridge a stand-in
  process behind `keeper_process.start` (the image test runs the real one); Bridge's gRPC link is `keeper_link.BridgeLink`;
- `ProtonBridge` and the Proton kind are wired only with `MAIL_BRIDGE_IMAGE`, so `app_client` registers them.
"""

import base64
import hashlib
import secrets
import time
from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import Any, TypeVar

import httpx2
import psycopg
from psycopg import sql
from ashley import services
from ashley.api.person import SESSION_COOKIE
from ashley.connections.connections import Connections
from ashley.main import create_app
from ashley.connections.kinds import ConnectionKinds
from ashley.connections.sealing import VERSION, Sealer, key_from
from ashley.db.database import Database
from ashley.mail import config as mail_config, proton_pod
from ashley.mail.proton_bridge import KeeperAccess, ProtonBridge
from ashley.mail.proton_bridge_postgres import PostgresProtonBridge
from ashley.mail.proton_kind import ADDRESS, PROTON
from ashley.wiring import CONNECTION_KINDS
from ashley.people import admin
from ashley.settings import Settings
from contract.conversations_support import scalar
from fastapi.testclient import TestClient

T = TypeVar("T")
PUBLIC = "https://ashley.test"
APP_KEY = base64.b64encode(bytes(range(32, 64))).decode()
PREFIX = "/api/mail-bridge/keeper"
SITE, OTHER_SITE = "site-a", "site-b"
NS = "ashley-mail-bridge"
IMAGE = "registry.test/apps/ashley-mail-bridge@sha256:" + "b" * 64
VAULT = b"VAULTBYTES-7f3a9c-0"
KEYCHAIN = b"KEYCHAINBYTES-51d2"
FAST: dict[str, Any] = {"fence_s": 1.0, "fence_margin_s": 0.5, "heartbeat_s": 0.2, "restart_s": 0.5, "tick_s": 0.05}
ALIASES: dict[str, str] = {}
LIVE: list[TestClient] = []


def config(**changes: float) -> mail_config.MailConfig:
    return replace(mail_config.load(), **{**FAST, **changes})


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Pod:
    """One epoch's pod as a test plays its keeper: the epoch, the token it was given, its name and site, and when its
    last accepted heartbeat came back (`time.monotonic()`)."""

    epoch: int
    token: str
    name: str
    site: str
    last_beat: float = 0.0
    fingerprint: str = "ab" * 32

    def auth(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self.token}"}


@dataclass(frozen=True)
class State:
    """The record's row as the suite reads it: `heartbeat_at` and `fingerprint` None until a heartbeat, `has_vault` once a
    write-back stored one."""

    epoch: int
    generation: int
    site: str | None
    pod: str | None
    heartbeat_at: Any
    token_hash: str | None
    fingerprint: str | None
    has_vault: bool


@dataclass(frozen=True)
class Account:
    user_id: str
    connection_id: int
    state: str
    synced_epoch: int | None
    syncing: bool
    progress: Any


@dataclass(frozen=True)
class Answer:
    """A heartbeat's answer, its 204 read as the success it is (the suite wrote 200)."""

    status_code: int
    text: str = ""


EVENT_BODIES: dict[str, dict[str, Any]] = {
    "sync_started": {"sync": "started"}, "sync_progress": {"sync": "progress"}, "sync_finished": {"sync": "finished"},
    "user_signed_out": {"state": "signed_out"}, "user_bad": {"state": "locked"}}


@dataclass
class World:
    client: TestClient
    url: str
    home: int
    alana: int
    tokens: dict[str, str] = field(default_factory=lambda: dict[str, str]())

    def run(self, call: Callable[[], Awaitable[T]]) -> T:
        portal = self.client.portal
        assert portal is not None
        return portal.call(call)

    def record(self) -> ProtonBridge:
        return services.get(ProtonBridge)

    def state(self) -> State:
        with psycopg.connect(self.url) as conn:
            row = conn.execute("SELECT epoch, generation, site, pod, heartbeat_at, encode(token_sha256, 'hex'), "
                               "certificate_sha256, vault IS NOT NULL FROM proton_bridge").fetchone()
        assert row is not None
        pod = next((alias for alias, real in ALIASES.items() if real == row[3]), row[3])
        return State(row[0], row[1], row[2], pod, *row[4:])

    def accounts(self) -> list[Account]:
        held = self.run(self.record().accounts)
        return [Account(a.proton_user_id, a.connection_id, a.state, a.synced_epoch or None, a.syncing,
                        a.sync_progress) for a in sorted(held, key=lambda a: a.id)]

    def begin(self, site: str = SITE, name: str = "bridge-1", access: KeeperAccess | None = None) -> Pod:
        """A new epoch for `site` whose pod is named for it, as the build names pods; `name` stays the suite's alias."""
        token = secrets.token_urlsafe(24)

        async def raised() -> int:
            record = self.record()
            epoch = await record.raise_epoch((await record.holder()).epoch, site, bytes.fromhex(sha(token)), access)
            assert epoch is not None
            assert await record.pod_started(epoch, proton_pod.pod_name(epoch))
            return epoch

        epoch = self.run(raised)
        ALIASES[name] = proton_pod.pod_name(epoch)
        return Pod(epoch, token, name, site)

    def beat(self, pod: Pod) -> Answer:
        got = self.client.post(f"{PREFIX}/heartbeat", json={"epoch": pod.epoch, "certificate_sha256": pod.fingerprint},
                               headers=pod.auth())
        if got.status_code == 204:
            pod.last_beat = time.monotonic()
        return Answer(200 if got.status_code == 204 else got.status_code, got.text)

    def fetch(self, pod: Pod, epoch: int | None = None) -> httpx2.Response:
        return self.client.get(f"{PREFIX}/vault", params={"epoch": pod.epoch if epoch is None else epoch},
                               headers=pod.auth())

    def put(self, pod: Pod, generation: int, vault: bytes = VAULT, epoch: int | None = None,
            keychain: bytes = KEYCHAIN) -> httpx2.Response:
        return self.client.put(f"{PREFIX}/vault", headers=pod.auth(), json={
            "epoch": pod.epoch if epoch is None else epoch, "generation": generation, "vault": b64(vault),
            "keychain": b64(keychain)})

    def event(self, pod: Pod, kind: str, user_id: str = "u1", epoch: int | None = None, **extra: object) -> httpx2.Response:
        return self.client.post(f"{PREFIX}/events", headers=pod.auth(), json={
            "epoch": pod.epoch if epoch is None else epoch, "user_id": user_id,
            **EVENT_BODIES.get(kind, {"sync": kind}), **extra})

    def account(self, user_id: str = "u1", state: str = "connected") -> int:
        """A Proton account Bridge holds, with the household's connection that is it; returns the connection's id."""
        async def add() -> int:
            made = await services.get(Connections).add(self.home, "proton", user_id, ADDRESS, "bp-secret", self.alana)
            await self.record().add_account(made.id, user_id, (f"{user_id}@proton.test",))
            return made.id

        return self.run(add)

    def needs(self, connection_id: int) -> str | None:
        found = scalar(self.url, "SELECT needs FROM connections WHERE id = %s", (connection_id,))
        return None if found is None else str(found)

    def sign_in(self) -> None:
        self.client.cookies.set(SESSION_COOKIE, self.tokens["alana"], domain="ashley.test")


def make_world(url: str, client: TestClient) -> World:
    with psycopg.connect(url) as conn:
        home = admin.add_household(conn, "home", "America/Denver")
        alana = admin.add_person(conn, home, "Alana")
        account = admin.add_account(conn, alana, "authentik", "a")
        token = secrets.token_urlsafe(16)
        conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                     "VALUES (%s, %s, %s, now() + interval '1 day')",
                     (hashlib.sha256(token.encode()).digest(), account, home))
    return World(client, url, home, alana, {"alana": token})


def app_client(url: str, **settings: str) -> Generator[TestClient]:
    app = create_app(Settings(database_url=url, build_version="t", public_url=PUBLIC, connections_key=APP_KEY,
                              **settings))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        services.register(ConnectionKinds, ConnectionKinds((*CONNECTION_KINDS, PROTON)))
        services.register(ProtonBridge, PostgresProtonBridge(services.get(Database),
                                                             Sealer({VERSION: key_from(APP_KEY)})))
        LIVE.append(c)
        try:
            yield c
        finally:
            LIVE.remove(c)


# --- the database ---------------------------------------------------------------------------------------------------


def dump(url: str) -> str:
    """Every row of every table of the database as text, bytea in hex: what is stored, for a search that must find
    nothing (and a control that must find something)."""
    out: list[str] = []
    with psycopg.connect(url, autocommit=True) as conn:
        tables = [r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'").fetchall()]
        assert tables
        for name in tables:
            for row in conn.execute(sql.SQL("SELECT t::text FROM {} t").format(sql.Identifier(name))).fetchall():
                out.append(str(row[0]))
    return "\n".join(out)


def forms(raw: bytes) -> list[str]:
    """The ways stored or logged text could carry `raw`: itself, its hex and its base64."""
    return [raw.decode("latin-1"), raw.hex(), b64(raw), base64.urlsafe_b64encode(raw).decode()]


@contextmanager
def read_only(url: str) -> Generator[None]:
    """The database as it is during a demotion: every new transaction read-only, and the connections the app holds cut
    so its next ones are made read-only."""
    name = scalar(url, "SELECT current_database()")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL("ALTER DATABASE {} SET default_transaction_read_only = on").format(sql.Identifier(name)))
        conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> "
                     "pg_backend_pid()", (name,))
    try:
        yield
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("SET default_transaction_read_only = off")
            conn.execute(sql.SQL("ALTER DATABASE {} RESET default_transaction_read_only").format(sql.Identifier(name)))
            conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> "
                         "pg_backend_pid()", (name,))
        flush_pool()


def flush_pool() -> None:
    """The app's pool hands each connection cut under it to one call before it drops it; spend those calls, as the next
    heartbeats after a promotion would."""
    for client in LIVE:
        portal = client.portal
        if portal is not None:
            for _ in range(6):
                portal.call(services.get(Database).probe)


