"""Which Discord messages she answers, and as what `Inbound`: a pure function of the message, her id, the household
servers and the author's person (`decisions.md`, "Discord is a bot, its Gateway a singleton")."""

from collections.abc import Mapping
from dataclasses import replace
from typing import Literal

from ...conversations.model import Attachment
from ...people.model import Person
from ...text import has_nul
from .. import pasted
from ..model import DiscordServer, Inbound
from .message import Message

FORWARD_ONLY = "I forwarded this."
"""The text of a message that forwards with nothing typed."""

Ignored = Literal["bot", "unknown_server", "not_addressed", "empty", "unmapped", "nul"]
"""Why a message gets no reply: a bot wrote it, a server that is no device, a channel message that neither
mentions her nor replies to her, nothing left once her mention is removed and nothing forwarded, a NUL in the text, or a DM from an account
mapped to no one."""


def route(message: Message, me: int, servers: Mapping[int, DiscordServer], person: Person | None) -> Inbound | None:
    """The `Inbound` this message is, or None when she does not answer it.
    `person` is `People.person_for("discord", str(message.author_id))`, looked up by the caller.
    - Bot author: None.
    - DM (`guild_id` None): None when `person` is None; else household `person.household_id`, thread
      `discord:<channel_id>`, text `content`, kind `chat`, medium `text`, audience `owner`, speaker `person.id`,
      shared False, place None, remembers True, later True.
    - Guild message: None when `guild_id` is not in `servers`, or it neither mentions her nor replies to her.
      Else from the server's device: household, kind, medium, audience and remembers the device's; thread
      `discord:<channel_id>`, the channel the message is in; speaker `person.id` when `person` is in the device's
      household, else None; `taint` `stranger` unless `person` is in the device's household (the author is in no household, or in another), else None;
      shared False; place None; later True; `discord_channel` the channel's id (a DM has none).
    - The text of what the message forwards (`Message.forwarded`) is its `Inbound.attachment`, titled `Forwarded`, never
      part of `text` (`I forwarded this.` when nothing else was typed); `taint` `pasted` when `channels.pasted` says it
      is over the threshold and the message is not `stranger`'s already.
    - Source `discord:<message id>`, so a message handed in twice is one turn.
    - Text is `content` with her own mention tokens (`<@ME>`, `<@!ME>`) removed and stripped; None when nothing is
      left, or the text holds a NUL (`nul`, which no text column can store). `me` is her own Discord user id. `servers` is keyed by guild id."""
    got = decide(message, me, servers, person)
    return got if isinstance(got, Inbound) else None


def decide(message: Message, me: int, servers: Mapping[int, DiscordServer],
           person: Person | None) -> Inbound | Ignored:
    """`route`, saying why when she does not answer."""
    if message.author_is_bot:
        return "bot"
    thread = f"discord:{message.channel_id}"
    if message.guild_id is None:
        if person is None:
            return "unmapped"
        inbound = Inbound(household_id=person.household_id, thread=thread, text="", kind="chat", medium="text",
                          audience="owner", speaker_id=person.id, shared=False, place=None, channel="discord",
                          remembers=True, later=True, taint=None)
    else:
        server = servers.get(message.guild_id)
        if server is None:
            return "unknown_server"
        if not (message.mentions_me or message.replies_to_me):
            return "not_addressed"
        device = server.device
        member = person is not None and person.household_id == device.household_id
        speaker = person.id if person is not None and member else None
        inbound = Inbound(household_id=device.household_id, thread=thread, text="", kind=device.kind,
                          medium=device.medium, audience=device.audience, speaker_id=speaker, shared=False,
                          place=None, channel="discord", remembers=device.remembers, later=True,
                          taint=None if member else "stranger", discord_channel=message.channel_id)
    text = message.content.replace(f"<@{me}>", "").replace(f"<@!{me}>", "").strip()
    forwarded = message.forwarded.strip()
    if not (text or forwarded):
        return "empty"
    if has_nul(text) or has_nul(forwarded):
        return "nul"
    block = Attachment("Forwarded", forwarded) if forwarded else None
    return replace(inbound, text=text or FORWARD_ONLY, source=f"discord:{message.id}", attachment=block,
                   taint=inbound.taint or pasted.taint_of(block))
