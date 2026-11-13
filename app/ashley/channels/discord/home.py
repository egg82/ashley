"""Her tending of her home channel on each household's Discord server (`DiscordServer.home_channel_id`), run inside the
Discord singleton's session: time is cut into slots (`initiative.tend`), and once per server and slot `Initiative`
rolls, then decides from the slot's facts, measured from the channel's messages sent before the slot began, so any
process deciding a slot decides the same. An allowed slot is her own turn on the channel's thread, the household's,
offering only the tools that change that channel (`Inbound.home_channel`, `tools.discord_home_tools`). Its source is
the slot's (`discord-home:<device id>:<slot>`), so a slot handed in again after a failover is one turn, and a turn a
stopped pod left is finished by the `inflight` singleton. What she writes goes out through the outbox when she sets
`says` to reply.

Logs `discord.tend` (device, slot, verdict) for each slot that rolled in, `discord.tended` (channel, conversation,
says, follows) when its turn returns, `discord.failed` (reason) when it cannot run. Never content."""

import logging
from collections.abc import Awaitable, Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from ... import logs, services
from ...initiative.initiative import Initiative
from ...initiative.tend import RATES, Rates, Tending
from ...people.zone import zone_of
from ...tools.discord_home_tools import NAMES
from ...tools.discord_posts import ChannelPosts, PostsFailed
from ..devices import Devices, DevicesUnavailable
from ..model import DiscordServer, Inbound, Outbound
from ..respond import RespondRefused, RespondUnavailable
from .message import sent_at

log = logging.getLogger("ashley.channels.discord")

TEXT = "Her own time in her channel"
NOTE = ("Nobody asked you anything: this is your own time in your channel on the household's Discord server, a place "
        "of your own to keep as you like. This time, tending it is allowed: look at what you have posted and pinned "
        "there, and change its topic or pins if you want to. If you have something worth posting for the household, "
        "write it as your reply and set `says` to reply; otherwise set `says` to none and nothing is posted. Never "
        "post a line you have posted there before.")

Respond = Callable[[Inbound], Awaitable[Outbound]]


async def tend(me: int, start: Callable[[Coroutine[Any, Any, None]], None], respond: Respond,
               now: Callable[[], datetime], sleep: Callable[[float], Awaitable[None]], rates: Rates = RATES) -> None:
    """After every `check_every_s` until cancelled, decide each server's current slot once (`check`), and hand an allowed
    one's turn to `start`. `me` is her Discord user id."""
    done: set[str] = set()
    while True:
        await sleep(rates.check_every_s)
        await check(me, start, respond, now(), done, rates)


async def check(me: int, start: Callable[[Coroutine[Any, Any, None]], None], respond: Respond, at: datetime,
                done: set[str], rates: Rates = RATES) -> None:
    """Decide the slot holding `at` for every household server whose seed is not in `done`, adding it there; `done`
    keeps only the current slot's seeds. When the servers cannot be read, nothing is decided and it is logged."""
    try:
        servers = await services.get(Devices).discord_servers()
    except DevicesUnavailable:
        logs.warning(log, "discord.failed", reason="tend_devices_unavailable")
        return
    slot = int(at.timestamp() // rates.slot_s)
    begun = datetime.fromtimestamp(slot * rates.slot_s, UTC)
    for seed in [s for s in done if not s.endswith(f":{slot}")]:
        done.discard(seed)
    initiative = services.get(Initiative)
    for server in servers:
        seed = f"{server.device.id}:{slot}"
        if seed in done:
            continue
        done.add(seed)
        if not initiative.tend_rolls(seed):
            continue
        verdict = initiative.tend(await gathered(server, seed, me, begun, rates))
        logs.info(log, "discord.tend", device=server.device.id, slot=slot, verdict=verdict)
        if verdict == "allowed":
            start(_turn(respond, inbound(server, seed)))


async def gathered(server: DiscordServer, seed: str, me: int, begun: datetime, rates: Rates = RATES) -> Tending:
    """The facts at `begun` from the home channel's latest `read_count` messages sent before it. A fact that cannot be
    read is unknown, never a value."""
    zone = await zone_of(server.device.household_id)
    hour = None if zone is None else begun.astimezone(zone).hour
    try:
        posts = await services.get(ChannelPosts).recent(server.home_channel_id, rates.read_count)
    except PostsFailed:
        return Tending(seed, hour, False, None, 0)
    before = [p for p in posts if sent_at(p.id) < begun]
    mine = [i for i, p in enumerate(before) if p.author_id == me]
    after = before[mine[-1] + 1:] if mine else before
    since = None if not mine else (begun - sent_at(before[mine[-1]].id)).total_seconds()
    return Tending(seed, hour, True, since, sum(1 for p in after if not p.bot))


def inbound(server: DiscordServer, seed: str) -> Inbound:
    """Her turn of tending `server`'s home channel in the slot `seed`."""
    device = server.device
    return Inbound(household_id=device.household_id, thread=f"discord:{server.home_channel_id}", text=TEXT,
                   kind=device.kind, medium=device.medium, audience=device.audience, speaker_id=None, shared=False,
                   place=None, channel="discord", remembers=device.remembers, later=True, later_by="outbox",
                   source=f"discord-home:{seed}", unprompted=True, author="household", tools_only=NAMES, note=NOTE,
                   taint=None, home_channel=server.home_channel_id)


async def _turn(respond: Respond, inbound: Inbound) -> None:
    try:
        out = await respond(inbound)
    except (RespondUnavailable, RespondRefused):
        logs.warning(log, "discord.failed", reason="tend_turn", channel=inbound.home_channel)
        return
    logs.info(log, "discord.tended", channel=inbound.home_channel, conversation=out.conversation_id, says=out.says,
              follows=out.follows)
