"""A bench's talk carries, on her answer, the pieces her commands touched answering the person's message; every
other turn and an unanswered message carry none."""

from dataclasses import replace

from ashley.api.models import ChatConversation
from ashley.db.pool import PoolDatabase
from ashley.inference.reply import Reply
from ashley.workshop.commands import Add
from ashley.workshop.model import HER, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.rules import load
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import run
from respond_support import ALANA, Fakes, wired as wired
from test_bench_opening import open_with, until
from test_workshop_routes import As, signed_in as signed_in


def talk(alana: As, bench_id: int) -> ChatConversation:
    return ChatConversation.model_validate(alana(ALANA).get(f"/api/benches/{bench_id}/conversation").json())


def test_her_answer_carries_the_pieces_her_commands_in_that_turn_touched(signed_in: As, wired: Fakes, db_url: str) -> None:
    wired.inference.script = [Reply(spoken="done", text="done")]
    bench = open_with(signed_in, ask="make two notes")
    until(lambda: [t.author for t in talk(signed_in, bench.id).turns] == ["person", "ashley"])
    person_turn, answer = talk(signed_in, bench.id).turns
    assert answer.piece_ids == [] and person_turn.piece_ids == []

    async def hers() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        try:
            shop = PostgresWorkshop(database, load())
            for title in ("a", "b"):
                done = await shop.apply(Owner(ALANA.household_id, ALANA.id), bench.id,
                                        Add(replace(HER, turn=person_turn.id), "note", Text(title, ""), "small"))
                assert done.outcome == "accepted"
        finally:
            await database.close()

    run(hers())
    turns = talk(signed_in, bench.id).turns
    assert [t.piece_ids for t in turns] == [[], [1, 2]]
