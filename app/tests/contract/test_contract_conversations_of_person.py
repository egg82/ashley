"""`Conversations.of_person`: a person's conversations across channels, newest activity first, paged by cursor, with
where each started and how many turns it has; those they did not take part in, those with no turn and another
household's are not listed; it reads only and logs ids and counts."""

import pytest
from ashley import logs
from ashley.conversations.model import NewTurn
from conversations_support import events, household, person, place_before_now, run, service


def test_a_person_lists_their_conversations_newest_activity_first_with_where_and_how_much(db_url: str) -> None:
    home = household(db_url)
    mine, yours = person(db_url, home), person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            old = await conv.start(home, "chat", [mine], channel="voice", place="kitchen")
            await conv.add_turn(old.id, NewTurn("person", "hello", mine))
            await conv.add_turn(old.id, NewTurn("ashley", "hi"))
            new = await conv.start(home, "command", [mine, yours])
            await conv.add_turn(new.id, NewTurn("person", "lights", yours))
            place_before_now(db_url, old.id, 50_000)
            page = await conv.of_person(home, mine, 10)
        assert page.next is None
        assert [s.id for s in page.items] == [new.id, old.id]
        newest, oldest = page.items
        assert (oldest.kind, oldest.channel, oldest.place, oldest.turns) == ("chat", "voice", "kitchen", 2)
        assert (newest.kind, newest.channel, newest.place, newest.turns, newest.state) == ("command", None, None, 1, "open")
        assert oldest.state == "closed" and oldest.started_at <= oldest.last_activity_at

    run(scenario())


def test_only_conversations_they_took_part_in_with_a_turn_in_their_household(db_url: str) -> None:
    home, elsewhere = household(db_url), household(db_url)
    mine, yours = person(db_url, home), person(db_url, home)
    stranger = person(db_url, elsewhere)

    async def scenario() -> None:
        async with service(db_url) as conv:
            shared = await conv.start(home, "chat", [mine])
            await conv.add_turn(shared.id, NewTurn("person", "mine", mine))
            others = await conv.start(home, "chat", [yours])
            await conv.add_turn(others.id, NewTurn("person", "yours", yours))
            await conv.start(home, "chat", [mine])
            far = await conv.start(elsewhere, "chat", [stranger])
            await conv.add_turn(far.id, NewTurn("person", "far", stranger))
            assert [s.id for s in (await conv.of_person(home, mine, 10)).items] == [shared.id]
            assert (await conv.of_person(home, stranger, 10)).items == ()
            assert [s.id for s in (await conv.of_person(elsewhere, stranger, 10)).items] == [far.id]

    run(scenario())


def test_a_speaker_who_joined_by_speaking_is_a_participant(db_url: str) -> None:
    home = household(db_url)
    mine = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            shared = await conv.start(home, "chat", [])
            await conv.add_turn(shared.id, NewTurn("person", "hello", mine))
            assert [s.id for s in (await conv.of_person(home, mine, 10)).items] == [shared.id]

    run(scenario())


def test_pages_follow_each_other_by_cursor_without_gaps_or_repeats(db_url: str) -> None:
    home = household(db_url)
    mine = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            made: list[int] = []
            for n in range(5):
                c = await conv.start(home, "chat", [mine])
                await conv.add_turn(c.id, NewTurn("person", f"t{n}", mine))
                made.append(c.id)
            first = await conv.of_person(home, mine, 2)
            assert first.next is not None
            second = await conv.of_person(home, mine, 2, first.next)
            assert second.next is not None
            third = await conv.of_person(home, mine, 2, second.next)
        assert third.next is None
        assert [s.id for p in (first, second, third) for s in p.items] == made[::-1]

    run(scenario())


def test_a_page_of_exactly_the_remaining_conversations_has_no_next(db_url: str) -> None:
    home = household(db_url)
    mine = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            for n in range(2):
                c = await conv.start(home, "chat", [mine])
                await conv.add_turn(c.id, NewTurn("person", f"t{n}", mine))
            assert (await conv.of_person(home, mine, 2)).next is None

    run(scenario())


@pytest.mark.parametrize("limit", [0, -1])
def test_a_page_of_less_than_one_is_refused_before_the_database(db_url: str, limit: int) -> None:
    async def scenario() -> None:
        async with service(db_url) as conv:
            with pytest.raises(ValueError):
                await conv.of_person(1, 1, limit)

    run(scenario())


def test_get_reports_where_a_conversation_started(db_url: str) -> None:
    home = household(db_url)
    mine = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            made = await conv.start(home, "chat", [mine], channel="discord", place=None)
            plain = await conv.start(home, "chat", [mine], channel="device", place="den")
            assert (await conv.get(made.id)) == made
            got = await conv.get(plain.id)
        assert got is not None and (got.channel, got.place) == ("device", "den")

    run(scenario())


def test_listing_logs_ids_and_counts_never_text(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    home = household(db_url)
    mine = person(db_url, home)
    logs.setup()

    async def scenario() -> None:
        async with service(db_url) as conv:
            c = await conv.start(home, "chat", [mine])
            await conv.add_turn(c.id, NewTurn("person", "SECRET WORDS", mine))
            await conv.of_person(home, mine, 5)

    run(scenario())
    out = capsys.readouterr().out
    assert "SECRET WORDS" not in out
    assert events(out, "conversation.listed")[0]["count"] == "1"
