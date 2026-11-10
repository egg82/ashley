"""What she is offered from the tidy pass on a bench read, and how a finding ends: dismissed by her, or gone with the
text it pointed at."""

import json

from ashley import services
from ashley.inference.model import ToolCall
from ashley.tidy import run
from ashley.tidy.config import load as load_config
from ashley.tools.bench_tidy import BenchTidyTools
from ashley.tools.bench_tools import BenchTools
from ashley.workshop.commands import Edit
from ashley.workshop.model import By, Text
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from tidy_support import CODE_STATUS, HEADER, STALE, Bench, found, scenario, two_notes

CONFIG = load_config()


async def read_to_check(bench: Bench) -> list[dict[str, object]]:
    got = await BenchTools(bench.owner.household_id, bench.owner.person_id, bench.id).call(ToolCall("r", "bench_read", {}))
    assert not got.is_error, got.content
    return list(json.loads(got.content).get("to_check", []))


async def dismiss(bench: Bench, finding_id: object) -> tuple[bool, str]:
    got = await BenchTidyTools(bench.id).call(ToolCall("d", "bench_dismiss", {"finding_id": finding_id}))
    return got.is_error, got.content


def test_her_bench_read_lists_the_findings_to_verify_and_a_bench_with_none_has_no_such_field(db_url: str) -> None:
    async def body(bench: Bench) -> None:
        status, decompile = await two_notes(bench)
        assert await read_to_check(bench) == []
        await run.after_turn(bench.owner, bench.id)
        listed = await read_to_check(bench)
        assert [(f["piece_id"], f["kind"], f["quote"], f["other_piece_id"]) for f in listed] == [
            (status, "debris", HEADER, None), (status, "superseded", STALE, decompile),
            (listed[2]["piece_id"], "contradicts", listed[2]["quote"], status)]
        assert set(listed[0]) == {"id", "piece_id", "kind", "quote", "other_piece_id", "why"}

    scenario(db_url, body)


def test_a_dismissed_finding_is_not_offered_and_the_same_passage_is_not_pointed_at_again(db_url: str) -> None:
    async def body(bench: Bench) -> None:
        status, _ = await two_notes(bench)
        await run.after_turn(bench.owner, bench.id)
        first = (await read_to_check(bench))[0]
        assert await dismiss(bench, first["id"]) == (False, json.dumps({"dismissed": first["id"]}))
        assert first["id"] not in [f["id"] for f in await read_to_check(bench)]
        await services.get(Workshop).apply(bench.owner, bench.id, Edit(By(bench.owner.person_id), status, 1,
                                                                       Text("t", CODE_STATUS.body + "\nmore")))
        await run.after_turn(bench.owner, bench.id)                      # the model points at the same passages again
        assert first["quote"] not in [f["quote"] for f in await read_to_check(bench)]
        assert len(await read_to_check(bench)) == 2

    scenario(db_url, body)


def test_an_edit_that_removes_the_quoted_passage_clears_its_finding_and_the_others_stay(db_url: str) -> None:
    async def body(bench: Bench) -> None:
        status, _ = await two_notes(bench)
        await run.after_turn(bench.owner, bench.id)
        mended = CODE_STATUS.body.replace(HEADER, "To confirm for the roof pitch (rafter cut, ridge height):")
        await services.get(Workshop).apply(bench.owner, bench.id, Edit(By(None), status, 1, Text(CODE_STATUS.title, mended)))
        assert [f["kind"] for f in await read_to_check(bench)] == ["superseded", "contradicts"]
        assert [f.quote for f in await bench.tidy.findings(bench.id)].count(HEADER) == 0   # deleted, not hidden

    scenario(db_url, body)


def test_a_dismissal_the_bench_does_not_hold_is_an_error_and_another_benchs_finding_is_out_of_reach(db_url: str) -> None:
    async def body(bench: Bench) -> None:
        await two_notes(bench)
        await run.after_turn(bench.owner, bench.id)
        mine = (await read_to_check(bench))[0]["id"]
        failed, message = await dismiss(bench, 999999)
        assert failed and message.startswith("no_such_finding:")
        elsewhere = await BenchTidyTools(bench.id + 1).call(ToolCall("d", "bench_dismiss", {"finding_id": mine}))
        assert elsewhere.is_error and elsewhere.content.startswith("no_such_finding:")
        assert len(await read_to_check(bench)) == 3
        assert (await dismiss(bench, "1"))[0] and (await BenchTidyTools(bench.id).call(
            ToolCall("d", "bench_dismiss", {"finding_id": 1, "x": 2}))).is_error

    scenario(db_url, body)


def test_a_read_offers_no_more_than_the_configured_few(db_url: str) -> None:
    async def body(bench: Bench) -> None:
        status, _ = await two_notes(bench)
        bench.inference.reply.findings.clear()
        words = CODE_STATUS.body.split("\n\n")
        bench.inference.reply.findings.extend(found(status, "duplicate", w[:30]) for w in words * 2)
        await run.after_turn(bench.owner, bench.id)
        assert 0 < len(await read_to_check(bench)) <= CONFIG.shown

    scenario(db_url, body)
