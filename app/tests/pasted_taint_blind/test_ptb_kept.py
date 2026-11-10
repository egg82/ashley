"""The origin survives a checkpoint (a resumed turn on another pod) and the block survives the conversation store, where the
judge's WORDS are read from, so a resumed turn still keeps the block out of them."""

import json
from dataclasses import replace

from ashley.channels.checkpoint import dumps, loads
from ashley.conversations.model import NewTurn
from contract.conversations_support import household, person, run, service
from inflight_blind.ifb_checkpoint_support import checkpoint
from pasted_taint_blind_support import ORIGIN, TYPED_A, inbound, message, new_turn, over, spans_of


def test_the_origin_survives_the_checkpoint_json_of_a_turn_that_carries_a_block() -> None:
    text, span = message(over())
    kept = loads(dumps(replace(checkpoint(), inbound=inbound(taint=ORIGIN, text=text, attachment=span)))).inbound
    assert kept.taint == ORIGIN and kept.text == text


def test_a_checkpoint_written_before_the_field_loads_with_no_block() -> None:
    raw = json.loads(dumps(checkpoint()))
    del raw["inbound"]["attachment"]
    assert spans_of(loads(json.dumps(raw)).inbound) == ()


def test_the_store_keeps_a_person_turns_spans_and_reads_them_back(db_url: str) -> None:
    text, span = message(over())

    async def scenario() -> None:
        home = household(db_url)
        who = person(db_url, home)
        async with service(db_url) as conversations:
            made = await conversations.start(home, "chat", [who])
            await conversations.add_turn(made.id, new_turn(text, who, [span]))
            await conversations.add_turn(made.id, NewTurn("person", TYPED_A + "plain", who))
            found = await conversations.get(made.id)
        assert found is not None
        first, second = found.turns
        assert first.text == text and spans_of(first) == (span,) and spans_of(second) == ()

    run(scenario())
