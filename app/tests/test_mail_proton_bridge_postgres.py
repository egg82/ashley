"""The Proton Bridge record on a real database (`ashley.mail.proton_bridge_postgres`): the epoch is a compare-and-set that
retires an older pod's writes; a write-back lands only at the generation it read and the current epoch; the vault is
stored sealed and opens only under the key that sealed it; an account's state and sync follow the epoch they were
reported in, and a signed-out account puts its connection in need of a login."""

import asyncio
import os

import pytest
from ashley.connections.sealing import VERSION, Sealer
from ashley.db.pool import PoolDatabase
from ashley.mail.proton_bridge import BridgeUnavailable, KeeperAccess
from ashley.mail.proton_bridge_postgres import PostgresProtonBridge, token_sha256
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar
from mail_bridge_support import KEY, bridge_on, proton_connection

pytestmark = pytest.mark.usefixtures("unwired")
VAULT, KEYCHAIN = b"v" * 64, b"k" * 32


async def started(bridge: PostgresProtonBridge, site: str = "birch", token: str = "t") -> int:
    epoch = await bridge.raise_epoch((await bridge.holder()).epoch, site, token_sha256(token))
    assert epoch is not None
    assert await bridge.pod_started(epoch, f"mail-bridge-{epoch}")
    return epoch


def test_a_new_record_has_no_epoch_and_no_vault(db_url: str) -> None:
    async def scenario() -> None:
        async with bridge_on(db_url) as bridge:
            holder = await bridge.holder()
            assert (holder.epoch, holder.site, holder.pod, holder.alive_age_s) == (0, None, None, None)

    asyncio.run(scenario())


def test_raising_the_epoch_is_a_compare_and_set_that_keeps_the_last_heartbeat(db_url: str) -> None:
    async def scenario() -> None:
        async with bridge_on(db_url) as bridge:
            first = await started(bridge)
            assert await bridge.heartbeat(first, None)
            assert await bridge.raise_epoch(first, "willow", token_sha256("u")) == first + 1
            assert await bridge.raise_epoch(first, "willow", token_sha256("v")) is None
            holder = await bridge.holder()
            assert (holder.epoch, holder.site, holder.pod) == (first + 1, "willow", None)
            assert holder.alive_age_s is not None and holder.alive_age_s < 5
            assert not await bridge.heartbeat(first, None)
            assert await bridge.pod_started(first + 1, "p") and not await bridge.pod_started(first + 1, "q")

    asyncio.run(scenario())


def test_authorize_names_a_stale_epoch_before_a_wrong_token(db_url: str) -> None:
    async def scenario() -> None:
        async with bridge_on(db_url) as bridge:
            epoch = await started(bridge, token="right")
            assert await bridge.authorize(epoch, "right") == "ok"
            assert await bridge.authorize(epoch, "wrong") == "bad_token"
            assert await bridge.authorize(epoch - 1, "right") == "stale_epoch"

    asyncio.run(scenario())


def test_a_write_back_lands_only_at_its_generation_and_the_current_epoch(db_url: str) -> None:
    async def scenario() -> None:
        async with bridge_on(db_url) as bridge:
            epoch = await started(bridge)
            first = await bridge.vault(epoch)
            assert first is not None and (first.generation, first.vault, first.keychain) == (0, None, None)
            assert await bridge.write_back(epoch, 0, VAULT, KEYCHAIN) == 1
            assert await bridge.write_back(epoch, 0, b"stale", KEYCHAIN) is None
            assert await bridge.write_back(epoch + 1, 1, b"other", KEYCHAIN) is None
            got = await bridge.vault(epoch)
            assert got is not None and (got.generation, got.vault, got.keychain) == (1, VAULT, KEYCHAIN)
            assert await bridge.vault(epoch + 1) is None

    asyncio.run(scenario())


def test_the_vault_is_stored_sealed_and_opens_only_under_its_key(db_url: str) -> None:
    async def scenario() -> None:
        async with bridge_on(db_url) as bridge:
            epoch = await started(bridge)
            await bridge.write_back(epoch, 0, VAULT, KEYCHAIN)
        stored = bytes(scalar(db_url, "SELECT vault FROM proton_bridge"))
        assert VAULT not in stored and len(stored) > len(VAULT)
        database = PoolDatabase(db_url)
        await database.open()
        try:
            other = PostgresProtonBridge(database, Sealer({VERSION: os.urandom(32)}))
            with pytest.raises(BridgeUnavailable):
                await other.vault(epoch)
            assert (await PostgresProtonBridge(database, Sealer({VERSION: KEY})).vault(epoch)) is not None
        finally:
            await database.close()

    asyncio.run(scenario())


def test_an_account_follows_the_epoch_its_state_and_sync_were_reported_in(db_url: str) -> None:
    async def scenario() -> None:
        connection = await proton_connection(db_url)
        async with bridge_on(db_url) as bridge:
            epoch = await started(bridge)
            account = await bridge.add_account(connection, "user-1", ("a@proton.test",))
            assert (account.state, account.syncing, account.sync_progress) == ("connected", True, None)
            assert await bridge.sync(epoch, "user-1", "progress", 0.4) == account.id
            assert await bridge.sync(epoch - 1, "user-1", "finished") is None
            assert await bridge.sync(epoch, "nobody", "finished") is None
            assert (await bridge.accounts())[0].sync_progress == 0.4
            assert await bridge.sync(epoch, "user-1", "finished")
            assert not (await bridge.accounts())[0].syncing
            nxt = await bridge.raise_epoch(epoch, "birch", token_sha256("x"))
            assert nxt is not None and (await bridge.accounts())[0].syncing
            assert await bridge.pod_started(nxt, "p")
            assert await bridge.sync(nxt, "user-1", "started")
            assert (await bridge.accounts())[0].sync_progress == 0

    asyncio.run(scenario())


def test_a_signed_out_account_needs_a_login_and_logging_in_clears_it(db_url: str) -> None:
    async def scenario() -> None:
        connection = await proton_connection(db_url)
        async with bridge_on(db_url) as bridge:
            epoch = await started(bridge)
            await bridge.add_account(connection, "user-1", ())
            assert await bridge.set_state(epoch, "user-1", "signed_out") is not None
            assert await bridge.set_state(epoch - 1, "user-1", "connected") is None
            assert scalar(db_url, "SELECT needs FROM connections") == "login"
            assert not (await bridge.accounts())[0].syncing
            await bridge.add_account(connection, "user-1", ("b@proton.test",))
            account = (await bridge.accounts())[0]
            assert (account.state, account.addresses) == ("connected", ("b@proton.test",))
            assert scalar(db_url, "SELECT needs FROM connections") is None

    asyncio.run(scenario())


def test_a_database_that_cannot_be_reached_is_unavailable() -> None:
    async def scenario() -> None:
        async with bridge_on("postgresql://postgres:t@127.0.0.1:1/postgres") as bridge:
            with pytest.raises(BridgeUnavailable):
                await bridge.holder()

    asyncio.run(scenario())


def test_the_keepers_token_and_certificate_are_stored_sealed_for_the_epoch_and_open_from_the_record(
        db_url: str) -> None:
    async def scenario() -> None:
        async with bridge_on(db_url) as bridge:
            grant = KeeperAccess("tok-secret-1", "CERT-PEM-1")
            first = await bridge.raise_epoch(0, "birch", token_sha256("tok-secret-1"), grant)
            assert first is not None and await bridge.keeper_access(first) == grant
            assert await bridge.keeper_access(first + 1) is None
            raw = scalar(db_url, "SELECT keeper_access FROM proton_bridge")
            assert b"tok-secret-1" not in bytes(raw) and b"CERT-PEM-1" not in bytes(raw)
            async with bridge_on(db_url, os.urandom(32)) as stranger:
                with pytest.raises(BridgeUnavailable):
                    await stranger.keeper_access(first)
            second = await bridge.raise_epoch(first, "willow", token_sha256("u"))
            assert second is not None and await bridge.keeper_access(second) is None
            assert await bridge.keeper_access(first) is None

    asyncio.run(scenario())
