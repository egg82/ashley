"""The value objects and their storage (spec INTERFACES): `Receipts` holds its invariant, round-trips through JSON, and is
stored with her turn and read back whole; a turn that is not hers refuses it."""

import pytest
from ashley import services
from ashley.conversations.conversations import Conversations
from ashley.conversations.model import NewTurn, Receipt, Receipts
from contract.conversations_support import run
from receipts_blind_support import OKAY, World, database

ONE = Receipt("Changed something in the house", "house_do (action: light.turn_on)", "You asked for it.")
TWO = Receipt("Moved an email to a folder", None, None)
SHAPES = [Receipts((ONE,), (), None), Receipts((), (TWO,), 4), Receipts((ONE, TWO), (TWO, ONE), 9)]


def test_a_snapshot_with_nothing_in_it_is_refused() -> None:
    with pytest.raises(ValueError):
        Receipts((), (), None)


@pytest.mark.parametrize(("done", "held", "proposal"), [((ONE,), (), 3), ((), (TWO,), None), ((ONE,), (TWO,), None)])
def test_a_proposal_id_is_set_exactly_when_something_is_held(done: tuple[Receipt, ...], held: tuple[Receipt, ...],
                                                              proposal: int | None) -> None:
    with pytest.raises(ValueError):
        Receipts(done, held, proposal)


@pytest.mark.parametrize("shape", SHAPES)
def test_json_round_trips_and_names_done_held_and_proposal_id(shape: Receipts) -> None:
    out = shape.to_json()
    assert set(out) == {"done", "held", "proposal_id"} and out["proposal_id"] == shape.proposal_id
    assert Receipts.from_json(out) == shape


@pytest.mark.parametrize("shape", SHAPES)
def test_her_turn_stores_the_snapshot_and_reads_it_back_whole(world: World, shape: Receipts) -> None:
    async def go() -> None:
        async with database(world):
            convs = services.get(Conversations)
            conv = await convs.for_thread(world.who.household_id, "person:1:web", "chat", [world.who.id],
                                          remembered=True, channel="web", place=None)
            said = await convs.add_turn(conv.id, NewTurn("person", "do it", world.who.id, "private", world.who.id))
            hers = await convs.add_turn(conv.id, NewTurn("ashley", OKAY, None, "private", world.who.id, answers=said.id,
                                                         receipts=shape))
            assert hers.receipts == shape
            found = await convs.get(conv.id)
            assert found is not None and [t.receipts for t in found.turns] == [None, shape]

    run(go())


@pytest.mark.parametrize("author", ["person", "household"])
def test_a_turn_that_is_not_hers_refuses_receipts(world: World, author: str) -> None:
    async def go() -> None:
        async with database(world):
            convs = services.get(Conversations)
            conv = await convs.for_thread(world.who.household_id, "person:1:web", "chat", [world.who.id],
                                          remembered=True, channel="web", place=None)
            speaker = world.who.id if author == "person" else None
            with pytest.raises(ValueError):
                await convs.add_turn(conv.id, NewTurn("person" if author == "person" else "household", "hello", speaker,
                                                      receipts=SHAPES[0]))
            found = await convs.get(conv.id)
            assert found is not None and found.turns == ()

    run(go())
