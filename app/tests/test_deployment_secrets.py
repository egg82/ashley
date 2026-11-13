"""The deployment's own secrets on a real database: the env seeds each row once and never over a row; with neither a row
nor an env value one is generated; pods settling at once all keep the value that was written first; the value is sealed
under the connections key, bound to its name; a generated VAPID pair signs with the push library and a link signed under
the stored key checks on another pod; without the connections key, or while the database is away, the env's stand."""

import asyncio
import base64
import json
import os
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import psycopg
import pytest
from ashley import services, wiring_secrets
from ashley.channels.push import config as push_config
from ashley.connections.deployment_secrets import LINK_KEY, VAPID, DeploymentSecrets, Wanted, settle_one, vapid_value
from ashley.connections.sealing import VERSION, Sealer, Unsealable
from ashley.db.database import Database, DatabaseUnavailable, Probe
from ashley.db.pool import PoolDatabase
from ashley.looks import links
from ashley.settings import Settings
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from push_support import key_pair
from py_vapid import Vapid01

KEY = os.urandom(32)
SEALER = Sealer({VERSION: KEY})
ENV_LINK = "e" * 40


def settings(url: str, **changes: str) -> Settings:
    base: dict[str, Any] = {"database_url": url, "build_version": "t",
                            "connections_key": base64.b64encode(KEY).decode(), **changes}
    return Settings(**base)


@asynccontextmanager
async def database_on(url: str) -> AsyncGenerator[Database]:
    database = PoolDatabase(url, connect_timeout_s=5.0)
    await database.open()
    try:
        yield database
    finally:
        await database.close()


async def settled(config: Settings, database: Database) -> DeploymentSecrets:
    """What one pod holds after its start: `register`, then `settle` to the end."""
    services.register(Database, database)
    wiring_secrets.register(config)
    await wiring_secrets.settle(config, no_sleep)
    return services.get(DeploymentSecrets)


async def no_sleep(_: float) -> None:
    raise AssertionError("nothing should have failed")


def sealed_rows(url: str) -> dict[str, bytes]:
    with psycopg.connect(url) as conn:
        return {str(n): bytes(s) for n, s in conn.execute("SELECT name, sealed FROM deployment_secrets").fetchall()}


def opened(url: str, name: str) -> str:
    return SEALER.open(sealed_rows(url)[name], f"deployment:{name}".encode())


def test_the_env_seeds_the_rows_and_its_values_are_in_force(db_url: str) -> None:
    public, private = key_pair()
    config = settings(db_url, files_link_key=ENV_LINK, vapid_public_key=public, vapid_private_key=private)

    async def scenario() -> DeploymentSecrets:
        async with database_on(db_url) as database:
            return await settled(config, database)
    held = asyncio.run(scenario())
    assert held.link_key() == ENV_LINK and held.vapid_keys() == (public, private)
    assert opened(db_url, LINK_KEY) == ENV_LINK and json.loads(opened(db_url, VAPID)) == {
        "public_key": public, "private_key": private}


def test_with_neither_a_row_nor_an_env_value_fresh_ones_are_generated_once(db_url: str) -> None:
    async def scenario() -> tuple[DeploymentSecrets, DeploymentSecrets]:
        async with database_on(db_url) as database:
            first = await settled(settings(db_url), database)
            return first, await settled(settings(db_url), database)
    first, second = asyncio.run(scenario())
    assert len(first.link_key()) >= 32 and push_config.is_pair(*first.vapid_keys())
    assert (second.link_key(), second.vapid_keys()) == (first.link_key(), first.vapid_keys())
    assert opened(db_url, LINK_KEY) == first.link_key()
    assert scalar(db_url, "SELECT count(*) FROM deployment_secrets") == 2


def test_an_env_value_never_replaces_a_row(db_url: str) -> None:
    public, private = key_pair()
    seeding = settings(db_url, files_link_key=ENV_LINK, vapid_public_key=public, vapid_private_key=private)

    async def scenario() -> tuple[DeploymentSecrets, dict[str, bytes], DeploymentSecrets]:
        async with database_on(db_url) as database:
            before = await settled(settings(db_url), database)
            rows = sealed_rows(db_url)
            return before, rows, await settled(seeding, database)
    before, rows, after = asyncio.run(scenario())
    assert after.link_key() == before.link_key() != ENV_LINK
    assert after.vapid_keys() == before.vapid_keys() != (public, private)
    assert sealed_rows(db_url) == rows, "the rows' bytes did not change"


def test_pods_starting_at_once_converge_on_one_value(db_url: str) -> None:
    made = iter(f"value-{n}" for n in range(100))

    async def scenario() -> list[tuple[str | None, str]]:
        databases = [PoolDatabase(db_url, connect_timeout_s=5.0) for _ in range(6)]
        for database in databases:
            await database.open()
        try:
            return list(await asyncio.gather(*(settle_one(d, SEALER, Wanted(LINK_KEY, "", lambda: next(made)))
                                               for d in databases)))
        finally:
            for database in databases:
                await database.close()
    got = asyncio.run(scenario())
    assert len({value for value, _ in got}) == 1 and got[0][0] == opened(db_url, LINK_KEY)
    assert sorted(outcome for _, outcome in got) == ["found"] * 5 + ["generated"]


def test_a_pod_that_loses_the_insert_keeps_the_winner_s_value(db_url: str) -> None:
    """The other pod writes between this pod's read and its insert: this one's insert does nothing and it reads back
    the other's value, never keeping its own."""
    def generate_while_another_pod_writes() -> str:
        with psycopg.connect(db_url, autocommit=True) as conn:
            conn.execute("INSERT INTO deployment_secrets (name, sealed) VALUES (%s, %s)",
                         (LINK_KEY, SEALER.seal("the other pod's", f"deployment:{LINK_KEY}".encode())))
        return "this pod's"

    async def scenario() -> tuple[str | None, str]:
        async with database_on(db_url) as database:
            return await settle_one(database, SEALER, Wanted(LINK_KEY, "", generate_while_another_pod_writes))
    assert asyncio.run(scenario()) == ("the other pod's", "found")
    assert opened(db_url, LINK_KEY) == "the other pod's"


def test_the_value_is_sealed_under_the_connections_key_and_bound_to_its_name(db_url: str) -> None:
    async def scenario() -> None:
        async with database_on(db_url) as database:
            await settled(settings(db_url, files_link_key=ENV_LINK), database)
    asyncio.run(scenario())
    rows = sealed_rows(db_url)
    assert ENV_LINK.encode() not in rows[LINK_KEY] and rows[LINK_KEY][0] == VERSION
    with pytest.raises(Unsealable):
        SEALER.open(rows[LINK_KEY], f"deployment:{VAPID}".encode())
    with pytest.raises(Unsealable):
        Sealer({VERSION: os.urandom(32)}).open(rows[LINK_KEY], f"deployment:{LINK_KEY}".encode())
    with pytest.raises(Unsealable):
        SEALER.open(rows[LINK_KEY], f"connection:1:{LINK_KEY}".encode())


def test_a_row_another_key_sealed_is_never_written_over(db_url: str) -> None:
    other = Sealer({VERSION: os.urandom(32)})
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("INSERT INTO deployment_secrets (name, sealed) VALUES (%s, %s)",
                     (LINK_KEY, other.seal("theirs", f"deployment:{LINK_KEY}".encode())))
    rows = sealed_rows(db_url)

    async def scenario() -> None:
        async with database_on(db_url) as database:
            await settle_one(database, SEALER, Wanted(LINK_KEY, ENV_LINK, None))
    with pytest.raises(Unsealable):
        asyncio.run(scenario())
    assert sealed_rows(db_url) == rows


def test_a_generated_pair_signs_with_the_push_library(db_url: str) -> None:
    async def scenario() -> DeploymentSecrets:
        async with database_on(db_url) as database:
            return await settled(settings(db_url, vapid_subject="mailto:admin@example.test"), database)
    held = asyncio.run(scenario())
    services.register(DeploymentSecrets, held)
    identity = push_config.identity("mailto:admin@example.test")
    assert identity is not None
    headers = Vapid01.from_string(identity.private_key).sign({"sub": identity.subject,
                                                              "aud": "https://fcm.googleapis.com"})
    assert headers["Crypto-Key"] == f"p256ecdsa={identity.public_key}"
    header, claims, signature = headers["Authorization"].removeprefix("WebPush ").split(".")
    raw = _unb64(signature)
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), _unb64(identity.public_key))
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    public.verify(der, f"{header}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))


def test_a_link_signed_on_one_pod_checks_on_another(db_url: str) -> None:
    grant = links.Grant(1, 2, 3, 4, 2_000_000_000)

    async def scenario() -> tuple[str, str]:
        async with database_on(db_url) as database:
            minting = (await settled(settings(db_url), database)).link_key()
            checking = (await settled(settings(db_url), database)).link_key()
            return minting, checking
    minting, checking = asyncio.run(scenario())
    token = links.mint(minting.encode(), grant)
    assert links.check(checking.encode(), token, 1_000_000_000) == grant
    assert links.check(b"x" * 43, token, 1_000_000_000) is None


def test_without_the_connections_key_the_env_s_values_stand_and_nothing_is_written(db_url: str) -> None:
    public, private = key_pair()
    config = settings(db_url, connections_key="", files_link_key=ENV_LINK, vapid_public_key=public,
                      vapid_private_key=private)

    async def scenario() -> DeploymentSecrets:
        async with database_on(db_url) as database:
            return await settled(config, database)
    held = asyncio.run(scenario())
    assert held.link_key() == ENV_LINK and held.vapid_keys() == (public, private)
    assert sealed_rows(db_url) == {}


def test_an_env_pair_that_is_not_one_pair_is_neither_seeded_nor_replaced_by_a_fresh_one(db_url: str) -> None:
    public, _ = key_pair()
    _, other_private = key_pair()

    async def scenario() -> DeploymentSecrets:
        async with database_on(db_url) as database:
            return await settled(settings(db_url, vapid_public_key=public, vapid_private_key=other_private), database)
    held = asyncio.run(scenario())
    assert VAPID not in sealed_rows(db_url) and LINK_KEY in sealed_rows(db_url)
    assert push_config.vapid(*held.vapid_keys(), "mailto:admin@example.test") is None


class AwayOnce(Database):
    """The database, refusing the first connection as a pool does while the primary is away."""

    def __init__(self, inner: Database) -> None:
        self.inner = inner
        self.refused = 0

    async def open(self) -> None:
        await self.inner.open()

    async def close(self) -> None:
        await self.inner.close()

    async def probe(self) -> Probe:
        return await self.inner.probe()

    def connection(self) -> AbstractAsyncContextManager[psycopg.AsyncConnection[tuple[Any, ...]]]:
        if self.refused == 0:
            self.refused += 1
            raise DatabaseUnavailable("away")
        return self.inner.connection()


def test_while_the_database_is_away_the_env_s_values_stand_until_a_retry_settles(db_url: str) -> None:
    waits: list[float] = []

    async def scenario() -> tuple[str, str, bool]:
        async with database_on(db_url) as database:
            services.register(Database, AwayOnce(database))
            wiring_secrets.register(settings(db_url, files_link_key=ENV_LINK))
            held = services.get(DeploymentSecrets)
            waiting = asyncio.create_task(held.settled())
            during: list[tuple[str, bool]] = []

            async def sleep(s: float) -> None:
                waits.append(s)
                during.append((held.link_key(), waiting.done()))
            await wiring_secrets.settle(settings(db_url, files_link_key=ENV_LINK), sleep)
            await asyncio.wait_for(waiting, 1)
            return during[0][0], held.link_key(), during[0][1]
    before, after, settled_during = asyncio.run(scenario())
    assert waits == [wiring_secrets.RETRY_S[0]]
    assert before == after == ENV_LINK and not settled_during
    assert opened(db_url, LINK_KEY) == ENV_LINK


def test_the_vapid_value_round_trips_through_the_holder() -> None:
    public, private = key_pair()
    held = DeploymentSecrets()
    held.settle({VAPID: vapid_value(public, private), LINK_KEY: "k" * 43})
    assert held.vapid_keys() == (public, private) and held.link_key() == "k" * 43


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
