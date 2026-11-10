"""What she carries when the owner speaks on a bench after its talk closed: the earlier talk on the bench's thread, by
the same carry every conversation gets, built from the turns' own hearing as the bench's inbound records it."""

from ashley.api.bench_talk import inbound_for
from ashley.api.models import ChatRequest
from ashley.channels.history import hearer, heard
from ashley.conversations.model import NewTurn
from ashley.people.model import Person
from ashley.signin.model import SignedIn
from conversations_support import household, person, place_before_now, run, service


def test_her_next_turn_on_a_bench_carries_the_talk_that_closed(db_url: str) -> None:
    home = household(db_url)
    me = person(db_url, home)
    who = Person(me, home, "Alana")
    inbound = inbound_for(SignedIn(1, who), 7, ChatRequest(text="and the washers?"))
    how, owner = heard(inbound, who)

    async def scenario() -> None:
        async with service(db_url) as conv:
            first = await conv.for_thread(home, inbound.thread, "brainstorm", [me])
            asked = await conv.add_turn(first.id, NewTurn("person", "which screws?", me, how, owner))
            await conv.add_turn(first.id, NewTurn("ashley", "M3, ten of them.", None, how, owner, answers=asked.id))
            place_before_now(db_url, first.id, 2_000_000)
            second = await conv.for_thread(home, inbound.thread, "brainstorm", [me])
            assert second.id != first.id
            said = await conv.add_turn(second.id, NewTurn("person", inbound.text, me, how, owner))
            got = await conv.carried(hearer(inbound, who), second.id, said.id, inbound.text, 80, 5)
            assert [t.text for t in got.recent] == ["which screws?", "M3, ten of them."]
            assert got.filtered == 0

    run(scenario())
