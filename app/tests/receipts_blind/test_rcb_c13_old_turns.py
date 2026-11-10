"""Contract 13: a stored turn whose text holds the old blocks is read and rendered unchanged: not stripped, not given
receipts, not given a history line, and the turn loop goes on over it."""

from ashley import services
from ashley.channels.prompt import messages
from ashley.channels.respond import respond
from ashley.conversations.conversations import Conversations
from ashley.conversations.model import NewTurn, Turn
from contract.conversations_support import run
from receipts_blind_support import (ANSWER, OKAY, OLD_DONE_INTRO, OLD_HELD_INTRO, World, database, hers, settled)
from receipts_blind_wire_support import AT, conversation, open_app, turn
from respond_support import ALANA, HOME

OLD = f"I looked.\n\n{OLD_DONE_INTRO}\n- house_do (action: light.turn_on)\n\n{OLD_HELD_INTRO}\n- mail_label (folder: \"archive\")"


def test_c13_the_web_serves_an_old_turn_as_stored_with_no_receipts() -> None:
    for page in open_app(conversation(turn(1, "person", "do it"), turn(2, "ashley", OLD, None, answers=1))):
        her = page.turns()[1]
        assert her["text"] == OLD and her["receipts"] is None


def test_c13_the_prompt_carries_an_old_turn_as_stored() -> None:
    old = Turn(1, "ashley", None, OLD, AT, answers=0)
    asked = Turn(2, "person", ALANA.id, "again", AT)
    (earlier, _) = messages([old], asked, HOME)
    assert earlier.text.endswith(f") {OLD}") and earlier.text.count(OLD_HELD_INTRO) == 1


def test_c13_a_stored_old_turn_reads_back_whole_and_a_new_turn_goes_on_over_it(world: World) -> None:
    async def go() -> None:
        async with database(world):
            convs = services.get(Conversations)
            conv = await convs.for_thread(world.who.household_id, f"person:{world.who.id}:web", "chat", [world.who.id],
                                          remembered=True, channel="web", place=None)
            said = await convs.add_turn(conv.id, NewTurn("person", "do it", world.who.id, "private", world.who.id))
            await convs.add_turn(conv.id, NewTurn("ashley", OLD, None, "private", world.who.id, answers=said.id))
            world.as_pod(world.first)
            world.first.model.script = [ANSWER]
            await respond(world.web("and now"))
            await settled(conv.id, 2)
            texts = [t.text for t in await hers(conv.id)]
            assert texts == [OLD, OKAY]
            assert all(t.receipts is None for t in await hers(conv.id))

    run(go())
