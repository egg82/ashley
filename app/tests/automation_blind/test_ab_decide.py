"""The refusals of Add, Edit, Propose, Install and Undo around an automation piece, and that only a person's Install or
Undo of one reaches the house."""

import json

import pytest
from ab_support import add, edit_text, body, bench_with_piece, carried, crowd, edit, install, installed, propose, undo
from ashley import services
from ashley.workshop.commands import Command, Proposed
from ashley.workshop.install_piece import automation_id_for
from ashley.workshop.model import HER, Owner
from ashley.workshop.workshop import BenchNotFound, Workshop
from automations_support import FakeHouse
from contract.conversations_support import db_url as db_url, run


async def outcome(owner: Owner, bench: int, command: Command) -> str:
    return (await services.get(Workshop).apply(owner, bench, command)).outcome


def test_an_add_or_edit_of_a_body_that_is_not_an_automation_config_is_bad_automation_and_changes_nothing(
        db_url: str) -> None:
    async def scenario() -> None:
        async with crowd(db_url) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            bad = ["not json", "[1]", "3", json.dumps({"alias": "a", "id": "mine"}), json.dumps({"alias": "a", "bogus": 1}),
                   json.dumps({"alias": "a", "triggers": [3]}), json.dumps({"alias": "a", "actions": "x"}),
                   json.dumps({"alias": "a", "conditions": [[]]}), json.dumps({"alias": 5})]
            for text in bad:
                assert await outcome(c.alana, bench, add(c.alana, text)) == "bad_automation", text
                assert await outcome(c.alana, bench, edit_text(c.alana, piece, text)) == "bad_automation", text
            view = await services.get(Workshop).read(c.alana, bench)
            assert [(p.id, p.version) for p in view.pieces] == [(piece, 1)]

    run(scenario())


def test_an_empty_body_is_a_draft_that_is_accepted_but_cannot_be_proposed(db_url: str) -> None:
    async def scenario() -> None:
        async with crowd(db_url) as (_, c):
            bench, piece = await bench_with_piece(c.alana, text="")
            assert await outcome(c.alana, bench, propose(piece, 1)) == "incomplete"

    run(scenario())


def test_a_config_with_no_alias_trigger_or_action_cannot_be_proposed(db_url: str) -> None:
    async def scenario() -> None:
        async with crowd(db_url) as (_, c):
            for changes in (dict(alias=""), dict(alias="  "), dict(triggers=[]), dict(actions=[])):
                bench, piece = await bench_with_piece(c.alana, text=body(**changes))
                assert await outcome(c.alana, bench, propose(piece, 1)) == "incomplete", changes

    run(scenario())


def test_a_piece_that_is_not_an_automation_is_not_installable_by_propose_or_install(db_url: str) -> None:
    async def scenario() -> None:
        async with crowd(db_url) as (_, c):
            bench, note = await bench_with_piece(c.alana, text="hello", kind="note")
            assert await outcome(c.alana, bench, propose(note, 1)) == "not_installable"
            assert await outcome(c.alana, bench, install(c.alana, bench, 1, note)) == "not_installable"

    run(scenario())


def test_a_propose_of_a_piece_not_on_the_bench_is_no_such_piece(db_url: str) -> None:
    async def scenario() -> None:
        async with crowd(db_url) as (_, c):
            bench, _ = await bench_with_piece(c.alana)
            assert await outcome(c.alana, bench, propose(99, 1)) == "no_such_piece"

    run(scenario())


def test_a_propose_at_a_version_the_piece_is_not_at_is_stale_base(db_url: str) -> None:
    async def scenario() -> None:
        async with crowd(db_url) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            assert await outcome(c.alana, bench, propose(piece, 2)) == "stale_base"
            await services.get(Workshop).apply(c.alana, bench, edit(c.alana, piece, 1, alias="v2"))
            assert await outcome(c.alana, bench, propose(piece, 1)) == "stale_base"
            assert await outcome(c.alana, bench, propose(piece, 2)) == "accepted"

    run(scenario())


def test_an_install_of_a_piece_changed_since_the_proposal_is_stale_base_and_writes_nothing(db_url: str) -> None:
    async def scenario() -> None:
        house = FakeHouse()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            proposed = await services.get(Workshop).apply(c.alana, bench, propose(piece, 1))
            await services.get(Workshop).apply(c.alana, bench, edit(c.alana, piece, 1, alias="v2"))
            applied, record = await carried(c.alana, bench, install(c.alana, bench, proposed.seq, piece))
            assert applied.outcome == "stale_base" and applied.effect is None and record is None
            assert house.writes == [] and house.configs == {}

    run(scenario())


def test_an_install_naming_no_accepted_proposal_of_that_piece_is_no_proposal(db_url: str) -> None:
    async def scenario() -> None:
        house = FakeHouse()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            other = (await services.get(Workshop).apply(c.alana, bench, add(c.alana, body(alias="b")))).piece_id
            assert other is not None
            for_other = await services.get(Workshop).apply(c.alana, bench, propose(other, 1))
            stale = await services.get(Workshop).apply(c.alana, bench, propose(piece, 5))
            assert stale.outcome == "stale_base"
            for seq in (1, 99, for_other.seq, stale.seq):
                applied, record = await carried(c.alana, bench, install(c.alana, bench, seq, piece))
                assert applied.outcome == "no_proposal" and record is None, seq
            assert house.writes == []

    run(scenario())


def test_a_proposal_is_installed_once_and_a_second_press_is_no_proposal_and_writes_nothing(db_url: str) -> None:
    async def scenario() -> None:
        house = FakeHouse()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            proposed, _, _ = await installed(c.alana, bench, piece)
            writes = list(house.writes)
            applied, record = await carried(c.alana, bench, install(c.alana, bench, proposed, piece))
            assert applied.outcome == "no_proposal" and record is None and house.writes == writes

    run(scenario())


def test_her_install_is_needs_person_and_writes_nothing(db_url: str) -> None:
    async def scenario() -> None:
        house = FakeHouse()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            proposed = await services.get(Workshop).apply(c.alana, bench, propose(piece, 1, True))
            applied, record = await carried(c.alana, bench, install(c.alana, bench, proposed.seq, piece, by=HER))
            assert applied.outcome == "needs_person" and applied.effect is None and record is None
            assert house.writes == [] and house.configs == {}
            log = await services.get(Workshop).log(c.alana, bench)
            assert log[-1].outcome == "needs_person" and log[-1].by == HER
            _, _, fine = await installed(c.alana, bench, piece, enabled=True)
            assert fine is not None and fine.ending == "done"

    run(scenario())


def test_her_install_is_needs_person_even_with_no_proposal_to_name(db_url: str) -> None:
    async def scenario() -> None:
        async with crowd(db_url) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            assert await outcome(c.alana, bench, install(c.alana, bench, 1, piece, by=HER)) in ("needs_person", "no_proposal")

    run(scenario())


def test_her_undo_of_an_install_is_needs_person_and_the_house_keeps_what_the_install_wrote(db_url: str) -> None:
    async def scenario() -> None:
        house = FakeHouse()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            _, seq, _ = await installed(c.alana, bench, piece)
            writes = list(house.writes)
            applied, record = await carried(c.alana, bench, undo(c.alana, seq, by=HER))
            assert applied.outcome == "needs_person" and record is None
            assert house.writes == writes and automation_id_for(bench, piece) in house.configs
            applied, record = await carried(c.alana, bench, undo(c.alana, seq))
            assert applied.outcome == "accepted" and record is not None and record.ending == "done"

    run(scenario())


def test_a_propose_changes_no_piece_and_cannot_be_undone(db_url: str) -> None:
    async def scenario() -> None:
        house = FakeHouse()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            before = await services.get(Workshop).read(c.alana, bench)
            proposed = await services.get(Workshop).apply(c.alana, bench, propose(piece, 1, True, "automation.x"))
            assert proposed.outcome == "accepted" and proposed.effect == Proposed(piece, 1, True, "automation.x")
            after = await services.get(Workshop).read(c.alana, bench)
            assert after.pieces == before.pieces
            assert await outcome(c.alana, bench, undo(c.alana, proposed.seq)) == "nothing_to_undo"
            assert house.writes == []

    run(scenario())


def test_an_undo_of_an_install_after_the_piece_changed_again_is_changed_since_and_writes_nothing(db_url: str) -> None:
    async def scenario() -> None:
        house = FakeHouse()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            _, seq, _ = await installed(c.alana, bench, piece)
            await services.get(Workshop).apply(c.alana, bench, edit(c.alana, piece, 1, alias="v2"))
            writes = list(house.writes)
            applied, record = await carried(c.alana, bench, undo(c.alana, seq))
            assert applied.outcome == "changed_since" and record is None and house.writes == writes

    run(scenario())


def test_an_install_cannot_be_undone_twice(db_url: str) -> None:
    async def scenario() -> None:
        house = FakeHouse()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            _, seq, _ = await installed(c.alana, bench, piece)
            await carried(c.alana, bench, undo(c.alana, seq))
            writes = list(house.writes)
            applied, record = await carried(c.alana, bench, undo(c.alana, seq))
            assert applied.outcome != "accepted" and record is None and house.writes == writes

    run(scenario())


def test_another_household_cannot_propose_install_or_undo_on_the_bench(db_url: str) -> None:
    async def scenario() -> None:
        house = FakeHouse()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            proposed, seq, _ = await installed(c.alana, bench, piece)
            writes = list(house.writes)
            for command in (propose(piece, 1), install(c.zed, bench, proposed, piece), undo(c.zed, seq)):
                with pytest.raises(BenchNotFound):
                    await services.get(Workshop).apply(c.zed, bench, command)
            assert house.writes == writes

    run(scenario())


def test_a_housemate_cannot_install_on_a_bench_that_is_not_theirs(
        db_url: str) -> None:
    async def scenario() -> None:
        async with crowd(db_url) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            proposed = await services.get(Workshop).apply(c.alana, bench, propose(piece, 1))
            with pytest.raises(BenchNotFound):
                await services.get(Workshop).apply(c.sam, bench, install(c.sam, bench, proposed.seq, piece))

    run(scenario())
