"""A remark in a Discord channel she was not pinged in (`decisions.md`, "Whether she speaks unprompted is decided in
code"): one of her asides. A household member's message in a household server that neither mentions her nor replies
to her is rolled against the chance first, by its id alone, so most messages cost nothing; one that rolls in has its
facts gathered (`gathered`) and `Initiative` decides. An allowed one is claimed in `Remarks`, then her turn runs
unprompted with no tools, and its answer, when `Initiative` lets it out, goes through the outbox like any later reply.

Logs `discord.remark` (message, verdict) for each message that rolled in, `discord.remark_claimed_elsewhere` (message),
`discord.remarks_pruned` (count) and `discord.remarks_unavailable` (reason) when pruning cannot reach the store.
Never content."""

import logging
from collections.abc import Mapping
from datetime import datetime, timedelta

from ... import logs, services
from ...initiative.initiative import Initiative
from ...initiative.remark import DAY_S, RATES, Chance, fingerprint
from ...people.model import Person
from ...people.quiet import holds
from ...people.zone import zone_of
from ...senses.focus import Focus, FocusUnavailable
from ...text import has_nul
from ..model import DiscordServer, Inbound
from ..remarks import Remarks, RemarksUnavailable
from .message import Message

log = logging.getLogger("ashley.channels.discord")

NOTE = ("Nobody asked you anything here: this is a message between people in a channel of the household's Discord, "
        "and you read it in passing. This time, one remark from you is allowed: a single short line of your own, "
        "as a friend in the room might add to what was said. If nothing comes to you that is worth their attention, "
        "set `says` to none and nothing is sent. Never say a line you have said here before.")


async def offered(message: Message, servers: Mapping[int, DiscordServer], person: Person | None,
                  now: datetime) -> Inbound | None:
    """The turn for a remark on `message`, a guild message `route` found `not_addressed`, claimed in `Remarks`; None
    when there is none to make: the author is in no household of the server, the message has no text (or a NUL), the
    roll misses, `Initiative` does not allow it, or it was claimed already (or `Remarks` cannot be written)."""
    server = servers.get(message.guild_id) if message.guild_id is not None else None
    text = message.content.strip()
    if server is None or person is None or person.household_id != server.device.household_id:
        return None
    if not text or has_nul(text):
        return None
    seed = f"discord:{message.id}"
    initiative = services.get(Initiative)
    if not initiative.rolls(seed):
        return None
    chance = await gathered(seed, person, now)
    verdict = initiative.remark(chance)
    logs.info(log, "discord.remark", message=message.id, verdict=verdict)
    if verdict != "allowed" or not await _claim(message, person, seed, now):
        return None
    device = server.device
    return Inbound(household_id=device.household_id, thread=f"discord:{message.channel_id}", text=text,
                   kind=device.kind, medium=device.medium, audience=device.audience, speaker_id=person.id,
                   shared=False, place=None, channel="discord", remembers=device.remembers, later=True,
                   later_by="outbox", source=seed, unprompted=True, tools_only=(), note=NOTE, taint=None,
                   remark=chance)


async def gathered(seed: str, person: Person, now: datetime) -> Chance:
    """The facts at `now` for a remark to `person`: the hour in the household's zone, whether their own quiet hours hold, what `Remarks` holds of the last
    day and the repeat window, and when they last typed into a session (`Focus`). A fact that cannot be read is
    unknown, never a value."""
    household_id = person.household_id
    zone = await zone_of(household_id)
    try:
        before = await services.get(Remarks).before(household_id, person.id, now - timedelta(seconds=DAY_S),
                                                    now - timedelta(days=RATES.repeat_within_days))
        sent, said = before.sent, before.said
    except RemarksUnavailable:
        sent, said = None, ()
    try:
        typed = await services.get(Focus).typed_at(household_id, person.id)
        since_typed, known = (None if typed is None else (now - typed).total_seconds()), True
    except FocusUnavailable:
        since_typed, known = None, False
    return Chance(seed, None if zone is None else now.astimezone(zone).hour, sent, since_typed, known,
                  holds(person.quiet, now), said)


async def settle(household_id: int, source: str, sent: str | None) -> None:
    """Record how the remark claimed as `source` ended: `sent`, the line that went out, or None. Logged when it
    cannot be."""
    try:
        await services.get(Remarks).settle(household_id, source, None if sent is None else fingerprint(sent))
    except RemarksUnavailable:
        logs.warning(log, "discord.failed", reason="remark_settle_unavailable")


async def _claim(message: Message, person: Person, seed: str, now: datetime) -> bool:
    try:
        claimed = await services.get(Remarks).claim(person.household_id, person.id, seed, now)
    except RemarksUnavailable:
        logs.warning(log, "discord.failed", message=message.id, reason="remarks_unavailable")
        return False
    if not claimed:
        logs.info(log, "discord.remark_claimed_elsewhere", message=message.id)
    return claimed


async def prune(now: datetime) -> None:
    """Drop remarks older than the rates keep them (`Rates.keep_s`); logged `discord.remarks_pruned` (count)."""
    try:
        pruned = await services.get(Remarks).prune(now - timedelta(seconds=RATES.keep_s))
    except RemarksUnavailable:
        logs.warning(log, "discord.remarks_unavailable", reason="prune")
        return
    logs.info(log, "discord.remarks_pruned", count=pruned)
