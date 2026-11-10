"""The sweep's two Postgres halves over a real database: the candidates survive between passes, and the references are
the large pieces on any bench (shelved included) plus those within the undo window, per household."""

import dataclasses
import hashlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from files_support import PNG, ZIP, sync
from ashley import services
from ashley.db.database import Database
from ashley.db.pool import PoolDatabase
from ashley.files import config as files_config, sweep
from ashley.files.intake import key_of
from ashley.files.memory import MemoryStore
from ashley.files.mirror import MirroredStore
from ashley.files.orphans import PostgresCandidates
from ashley.files.store import ObjectStore
from ashley.workshop import bench_file, rules as workshop_rules
from ashley.workshop.commands import Archive, Remove
from ashley.workshop.file_references import named_keys
from ashley.workshop.model import By, Owner
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.rules import Rules
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template, person


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@asynccontextmanager
async def wired(url: str) -> AsyncGenerator[tuple[Workshop, Rules, MemoryStore]]:
    db = PoolDatabase(url)
    await db.open()
    rules = workshop_rules.load()
    workshop = PostgresWorkshop(db, rules)
    store = MemoryStore()
    for interface, provider in ((Database, db), (Workshop, workshop), (ObjectStore, store)):
        services.register(interface, provider)
    try:
        yield workshop, rules, store
    finally:
        for interface in (Database, Workshop, ObjectStore):
            services.unregister(interface)
        await db.close()


def owner(url: str, name: str) -> Owner:
    home = household(url, name)
    return Owner(home, person(url, home, "Alana"))


async def upload(workshop: Workshop, rules: Rules, who: Owner, bench: int, data: bytes) -> int:
    _, applied = await bench_file.add_file(who, bench, By(who.person_id), data, "f.bin", "", rules)
    assert applied.piece_id is not None
    return applied.piece_id


@sync
async def test_candidates_are_replaced_whole(db_url: str) -> None:
    async with wired(db_url):
        candidates = PostgresCandidates()
        assert await candidates.load() == frozenset()
        await candidates.save(frozenset({"bench/1/x", "bench/1/y"}))
        await candidates.save(frozenset({"bench/1/y", "bench/1/z"}))
        assert await candidates.load() == {"bench/1/y", "bench/1/z"}
        await candidates.save(frozenset())
        assert await candidates.load() == frozenset()


@sync
async def test_a_bench_names_its_files_per_household_and_a_removed_file_is_named_only_within_the_undo_window(
        db_url: str) -> None:
    alana, zed = owner(db_url, "one"), owner(db_url, "two")
    async with wired(db_url) as (workshop, rules, _):
        bench, theirs = (await workshop.open(alana, "b")).id, (await workshop.open(zed, "z")).id
        await upload(workshop, rules, alana, bench, PNG)
        gone = await upload(workshop, rules, alana, bench, ZIP)
        shelved = await upload(workshop, rules, alana, bench, PNG + b"shelved")
        await upload(workshop, rules, zed, theirs, PNG)
        await workshop.apply(alana, bench, Remove(By(alana.person_id), gone))
        await workshop.apply(alana, bench, Archive(By(alana.person_id), shelved))
        every = {key_of(alana.household_id, sha(PNG)), key_of(alana.household_id, sha(ZIP)),
                 key_of(alana.household_id, sha(PNG + b"shelved")), key_of(zed.household_id, sha(PNG))}
        assert await named_keys(rules) == every
        short = dataclasses.replace(rules, undo_window=1)
        assert await named_keys(short) == every - {key_of(alana.household_id, sha(ZIP))}


@sync
async def test_an_upload_whose_piece_was_never_made_is_swept_after_two_passes(db_url: str) -> None:
    alana = owner(db_url, "one")
    async with wired(db_url) as (workshop, rules, store):
        bench = (await workshop.open(alana, "b")).id
        await upload(workshop, rules, alana, bench, PNG)
        orphan = key_of(alana.household_id, sha(ZIP))
        await store.put(orphan, ZIP)
        old = datetime.now(UTC) - timedelta(days=30)
        store.written = {k: old for k in store.objects}
        config = files_config.load()

        async def referenced() -> frozenset[str]:
            return await named_keys(rules)

        mirror, candidates = MirroredStore([store]), PostgresCandidates()
        await sweep.run_once(mirror, referenced, candidates, config)
        assert orphan in store.objects and await candidates.load() == {orphan}
        await sweep.run_once(mirror, referenced, candidates, config)
        assert set(store.objects) == {key_of(alana.household_id, sha(PNG))} and await candidates.load() == frozenset()
