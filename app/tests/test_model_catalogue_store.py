"""The catalogue's stored layers on a real database and the refresh singleton: a fetch is stored whole and replaced, an
override is stored per field with who set it and reset by deleting it, each pod's cache picks up both within its bound,
a failed fetch or read keeps what was there, and the singleton fetches only when the stored fetch is due."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx2
import psycopg
import pytest
from ashley.db.database import NullDatabase
from ashley.db.pool import PoolDatabase
from ashley.inference import catalogue_refresh, models_dev
from ashley.inference.catalogue import ModelCatalogueUnavailable
from ashley.inference.catalogue_merge import Override
from ashley.inference.catalogue_model import Catalogue, Provider
from ashley.inference.catalogue_store import CatalogueStore
from ashley.inference.model import Usage
from ashley.inference.postgres_catalogue import PostgresCatalogue
from ashley.inference.postgres_catalogue_override_write import PostgresCatalogueOverrideWriter
from ashley.inference.stored_catalogue import StoredCatalogue
from ashley.people import admin
from catalogue_support import PLAIN, captured, flat
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from household_routes_support import events

AT = datetime(2026, 11, 13, 8, tzinfo=UTC)
MILLION = Usage(1_000_000, 0)
D = Decimal


def person(url: str) -> int:
    with psycopg.connect(url) as conn:
        return admin.add_person(conn, admin.add_household(conn, "one", "UTC"), "Alana")


def on[R](url: str, work: Callable[[PostgresCatalogue, PostgresCatalogueOverrideWriter], Awaitable[R]]) -> R:
    async def scenario() -> R:
        database = PoolDatabase(url)
        await database.open()
        try:
            return await asyncio.wait_for(work(PostgresCatalogue(database), PostgresCatalogueOverrideWriter(database)), 25)
        finally:
            await database.close()
    return asyncio.run(scenario())


def one_model(price: str) -> Catalogue:
    return Catalogue({"p": Provider("P", None, {"m": flat(price)})})


def test_a_fetch_is_stored_whole_and_replaced(db_url: str) -> None:
    async def work(store: PostgresCatalogue, _: PostgresCatalogueOverrideWriter) -> list[object]:
        empty = (await store.fetched_at(), await store.fetched())
        await store.put_fetch(captured(), AT)
        first = await store.fetched()
        await store.put_fetch(Catalogue({}), AT + timedelta(hours=6))
        return [empty, first, await store.fetched(), await store.fetched_at()]
    empty, first, second, at = on(db_url, work)
    assert empty == (None, None)
    assert first == (captured(), AT)
    assert second == (Catalogue({}), AT + timedelta(hours=6)) and at == AT + timedelta(hours=6)


def test_an_override_is_stored_per_field_with_who_set_it_and_a_reset_deletes_it(
        db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, "ashley.inference")
    alana = person(db_url)

    async def work(store: PostgresCatalogue, writer: PostgresCatalogueOverrideWriter) -> list[list[Override]]:
        await writer.write("p", "m", {"input_usd_per_mtok": D("0.125"), "free": True}, (), alana)
        first = await store.overrides()
        await writer.write("p", "m", {"input_usd_per_mtok": D("2")}, ["free"], alana)
        return [first, await store.overrides()]
    first, then = on(db_url, work)
    assert {(o.field, o.value, o.set_by) for o in first} == {("input_usd_per_mtok", D("0.125"), alana),
                                                             ("free", True, alana)}
    assert [(o.provider, o.model, o.field, o.value) for o in then] == [("p", "m", "input_usd_per_mtok", D("2"))]
    assert events(caplog, "catalogue.override_set") == [
        {"provider": "p", "model": "m", "person": alana, "put": 2, "reset": 0},
        {"provider": "p", "model": "m", "person": alana, "put": 1, "reset": 1}]


def test_a_stored_override_the_code_cannot_read_is_dropped_and_the_rest_kept(db_url: str) -> None:
    with psycopg.connect(db_url) as conn:
        conn.execute("INSERT INTO model_catalogue_overrides (provider, model, field, value) VALUES "
                     "('p', 'm', 'retired', '1'), ('p', 'm', 'context_tokens', '-5'), ('p', 'm', 'name', '\"Kept\"')")
    found = on(db_url, lambda store, _: store.overrides())
    assert [(o.field, o.value, o.set_by) for o in found] == [("name", "Kept", None)]


def test_each_pod_prices_from_the_snapshot_then_the_stored_layers_within_its_bound(db_url: str) -> None:
    alana = person(db_url)
    clock = [0.0]

    async def work(store: PostgresCatalogue, writer: PostgresCatalogueOverrideWriter) -> list[Decimal | None]:
        cached = StoredCatalogue((one_model("1"), AT), store, PLAIN, lambda: clock[0], refresh_s=30)
        seen = [cached.priced().cost_usd("p", "m", MILLION)]
        await cached.refresh()
        await store.put_fetch(one_model("2"), AT)
        await writer.write("p", "m", {"output_usd_per_mtok": D("1")}, (), alana)
        clock[0] = 29.9
        await cached.refresh()
        seen.append(cached.priced().cost_usd("p", "m", MILLION))
        clock[0] = 30.0
        await cached.refresh()
        seen.append(cached.priced().cost_usd("p", "m", Usage(1_000_000, 1_000_000)))
        state = await cached.state()
        seen.append(D(1) if state.fetched_at == AT and state.snapshot_at == AT else None)
        return seen
    assert on(db_url, work) == [D(1), D(1), D(3), D(1)]


def test_a_failed_read_keeps_what_was_built(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, "ashley.inference")
    cached = StoredCatalogue((one_model("1"), AT), PostgresCatalogue(NullDatabase()), PLAIN, lambda: 0.0)
    asyncio.run(cached.refresh())
    assert cached.priced().cost_usd("p", "m", MILLION) == D(1)
    assert len(events(caplog, "catalogue.unreadable")) == 1
    with pytest.raises(ModelCatalogueUnavailable):
        asyncio.run(cached.state())


# --- the refresh singleton ---------------------------------------------------------------------------------------

class Stored(CatalogueStore):
    def __init__(self, at: datetime | None = None, down: bool = False) -> None:
        self.at, self.down, self.puts = at, down, list[tuple[Catalogue, datetime]]()

    async def fetched_at(self) -> datetime | None:
        if self.down:
            raise ModelCatalogueUnavailable("down")
        return self.at

    async def fetched(self) -> tuple[Catalogue, datetime] | None:
        return None

    async def put_fetch(self, catalogue: Catalogue, at: datetime) -> None:
        self.puts.append((catalogue, at))
        self.at = at

    async def overrides(self) -> list[Override]:
        return []


def ran(store: Stored, fetch: catalogue_refresh.Fetch, rounds: int = 1) -> list[float]:
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) >= rounds:
            raise asyncio.CancelledError

    async def go() -> None:
        with pytest.raises(asyncio.CancelledError):
            await catalogue_refresh.run(PLAIN, store, fetch, sleep, lambda: AT)
    asyncio.run(go())
    return waits


async def good() -> models_dev.Read:
    return models_dev.Read(captured(), 0)


async def refused() -> models_dev.Read:
    raise httpx2.HTTPStatusError("503", request=httpx2.Request("GET", "https://models.test"),
                                 response=httpx2.Response(503))


async def unreadable() -> models_dev.Read:
    raise ValueError("models.dev: no provider could be read")


def test_with_no_stored_fetch_it_fetches_stores_and_waits_the_refresh_interval() -> None:
    store = Stored()
    assert ran(store, good) == [PLAIN.refresh_s]
    assert store.puts == [(captured(), AT)]


@pytest.mark.parametrize("fetch", [refused, unreadable])
def test_a_failed_fetch_stores_nothing_logs_why_and_tries_again_after_retry_s(
        fetch: catalogue_refresh.Fetch, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, "ashley.inference")
    store = Stored(AT - timedelta(days=1))
    assert ran(store, fetch) == [PLAIN.retry_s]
    assert store.puts == []
    assert [e["reason"] for e in events(caplog, "catalogue.fetch_failed")] == [
        "status_503" if fetch is refused else "ValueError"]


def test_a_fetch_not_yet_due_is_not_made_and_it_waits_the_rest_of_the_interval() -> None:
    store = Stored(AT - timedelta(seconds=20))
    assert ran(store, good) == [PLAIN.refresh_s - 20]
    assert store.puts == []


def test_a_store_out_of_reach_is_logged_once_per_run_and_retried() -> None:
    store = Stored(down=True)
    assert ran(store, good, rounds=3) == [PLAIN.retry_s] * 3
    assert store.puts == []


def test_a_failed_fetch_keeps_the_stored_one_on_a_real_database(db_url: str) -> None:
    async def work(store: PostgresCatalogue, _: PostgresCatalogueOverrideWriter) -> tuple[Catalogue, datetime] | None:
        await store.put_fetch(captured(), AT)
        assert not await catalogue_refresh.refresh_once(store, refused, AT + timedelta(days=1))
        return await store.fetched()
    assert on(db_url, work) == (captured(), AT)
