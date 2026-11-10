"""Directed tests added by the reconciler for the mutants the blind suite alone let live (not blind: they were written
against the builder's code, from the decisions' sort part): what a label call with a folder or a read state does, and the
kind's availability."""

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from ashley import services
from ashley.connections.resources import ConnectionResources, Usable, Use
from ashley.connections.model import Connection, Resource, ResourceKind
from ashley.connections.connections import ConnectionsUnavailable
from ashley.mail.mailbox import Mailbox, NullMailbox
from ashley.watches.mail_inbox import MailInbox
from ashley.watches.model import Later
from mail_sort_blind_support import ADDRESS, Store, run, scenario as store_scenario
from mail_sort_blind_turn_support import (EPOCH, HOUSEHOLD, M1, PERSON, SCOPES, RecordingMailbox, Rig, TwoBoxes, held,
                                          sort_watch, with_rig, woken)

SCHOOL = frozenset({"School"})


def scenario(body: Callable[[Rig], Awaitable[None]]) -> None:
    run(with_rig(body))


@pytest.mark.parametrize("change", [{"unread": False}, {"unread": True}, {"remove": ["Work"]}])
def test_a_label_with_a_read_state_or_a_removal_runs(change: dict[str, object]) -> None:
    async def body(rig: Rig) -> None:
        turn = rig.turn(woken(sort_watch()), "watch")
        assert not held(await turn.label(M1, add=["School"], **change))
        assert len(turn.ran()) == 1

    scenario(body)


@pytest.mark.parametrize("folder", ["archive", "trash", "spam"])
def test_a_label_with_a_folder_is_held(folder: str) -> None:
    async def body(rig: Rig) -> None:
        turn = rig.turn(woken(sort_watch()), "watch")
        assert held(await turn.label(M1, add=["School"], folder=folder))
        assert turn.ran() == []

    scenario(body)


def test_a_label_call_that_names_no_mailbox_does_not_reach_the_port() -> None:
    async def body(rig: Rig) -> None:
        turn = rig.turn(woken(sort_watch()), "watch")
        await turn.call("mail_label", messages=[M1], add=["School"])
        assert turn.ran() == []

    scenario(body)


def test_a_send_with_the_label_arguments_is_held() -> None:
    async def body(rig: Rig) -> None:
        turn = rig.turn(woken(sort_watch()), "watch")
        assert held(await turn.call("mail_send", mailbox=ADDRESS, messages=[M1], add=["School"]))
        assert rig.mailbox.written == [] and turn.ran() == []

    scenario(body)


class Reconnect(TwoBoxes):
    async def usable(self, use: Use, changing: bool, kind: ResourceKind = "mailbox") -> tuple[Usable, ...]:
        return tuple(Usable(Connection(1, use.household_id, "google", "", PERSON, EPOCH, EPOCH, PERSON, "", "reconnect",
                                       SCOPES), Resource(ADDRESS, "mailbox", ADDRESS, True)) for _ in (0,))


class Down(TwoBoxes):
    async def usable(self, use: Use, changing: bool, kind: ResourceKind = "mailbox") -> tuple[Usable, ...]:
        raise ConnectionsUnavailable("down")


async def offered(resources: ConnectionResources, mailbox: Mailbox) -> bool:
    services.register(ConnectionResources, resources)
    services.register(Mailbox, mailbox)
    return await MailInbox().available(HOUSEHOLD, PERSON)


def test_the_kind_is_not_offered_for_a_connection_that_needs_the_person() -> None:
    assert asyncio.run(offered(Reconnect(), RecordingMailbox())) is False


def test_the_kind_is_not_offered_when_the_mailbox_cannot_read_the_connection() -> None:
    assert asyncio.run(offered(TwoBoxes(), NullMailbox())) is False


def test_the_kind_is_not_offered_while_connections_cannot_be_read() -> None:
    assert asyncio.run(offered(Down(), RecordingMailbox())) is False


def test_a_later_read_does_not_move_a_standing_watchs_end(db_url: str) -> None:
    async def body(s: Store) -> None:
        a = await s.armed(hours=6.0, standing=True)
        s.age(a, 5.0)
        await s.tick(Later())
        assert abs(s.hours_left(a) - 1.0) <= 0.1, s.hours_left(a)

    store_scenario(db_url, body)
