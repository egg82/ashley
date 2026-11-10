"""The turn that opens a bench adds at most `BenchToolsConfig.lead_adds` pieces; its next bench_add is refused
`ask_first`. Edits and every other turn are not capped. `ashley.tools.bench_lead.lead(adds)` names the cap."""

import dataclasses
import json

import pytest
from ashley.channels.model import Inbound
from ashley.channels.turn_tools import for_turn
from ashley.inference.model import ToolResult
from ashley.tools import bench_config, bench_lead
from ashley.tools.arrival import Arrival
from ashley.tools.bench_config import BenchToolsConfig
from ashley.tools.bench_tools import BenchTools
from ashley.tools.tools import Tools
from bq_support import Real, add_piece, inbound, owner_of, piece_count, real, tc
from contract.conversations_support import run

CONFIG = bench_config.load()
CAP = CONFIG.lead_adds


def lead_tools(r: Real, bench: int, adds: int = CAP) -> BenchTools:
    w = r.world
    return BenchTools(w.home, w.alana, bench, config=dataclasses.replace(CONFIG, lead_adds=adds), lead=True)


async def adds(tools: Tools, n: int) -> list[ToolResult]:
    return [await tools.call(add_piece(f"p{i}")) for i in range(n)]


async def opened(r: Real) -> int:
    return (await r.workshop.open(owner_of(r.world, r.world.alana), "bench")).id


def test_the_shipped_cap_is_two() -> None:
    assert CAP == 2


def test_the_cap_boundary_two_accepted_the_third_refused(db_url: str) -> None:
    async def scenario() -> None:
        async with real(db_url) as r:
            bench = await opened(r)
            first, second, third = await adds(lead_tools(r, bench), CAP + 1)
            assert not first.is_error and not second.is_error
            assert third.is_error and "ask_first" in third.content
            assert await piece_count(r, r.world.alana, bench) == CAP

    run(scenario())


def test_the_refusal_holds_for_every_later_add_of_the_turn(db_url: str) -> None:
    async def scenario() -> None:
        async with real(db_url) as r:
            bench = await opened(r)
            got = await adds(lead_tools(r, bench), CAP + 3)
            assert [x.is_error for x in got] == [False] * CAP + [True] * 3
            assert all("ask_first" in x.content for x in got[CAP:])
            assert await piece_count(r, r.world.alana, bench) == CAP

    run(scenario())


@pytest.mark.parametrize("cap", [1, 3, 5])
def test_the_cap_is_the_configured_number(db_url: str, cap: int) -> None:
    async def scenario() -> None:
        async with real(db_url) as r:
            bench = await opened(r)
            got = await adds(lead_tools(r, bench, cap), cap + 1)
            assert [x.is_error for x in got] == [False] * cap + [True]
            assert "ask_first" in got[-1].content

    run(scenario())


def test_a_turn_that_is_not_a_lead_adds_without_a_cap(db_url: str) -> None:
    async def scenario() -> None:
        async with real(db_url) as r:
            bench = await opened(r)
            plain = BenchTools(r.world.home, r.world.alana, bench)
            got = await adds(plain, CAP + 4)
            assert not any(x.is_error for x in got)
            assert await piece_count(r, r.world.alana, bench) == CAP + 4

    run(scenario())


def test_each_lead_instance_counts_its_own_turn(db_url: str) -> None:
    async def scenario() -> None:
        async with real(db_url) as r:
            bench = await opened(r)
            assert [x.is_error for x in await adds(lead_tools(r, bench), CAP + 1)] == [False] * CAP + [True]
            assert [x.is_error for x in await adds(lead_tools(r, bench), CAP + 1)] == [False] * CAP + [True]
            assert await piece_count(r, r.world.alana, bench) == 2 * CAP

    run(scenario())


def test_an_add_the_bench_refuses_for_another_reason_does_not_use_the_allowance(db_url: str) -> None:
    async def scenario() -> None:
        async with real(db_url) as r:
            bench = await opened(r)
            tools = lead_tools(r, bench)
            blank = await tools.call(tc("bench_add", kind="note", title=" \t ", body="b", size="small"))
            assert blank.is_error and "ask_first" not in blank.content
            got = await adds(tools, CAP + 1)
            assert [x.is_error for x in got] == [False] * CAP + [True]
            assert await piece_count(r, r.world.alana, bench) == CAP

    run(scenario())


def test_edits_and_reads_are_not_capped_after_the_adds_are(db_url: str) -> None:
    async def scenario() -> None:
        async with real(db_url) as r:
            bench = await opened(r)
            tools = lead_tools(r, bench)
            await adds(tools, CAP + 1)
            view = await r.workshop.read(owner_of(r.world, r.world.alana), bench)
            piece = view.pieces[0]
            assert not (await tools.call(tc("bench_read"))).is_error
            assert not (await tools.call(tc("bench_read_piece", piece_id=piece.id))).is_error
            for n in range(CAP + 2):
                version = (await r.workshop.read(owner_of(r.world, r.world.alana), bench)).pieces[0].version
                edited = await tools.call(tc("bench_edit", piece_id=piece.id, base_version=version, title="e",
                                             body=f"body {n}"))
                assert not edited.is_error, edited.content
            after = await r.workshop.read(owner_of(r.world, r.world.alana), bench)
            assert next(p for p in after.pieces if p.id == piece.id).text.body == f"body {CAP + 1}"

    run(scenario())


def _inbound(r: Real, lead: bool, bench: int) -> Inbound:
    return dataclasses.replace(inbound("chat", speaker_id=r.world.alana, household_id=r.world.home, thread="t"),
                               bench_id=bench, lead=lead)


def test_a_bench_message_that_opened_the_bench_is_capped_through_the_turn_seam(db_url: str) -> None:
    async def scenario() -> None:
        async with real(db_url) as r:
            bench = await opened(r)
            turn = for_turn(_inbound(r, True, bench))
            got = await adds(turn, CAP + 1)
            assert [x.is_error for x in got] == [False] * CAP + [True]
            assert "ask_first" in got[-1].content

    run(scenario())


def test_a_bench_opened_in_this_turn_is_capped_through_the_turn_seam(db_url: str) -> None:
    async def scenario() -> None:
        async with real(db_url) as r:
            bench = await opened(r)
            arrival = Arrival(bench)
            arrival.opened(bench)
            turn = for_turn(_inbound(r, False, bench), arrival=arrival)
            got = await adds(turn, CAP + 1)
            assert [x.is_error for x in got] == [False] * CAP + [True]

    run(scenario())


def test_a_bench_that_was_already_open_is_not_capped_through_the_turn_seam(db_url: str) -> None:
    async def scenario() -> None:
        async with real(db_url) as r:
            bench = await opened(r)
            got = await adds(for_turn(_inbound(r, False, bench), arrival=Arrival(bench)), CAP + 3)
            assert not any(x.is_error for x in got)
            got = await adds(for_turn(_inbound(r, False, bench)), 2)
            assert not any(x.is_error for x in got)

    run(scenario())


def test_the_lead_guidance_names_the_number_it_is_given() -> None:
    assert "37" in bench_lead.lead(37)
    assert "37" not in bench_lead.lead(2)
    assert bench_lead.lead(2) != bench_lead.lead(3)


def test_only_a_lead_catalogue_carries_the_lead_guidance(db_url: str) -> None:
    async def scenario() -> None:
        async with real(db_url) as r:
            bench = await opened(r)
            led = (await lead_tools(r, bench, 29).catalogue()).instructions or ""
            plain = (await BenchTools(r.world.home, r.world.alana, bench).catalogue()).instructions or ""
            assert bench_lead.lead(29) in led
            assert bench_lead.lead(CAP) not in plain and "ask_first" not in plain

    run(scenario())


def test_the_config_reads_lead_adds_and_refuses_what_is_not_a_positive_integer() -> None:
    raw = {f.name: getattr(CONFIG, f.name) for f in dataclasses.fields(BenchToolsConfig)}
    assert bench_config.parse(json.loads(json.dumps(raw))).lead_adds == CAP
    for bad in (0, -1, True, 1.5, "2", None):
        with pytest.raises(ValueError):
            bench_config.parse({**raw, "lead_adds": bad})
    missing = {k: v for k, v in raw.items() if k != "lead_adds"}
    with pytest.raises(ValueError):
        bench_config.parse(missing)
    with pytest.raises(ValueError):
        bench_config.parse({**raw, "lead_adds_extra": 1})
