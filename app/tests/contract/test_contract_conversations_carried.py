"""`Conversations.carried`: a reply's recent turns cross conversation boundaries up to a budget, relevant older turns
are found by their words, and every turn passes who-may-hear-it for the hearer: a turn private to A reaches only A
alone, a shared one anyone in the household, a turn from before turns recorded it no one, another household's never.
What the filter held back is counted, never returned."""

import pytest
from ashley.conversations.model import Hearer, NewTurn, Place
from conversations_support import household, person, run, scalar, service

PRIVATE = "my therapist moved the appointment to thursday"


def _texts(turns: tuple[object, ...]) -> list[str]:
    return [getattr(t, "text") for t in turns]


def test_recent_turns_cross_conversations_oldest_first_up_to_the_budget(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            earlier = await conv.start(home, "chat", [alana])
            for text in ("one", "two", "three"):
                await conv.add_turn(earlier.id, NewTurn("person", text, alana, "shared"))
            now = await conv.start(home, "chat", [alana])
            await conv.add_turn(now.id, NewTurn("ashley", "four", heard="shared"))
            said = await conv.add_turn(now.id, NewTurn("person", "five", alana, "shared"))
            hearer = Hearer(home, alana, owner_only=False)
            got = await conv.carried(hearer, now.id, said.id, "five", 3, 0)
            assert _texts(got.recent) == ["two", "three", "four"]
            assert (await conv.carried(hearer, now.id, said.id, "five", 0, 0)).recent == ()

    run(scenario())


def test_an_unknown_speaker_carries_only_this_conversation(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            earlier = await conv.start(home, "chat", [alana])
            await conv.add_turn(earlier.id, NewTurn("person", "before", alana, "shared"))
            now = await conv.start(home, "chat", [])
            await conv.add_turn(now.id, NewTurn("person", "here", None, "shared"))
            said = await conv.add_turn(now.id, NewTurn("person", "now", None, "shared"))
            got = await conv.carried(Hearer(home, None, False), now.id, said.id, "now", 10, 0)
            assert _texts(got.recent) == ["here"]

    run(scenario())


@pytest.mark.parametrize(("speaker", "owner_only", "heard"), [
    ("alana", True, True), ("alana", False, False), ("sam", True, False), ("sam", False, False), (None, False, False)])
def test_a_private_turn_reaches_only_its_owner_alone(db_url: str, speaker: str | None, owner_only: bool,
                                                     heard: bool) -> None:
    home = household(db_url)
    people = {"alana": person(db_url, home), "sam": person(db_url, home)}
    alana = people["alana"]

    async def scenario() -> None:
        async with service(db_url) as conv:
            web = await conv.start(home, "chat", [alana])
            await conv.add_turn(web.id, NewTurn("person", PRIVATE, alana, "private", alana))
            await conv.add_turn(web.id, NewTurn("ashley", "noted, thursday it is", heard="private", owner_id=alana))
            kitchen = await conv.start(home, "chat", [alana, people["sam"]])
            said = await conv.add_turn(kitchen.id, NewTurn("person", "when is the appointment", alana, "shared"))
            hearer = Hearer(home, None if speaker is None else people[speaker], owner_only)
            got = await conv.carried(hearer, kitchen.id, said.id, "therapist appointment thursday", 10, 10)
            carried = _texts(got.recent) + _texts(got.relevant)
            assert (PRIVATE in carried) is heard
            assert ("noted, thursday it is" in carried) is heard
            assert got.filtered == (0 if heard else 2)

    run(scenario())


def test_shared_turns_reach_anyone_in_the_household_and_no_other(db_url: str) -> None:
    home, elsewhere = household(db_url), household(db_url)
    alana, sam, far = person(db_url, home), person(db_url, home), person(db_url, elsewhere)

    async def scenario() -> None:
        async with service(db_url) as conv:
            kitchen = await conv.start(home, "chat", [alana])
            await conv.add_turn(kitchen.id, NewTurn("person", "the boiler is making a noise", alana, "shared"))
            there = await conv.start(elsewhere, "chat", [far])
            await conv.add_turn(there.id, NewTurn("person", "our boiler is fine", far, "shared"))
            dm = await conv.start(home, "chat", [sam])
            said = await conv.add_turn(dm.id, NewTurn("person", "boiler?", sam, "private", sam))
            got = await conv.carried(Hearer(home, sam, True), dm.id, said.id, "boiler", 10, 10)
            assert _texts(got.relevant) == ["the boiler is making a noise"]
            assert got.recent == () and got.filtered == 0

    run(scenario())


def test_a_turn_stored_before_hearing_was_recorded_is_carried_by_no_one(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            talk = await conv.start(home, "chat", [alana])
            old = await conv.add_turn(talk.id, NewTurn("person", "an old boiler turn", alana, "shared"))
            scalar(db_url, "UPDATE turns SET visibility = 'private', owner_id = NULL WHERE id = %s RETURNING id",
                   (old.id,))
            said = await conv.add_turn(talk.id, NewTurn("person", "boiler", alana, "private", alana))
            got = await conv.carried(Hearer(home, alana, True), talk.id, said.id, "boiler", 10, 10)
            assert got.recent == () and got.relevant == () and got.filtered == 1

    run(scenario())


def test_relevant_turns_leave_out_the_recent_ones_and_rank_by_match(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            old = await conv.start(home, "chat", [alana])
            for text in ("the garden gate is broken", "the gate and the garden fence", "lunch was nice"):
                await conv.add_turn(old.id, NewTurn("person", text, alana, "shared"))
            now = await conv.start(home, "chat", [alana])
            await conv.add_turn(now.id, NewTurn("person", "the garden gate again", alana, "shared"))
            said = await conv.add_turn(now.id, NewTurn("person", "garden gate", alana, "shared"))
            got = await conv.carried(Hearer(home, alana, False), now.id, said.id, "garden gate", 1, 5)
            assert _texts(got.recent) == ["the garden gate again"]
            assert set(_texts(got.relevant)) == {"the garden gate is broken", "the gate and the garden fence"}
            assert (await conv.carried(Hearer(home, alana, False), now.id, said.id, "garden gate", 1, 1)).relevant[0].text \
                in {"the garden gate is broken", "the gate and the garden fence"}

    run(scenario())


def test_the_recent_filtered_count_stops_at_the_oldest_turn_carried(db_url: str) -> None:
    home = household(db_url)
    alana, sam = person(db_url, home), person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            talk = await conv.start(home, "chat", [alana])
            await conv.add_turn(talk.id, NewTurn("person", "very old private", alana, "private", alana))
            await conv.add_turn(talk.id, NewTurn("person", "kept one", alana, "shared"))
            await conv.add_turn(talk.id, NewTurn("person", "newer private", alana, "private", alana))
            await conv.add_turn(talk.id, NewTurn("person", "kept two", alana, "shared"))
            said = await conv.add_turn(talk.id, NewTurn("person", "zzz", sam, "shared"))
            hearer = Hearer(home, sam, False)
            assert (await conv.carried(hearer, talk.id, said.id, "zzz", 2, 0)).filtered == 1
            assert (await conv.carried(hearer, talk.id, said.id, "zzz", 5, 0)).filtered == 2

    run(scenario())


@pytest.mark.parametrize(("recent", "relevant"), [(-1, 0), (0, -1)])
def test_a_negative_budget_is_refused(db_url: str, recent: int, relevant: int) -> None:
    async def scenario() -> None:
        async with service(db_url) as conv:
            with pytest.raises(ValueError):
                await conv.carried(Hearer(1, None, False), 1, 1, "x", recent, relevant)

    run(scenario())


def test_a_conversation_she_does_not_remember_is_carried_only_by_its_own_replies(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            harness = await conv.start(home, "chat", [alana], remembered=False)
            await conv.add_turn(harness.id, NewTurn("person", "an eval about the boiler", alana, "shared"))
            mine = await conv.start(home, "chat", [alana])
            said = await conv.add_turn(mine.id, NewTurn("person", "boiler", alana, "shared"))
            got = await conv.carried(Hearer(home, alana, False), mine.id, said.id, "boiler", 10, 10)
            assert got.recent == () and got.relevant == () and got.filtered == 0
            again = await conv.add_turn(harness.id, NewTurn("person", "boiler", alana, "shared"))
            within = await conv.carried(Hearer(home, alana, False), harness.id, again.id, "boiler", 10, 10)
            assert _texts(within.recent) == ["an eval about the boiler", "boiler"]

    run(scenario())


def test_a_recent_turn_says_where_it_was_said_unless_it_is_this_thread(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home)
    title = 'Cord "hole"\n(v2)'
    bench = int(scalar(db_url, "INSERT INTO benches (household_id, owner_id, title) VALUES (%s, %s, %s) RETURNING id",
                       (home, alana, title)))
    other = int(scalar(db_url, "INSERT INTO benches (household_id, owner_id, title) VALUES (%s, %s, 'Shelf') RETURNING id",
                       (home, alana)))

    async def scenario() -> None:
        async with service(db_url) as conv:
            here_before = await conv.for_thread(home, f"bench:{other}", "brainstorm", [alana])
            asked = await conv.add_turn(here_before.id, NewTurn("ashley", "Shall I fix crack()?", None, "shared"))
            elsewhere = await conv.for_thread(home, f"bench:{bench}", "brainstorm", [alana])
            cord = await conv.add_turn(elsewhere.id, NewTurn("ashley", "Does the cord hole fit?", None, "shared"))
            web = await conv.for_thread(home, f"person:{alana}:web", "chat", [alana])
            chat = await conv.add_turn(web.id, NewTurn("person", "hello", alana, "shared"))
            now = await conv.for_thread(home, f"bench:{other}", "brainstorm", [alana])
            same = await conv.add_turn(now.id, NewTurn("ashley", "Still here", None, "shared"))
            said = await conv.add_turn(now.id, NewTurn("person", "yeah", alana, "shared"))
            got = await conv.carried(Hearer(home, alana, owner_only=False), now.id, said.id, "yeah", 10, 0)
            assert _texts(got.recent) == ["Shall I fix crack()?", "Does the cord hole fit?", "hello", "Still here"]
            assert got.places == {cord.id: Place(f"bench:{bench}", title), chat.id: Place(f"person:{alana}:web", None)}
            assert asked.id not in got.places and same.id not in got.places

    run(scenario())
