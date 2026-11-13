"""A remark in a Discord channel she was not pinged in (`ashley.channels.discord.remark`, through the Discord bot): a
household member's message that neither mentions her nor replies to her starts an unprompted turn with no tools only
when `Initiative` allows it from the facts gathered (the day's count and lines from `Remarks`, the household's hour,
`Focus`); the remark is claimed before the turn and settled with the fingerprint of what went out, and the bot posts
none of it itself (the outbox does). Clock and seed are fixed: NOW, and a chance of 1 or 0."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta

from ashley import services
from ashley.channels.discord.bot import Bot
from ashley.channels.discord.message import Message
from ashley.channels.model import Inbound, Outbound
from ashley.channels.remarks import Before, Remarks, RemarksUnavailable
from ashley.initiative.initiative import Initiative, Scored
from ashley.initiative.remark import Rates, fingerprint
from ashley.initiative.weights import parse
from ashley.inference.reply import Says
from ashley.people.model import Household, Person
from ashley.people.people import People
from ashley.senses.focus import Focus, FocusUnavailable
from discord_support import ALANA, ALANA_ID, GUEST_ID, NOW, FakePeople, Rig, message, quiet, rig, running, unwire
from initiative_support import weights

ALWAYS = Rates(chance=1.0, per_day=2, typing_within_s=900.0, repeat_within_days=30)
LINE = "Bold of you to call that a salad."
HEARD = message(mentions_me=False, content="lunch is a salad today")


class HouseholdPeople(FakePeople):
    """FakePeople whose every household is in `zone`."""

    def __init__(self, zone: str) -> None:
        super().__init__({("discord", str(ALANA_ID)): ALANA})
        self.zone = zone

    async def household(self, household_id: int) -> Household | None:
        return Household(household_id, "home", self.zone, "", ())


class MemoryRemarks(Remarks):
    """`rows`: source -> [household, person, claimed_at, settled, line]."""

    def __init__(self) -> None:
        self.rows: dict[str, list[object]] = {}
        self.down = False

    async def before(self, household_id: int, person_id: int, count_since: datetime, said_since: datetime) -> Before:
        if self.down:
            raise RemarksUnavailable("down")
        mine = [r for r in self.rows.values() if r[0] == household_id]
        sent = sum(1 for r in mine if r[1] == person_id and _at(r) >= count_since and (not r[3] or r[4] is not None))
        return Before(sent, tuple(str(r[4]) for r in mine if r[4] is not None and _at(r) >= said_since))

    async def claim(self, household_id: int, person_id: int, source: str, at: datetime) -> bool:
        if self.down:
            raise RemarksUnavailable("down")
        if source in self.rows:
            return False
        self.rows[source] = [household_id, person_id, at, False, None]
        return True

    async def settle(self, household_id: int, source: str, line: str | None) -> None:
        row = self.rows.get(source)
        if row is not None and not row[3]:
            row[3], row[4] = True, line

    async def prune(self, before: datetime) -> int:
        return 0


def _at(row: list[object]) -> datetime:
    at = row[2]
    assert isinstance(at, datetime)
    return at


class FixedFocus(Focus):
    def __init__(self, typed: datetime | None = None, down: bool = False) -> None:
        self.typed, self.down = typed, down

    async def typed_at(self, household_id: int, person_id: int) -> datetime | None:
        if self.down:
            raise FocusUnavailable("down")
        return self.typed


def _wired(zone: str = "UTC", rates: Rates = ALWAYS, focus: Focus | None = None,
           remarks: MemoryRemarks | None = None, says: Says = "reply") -> tuple[Rig, MemoryRemarks]:
    """The Discord rig with a bot whose turns answer `LINE` with `says`, and the remark's seams registered."""
    r = rig()
    services.register(People, HouseholdPeople(zone))
    made = remarks or MemoryRemarks()
    services.register(Remarks, made)
    services.register(Focus, focus or FixedFocus())
    services.register(Initiative, Scored(parse(weights(night={"weight": 0.0, "from_hour": 22, "to_hour": 7})), rates))

    async def respond(inbound: Inbound) -> Outbound:
        r.replies.inbounds.append(inbound)
        return Outbound(77, "text", LINE, says=says)
    return replace(r, bot=Bot(r.connect, r.seen, r.config, respond=respond, now=lambda: NOW)), made


def _unwire() -> None:
    unwire()
    for interface in (Remarks, Focus, Initiative):
        services.unregister(interface)


def _hand(r: Rig, *messages: Message) -> None:
    async def scenario() -> None:
        async with running(r):
            for m in messages:
                r.discord.incoming.put_nowait(m)
            await quiet()
    asyncio.run(scenario())


def test_an_allowed_remark_runs_an_unprompted_turn_with_no_tools_and_is_settled_with_its_line() -> None:
    r, remarks = _wired()
    try:
        _hand(r, HEARD)
        assert len(r.replies.inbounds) == 1
        turn = r.replies.inbounds[0]
        assert turn.unprompted and turn.tools_only == () and turn.remark is not None and turn.later_by == "outbox"
        assert turn.thread == f"discord:{HEARD.channel_id}" and turn.speaker_id == ALANA.id and turn.taint is None
        assert turn.source == f"discord:{HEARD.id}" and turn.text == HEARD.content
        assert turn.remark.sent == 0 and turn.remark.hour == 12 and turn.remark.typing_known
        assert r.discord.sends == [], "what goes out is the outbox's to post"
        assert remarks.rows[f"discord:{HEARD.id}"][3:] == [True, fingerprint(LINE)]
    finally:
        _unwire()


def test_a_remark_she_kept_quiet_is_settled_with_no_line_and_not_counted() -> None:
    r, remarks = _wired(says="none")
    try:
        _hand(r, HEARD)
        assert remarks.rows[f"discord:{HEARD.id}"][3:] == [True, None]
    finally:
        _unwire()


def test_the_cap_reached_starts_no_turn() -> None:
    held = MemoryRemarks()
    held.rows = {f"discord:{i}": [1, ALANA.id, NOW - timedelta(hours=i), True, f"line{i}"] for i in (1, 2)}
    r, remarks = _wired(remarks=held)
    try:
        _hand(r, HEARD)
        assert r.replies.inbounds == [] and f"discord:{HEARD.id}" not in remarks.rows
    finally:
        _unwire()


def test_remarks_older_than_a_day_or_kept_quiet_do_not_count_toward_the_cap() -> None:
    held = MemoryRemarks()
    held.rows = {"discord:1": [1, ALANA.id, NOW - timedelta(hours=25), True, "a"],
                 "discord:2": [1, ALANA.id, NOW - timedelta(hours=1), True, None],
                 "discord:3": [1, ALANA.id, NOW - timedelta(hours=1), True, "c"]}
    r, _ = _wired(remarks=held)
    try:
        _hand(r, HEARD)
        assert len(r.replies.inbounds) == 1
        chance = r.replies.inbounds[0].remark
        assert chance is not None and chance.sent == 1 and set(chance.said) == {"a", "c"}
    finally:
        _unwire()


def test_a_roll_that_misses_starts_no_turn_and_claims_nothing() -> None:
    r, remarks = _wired(rates=replace(ALWAYS, chance=0.0))
    try:
        _hand(r, HEARD)
        assert r.replies.inbounds == [] and remarks.rows == {}
    finally:
        _unwire()


def test_typing_into_a_session_just_now_is_focus_and_starts_no_turn() -> None:
    r, _ = _wired(focus=FixedFocus(NOW - timedelta(seconds=60)))
    try:
        _hand(r, HEARD)
        assert r.replies.inbounds == []
    finally:
        _unwire()


def test_focus_that_cannot_be_read_or_remarks_that_cannot_be_read_start_no_turn() -> None:
    for focus, down in ((FixedFocus(down=True), False), (FixedFocus(), True)):
        held = MemoryRemarks()
        held.down = down
        r, _ = _wired(focus=focus, remarks=held)
        try:
            _hand(r, HEARD)
            assert r.replies.inbounds == []
        finally:
            _unwire()


def test_the_households_night_starts_no_turn() -> None:
    r, _ = _wired(zone="Etc/GMT-11")   # NOW is 23:00 there
    try:
        _hand(r, HEARD)
        assert r.replies.inbounds == []
    finally:
        _unwire()


def test_a_stranger_a_bot_or_a_message_with_no_text_gets_no_remark() -> None:
    r, _ = _wired()
    try:
        _hand(r, replace(HEARD, author_id=GUEST_ID), replace(HEARD, id=HEARD.id + 1, author_is_bot=True),
              replace(HEARD, id=HEARD.id + 2, content="   "))
        assert r.replies.inbounds == []
    finally:
        _unwire()


def test_a_member_of_another_household_gets_no_remark_in_this_households_server() -> None:
    r, _ = _wired()
    people = services.get(People)
    assert isinstance(people, HouseholdPeople)
    people.accounts_by_id[("discord", str(GUEST_ID))] = Person(9, 2, "Ines")
    try:
        _hand(r, replace(HEARD, author_id=GUEST_ID), replace(HEARD, id=HEARD.id + 1))
        assert [i.speaker_id for i in r.replies.inbounds] == [ALANA.id], "only the household's own member"
    finally:
        _unwire()


def test_a_message_handed_in_twice_gets_one_remark() -> None:
    r, remarks = _wired()
    try:
        _hand(r, HEARD, HEARD)
        assert len(r.replies.inbounds) == 1 and len(remarks.rows) == 1
    finally:
        _unwire()


def test_a_message_that_pings_her_is_answered_as_before_not_as_a_remark() -> None:
    r, remarks = _wired()
    try:
        _hand(r, message())
        assert len(r.replies.inbounds) == 1 and r.replies.inbounds[0].remark is None and remarks.rows == {}
    finally:
        _unwire()
