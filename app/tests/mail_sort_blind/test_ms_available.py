"""The `mail_inbox` kind is offered to a person who has a mailbox they may use, and to nobody else (design: "She arms one
when asked"; part 7 left `available` false until the sort)."""

import asyncio

from ashley import services
from ashley.connections.resources import ConnectionResources, Usable, Use
from ashley.connections.model import ResourceKind
from ashley.mail.mailbox import Mailbox
from ashley.watches.mail_inbox import MailInbox
from mail_sort_blind_turn_support import HOUSEHOLD, PERSON, RecordingMailbox, TwoBoxes


class NoBoxes(TwoBoxes):
    async def usable(self, use: Use, changing: bool, kind: ResourceKind = "mailbox") -> tuple[Usable, ...]:
        return ()


def test_the_kind_is_available_to_a_person_with_a_usable_mailbox() -> None:
    async def go() -> None:
        services.register(ConnectionResources, TwoBoxes())
        services.register(Mailbox, RecordingMailbox())
        assert await MailInbox().available(HOUSEHOLD, PERSON) is True

    asyncio.run(go())


def test_the_kind_is_not_available_to_a_person_with_none() -> None:
    async def go() -> None:
        services.register(ConnectionResources, NoBoxes())
        services.register(Mailbox, RecordingMailbox())
        assert await MailInbox().available(HOUSEHOLD, PERSON) is False

    asyncio.run(go())
