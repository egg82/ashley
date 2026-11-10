"""What each change tool's spec says, and which connections are offered them (design: the tools table's `reads` and
`outside` columns; "Gmail's scope raised to `gmail.modify` (a reconnect, which the room asks for)"; "A tool needing a Google
scope the connection was not granted is not offered"; "deleting forever is not")."""

import pytest
from ashley.connections.kinds import OAuth
from ashley.google.kind import GOOGLE
from mail_changes_blind_support import (ADDRESS, BASE_SCOPES, CHANGES, DRAFT, LABEL, M1, READONLY, SEARCH, SEND, World,
                                        data, label_args, labels_now, send_args, stock, untouched)


def test_a_connection_with_the_change_scope_is_offered_all_three(stocked: World) -> None:
    assert set(CHANGES) <= stocked.turn().names()


@pytest.mark.parametrize("tool", CHANGES)
def test_a_change_reads_nothing_and_shows_no_stranger_words(stocked: World, tool: str) -> None:
    spec = stocked.turn().specs()[tool]
    assert spec.reads is False
    assert spec.outside is False


def test_nothing_offered_deletes_for_good(stocked: World) -> None:
    for spec in stocked.turn().specs().values():
        text = f"{spec.name} {spec.parameters}".lower()
        assert not any(w in text for w in ("delete", "expunge", "purge", "permanent")), spec.name


def test_the_google_kind_asks_for_the_change_scope() -> None:
    assert isinstance(GOOGLE.connect, OAuth)
    assert any(s.endswith("gmail.modify") for s in GOOGLE.connect.scopes)


def test_a_grant_of_the_read_scope_alone_is_missing_the_change_scope() -> None:
    assert isinstance(GOOGLE.connect, OAuth)
    assert [s for s in GOOGLE.connect.missing((*BASE_SCOPES, READONLY)) if s.endswith("gmail.modify")]
    assert not [s for s in GOOGLE.connect.missing((*BASE_SCOPES, "https://www.googleapis.com/auth/gmail.modify"))
                if s.endswith("gmail.modify")]


def test_a_connection_that_was_only_granted_to_read_changes_nothing(world: World) -> None:
    stock(world)
    world.connect(scopes=(*BASE_SCOPES, READONLY))
    before = labels_now(world)
    turn = world.turn()
    assert data(turn.call(SEARCH, mailbox=ADDRESS))  # control: reading is still offered
    calls = {DRAFT: send_args(), SEND: send_args(), LABEL: label_args(M1, add_labels=["School"])}
    for tool, args in calls.items():
        assert tool in turn.names()
        got = turn.send(tool, args)
        assert got.is_error and "needs_reconnect" in got.content, got.content
    untouched(world, before)
