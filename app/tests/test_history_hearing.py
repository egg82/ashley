"""A person's history against a real database: turns from every channel they took part in reach it, each conversation
carries the channel and place it started on, and a turn said privately to someone else in a conversation they share
(a reply sent to that person's phone) never reaches them."""

import pytest
from ashley import logs, services
from ashley.api.history import history, past
from ashley.api.history_models import PastConversation, PastHistory
from ashley.conversations.conversations import Conversations
from ashley.conversations.model import Channel, NewTurn
from ashley.people.model import Household, Person
from ashley.people.people import People
from ashley.signin.model import SignedIn
from respond_support import FakePeople
from contract.conversations_support import (db_url as db_url, events, household, migrated_template as migrated_template,
                                            person, run, service)


class Home(FakePeople):
    def __init__(self, home: Household) -> None:
        self.home = home

    async def household(self, household_id: int) -> Household | None:
        return self.home if household_id == self.home.id else None


def _signed(who: Person) -> SignedIn:
    return SignedIn(1, who)


async def _said(conv: Conversations, home: int, channel: Channel, place: str | None, people: list[int],
                *turns: NewTurn) -> int:
    started = await conv.start(home, "chat", people, True, channel, place)
    for turn in turns:
        await conv.add_turn(started.id, turn)
    return started.id


def test_every_channel_reaches_the_web_history_with_where_it_was_said(db_url: str) -> None:
    home = household(db_url)
    alana = Person(person(db_url, home, "Alana"), home, "Alana")

    async def scenario() -> None:
        async with service(db_url) as conv:
            services.register(Conversations, conv)
            try:
                where: list[tuple[Channel, str | None]] = [("voice", "kitchen"), ("discord", None), ("device", "hallway"),
                                                           ("web", None)]
                for channel, place in where:
                    await _said(conv, home, channel, place, [alana.id],
                                NewTurn("person", f"said on {channel}", alana.id, "shared"))
                page = await history(_signed(alana))
                assert isinstance(page, PastHistory)
                assert {(c.channel, c.place) for c in page.conversations} == set(where)
            finally:
                services.unregister(Conversations)

    run(scenario())


def test_a_turn_private_to_another_participant_is_not_in_what_they_read_back(db_url: str,
                                                                              capsys: pytest.CaptureFixture[str]) -> None:
    home = household(db_url)
    alana = Person(person(db_url, home, "Alana"), home, "Alana")
    sam = Person(person(db_url, home, "Sam"), home, "Sam")
    logs.setup()

    async def scenario() -> None:
        async with service(db_url) as conv:
            services.register(Conversations, conv)
            services.register(People, Home(Household(home, "home", "America/Denver", "", (alana, sam))))
            try:
                said = await _said(
                    conv, home, "device", "hallway", [alana.id, sam.id],
                    NewTurn("person", "what is on today", alana.id, "shared"),
                    NewTurn("ashley", "the dentist at noon", None, "private", alana.id),
                    NewTurn("ashley", "and dinner at six", None, "shared"),
                    NewTurn("person", "thanks", sam.id, "shared"))
                texts = {}
                for who in (alana, sam):
                    got = await past(_signed(who), said)
                    assert isinstance(got, PastConversation)
                    texts[who.name] = [t.text for t in got.lines]
                assert texts["Alana"] == ["what is on today", "the dentist at noon", "and dinner at six", "thanks"]
                assert texts["Sam"] == ["what is on today", "and dinner at six", "thanks"]
            finally:
                services.unregister(Conversations)
                services.unregister(People)

    run(scenario())
    out = capsys.readouterr().out
    assert "dentist" not in out
    assert [(e["turns"], e["withheld"]) for e in events(out, "chat.past")] == [("4", "0"), ("3", "1")]
