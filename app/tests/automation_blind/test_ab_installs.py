"""The Installs record: started once per bench command, ended once, read back by command and as the latest on each piece
of a bench, per household."""

from typing import Any

import pytest
from ab_support import add, body, bench_with_piece, crowd, install, propose
from ashley import services
from ashley.workshop.installs import Before, Installs, NewInstall
from ashley.workshop.model import Owner
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, run


async def accepted_install(owner: Owner, bench: int, piece: int) -> int:
    shop = services.get(Workshop)
    proposed = await shop.apply(owner, bench, propose(piece, 1))
    return (await shop.apply(owner, bench, install(owner, bench, proposed.seq, piece))).seq


def new(owner: Owner, bench: int, seq: int, piece: int, **kw: Any) -> NewInstall:
    fields: dict[str, Any] = dict(household_id=owner.household_id, bench_id=bench, seq=seq, piece_id=piece, action="install",
                  automation_id=f"ashley_bench_{bench}_piece_{piece}", enabled=True, turn_off="automation.old",
                  before=Before({"alias": "was"}, False, True), touched=True)
    return NewInstall(**{**fields, **kw})


def test_a_started_record_reads_back_whole_with_no_ending_until_finished(db_url: str) -> None:
    async def scenario() -> None:
        async with crowd(db_url) as (_, c):
            installs = services.get(Installs)
            bench, piece = await bench_with_piece(c.alana)
            seq = await accepted_install(c.alana, bench, piece)
            started = new(c.alana, bench, seq, piece)
            assert await installs.of(c.alana.household_id, bench, seq) is None
            await installs.start(started)
            record = await installs.of(c.alana.household_id, bench, seq)
            assert record is not None and record.started == started
            assert (record.ending, record.note, record.finished_at) == (None, None, None)
            await installs.finish(bench, seq, "failed", "stopped at the write")
            record = await installs.of(c.alana.household_id, bench, seq)
            assert record is not None and (record.ending, record.note) == ("failed", "stopped at the write")
            assert record.finished_at is not None and record.finished_at >= record.started_at

    run(scenario())


def test_an_uninstall_record_keeps_its_nones(db_url: str) -> None:
    async def scenario() -> None:
        async with crowd(db_url) as (_, c):
            installs = services.get(Installs)
            bench, piece = await bench_with_piece(c.alana)
            seq = await accepted_install(c.alana, bench, piece)
            started = new(c.alana, bench, seq, piece, action="uninstall", enabled=None, turn_off=None, before=None)
            await installs.start(started)
            got = await installs.of(c.alana.household_id, bench, seq)
            assert got is not None and got.started == started

    run(scenario())


def test_a_command_has_one_record_and_one_ending(db_url: str) -> None:
    async def scenario() -> None:
        async with crowd(db_url) as (_, c):
            installs = services.get(Installs)
            bench, piece = await bench_with_piece(c.alana)
            seq = await accepted_install(c.alana, bench, piece)
            with pytest.raises(KeyError):
                await installs.finish(bench, seq, "done", None)
            await installs.start(new(c.alana, bench, seq, piece))
            with pytest.raises(ValueError):
                await installs.start(new(c.alana, bench, seq, piece, enabled=False))
            await installs.finish(bench, seq, "done", None)
            with pytest.raises(ValueError):
                await installs.finish(bench, seq, "failed", "again")
            record = await installs.of(c.alana.household_id, bench, seq)
            assert record is not None and record.ending == "done" and record.started.enabled is True

    run(scenario())


def test_text_postgres_cannot_store_is_a_value_error(db_url: str) -> None:
    async def scenario() -> None:
        async with crowd(db_url) as (_, c):
            installs = services.get(Installs)
            bench, piece = await bench_with_piece(c.alana)
            seq = await accepted_install(c.alana, bench, piece)
            with pytest.raises(ValueError):
                await installs.start(new(c.alana, bench, seq, piece, turn_off="automation.a\x00b"))
            assert await installs.of(c.alana.household_id, bench, seq) is None

    run(scenario())


def test_the_latest_install_of_each_piece_is_read_by_piece_and_not_across_households(db_url: str) -> None:
    async def scenario() -> None:
        async with crowd(db_url) as (_, c):
            installs = services.get(Installs)
            shop = services.get(Workshop)
            bench, one = await bench_with_piece(c.alana)
            two = (await shop.apply(c.alana, bench, add(c.alana, body(alias="b")))).piece_id
            assert two is not None
            assert await installs.latest_on_bench(c.alana.household_id, bench) == {}
            a = await accepted_install(c.alana, bench, one)
            await installs.start(new(c.alana, bench, a, one))
            await installs.finish(bench, a, "done", None)
            b = await accepted_install(c.alana, bench, one)
            await installs.start(new(c.alana, bench, b, one))
            d = await accepted_install(c.alana, bench, two)
            await installs.start(new(c.alana, bench, d, two))
            latest = await installs.latest_on_bench(c.alana.household_id, bench)
            assert set(latest) == {one, two}
            assert latest[one].started.seq == b and latest[one].ending is None and latest[two].started.seq == d
            assert await installs.latest_on_bench(c.zed.household_id, bench) == {}
            assert await installs.of(c.zed.household_id, bench, a) is None

    run(scenario())
