"""`Conversations.of_person` on one thread: every conversation the thread has carried, closed ones included, once the
thread has moved on to a newer one; another thread's, another person's and a conversation that was never on a thread
are not listed."""

from ashley.conversations.model import NewTurn
from conversations_support import household, person, place_before_now, run, service


def test_a_thread_lists_every_conversation_it_carried_closed_and_open(db_url: str) -> None:
    home = household(db_url)
    mine, yours = person(db_url, home), person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            first = await conv.for_thread(home, "bench:1", "brainstorm", [mine])
            await conv.add_turn(first.id, NewTurn("person", "screws?", mine))
            other = await conv.for_thread(home, "bench:2", "brainstorm", [mine])
            await conv.add_turn(other.id, NewTurn("person", "elsewhere", mine))
            unthreaded = await conv.start(home, "brainstorm", [mine])
            await conv.add_turn(unthreaded.id, NewTurn("person", "no thread", mine))
            theirs = await conv.for_thread(home, "bench:3", "brainstorm", [yours])
            await conv.add_turn(theirs.id, NewTurn("person", "not mine", yours))
            place_before_now(db_url, first.id, 2_000_000)
            second = await conv.for_thread(home, "bench:1", "brainstorm", [mine])
            await conv.add_turn(second.id, NewTurn("person", "again", mine))
            assert second.id != first.id
            page = await conv.of_person(home, mine, 10, thread="bench:1")
            assert [(s.id, s.state) for s in page.items] == [(second.id, "open"), (first.id, "closed")]
            assert (await conv.of_person(home, yours, 10, thread="bench:1")).items == ()
            assert [s.id for s in (await conv.of_person(home, mine, 10, thread="bench:2")).items] == [other.id]

    run(scenario())


def test_a_thread_pages_by_the_same_cursor(db_url: str) -> None:
    home = household(db_url)
    mine = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            made: list[int] = []
            for _ in range(3):
                found = await conv.for_thread(home, "bench:1", "brainstorm", [mine])
                await conv.add_turn(found.id, NewTurn("person", "hi", mine))
                made.append(found.id)
                place_before_now(db_url, found.id, 2_000_000)
            first = await conv.of_person(home, mine, 2, thread="bench:1")
            assert first.next is not None
            rest = await conv.of_person(home, mine, 2, first.next, thread="bench:1")
            assert [s.id for s in (*first.items, *rest.items)] == made[::-1] and rest.next is None

    run(scenario())
