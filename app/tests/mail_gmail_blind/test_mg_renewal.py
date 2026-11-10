"""The tools over part 1's renewal (design: "A pod whose access token is within `refresh_margin_s` of expiry refreshes",
"A refused refresh marks the connection, never deletes it ... her tools over it answer `needs_reconnect` rather than
empty results"). The token endpoint is the fake's, at its HTTP boundary."""

import asyncio

import pytest
from ashley import services
from ashley.connections.model import Grant
from ashley.connections.oauth_connections import OAuthConnections
from mail_gmail_blind_support import (ADDRESS, BASE_SCOPES, GMAIL_SCOPE, LABELS, READ, SEARCH, SEED_ACCESS,
                                      SEED_REFRESH, World, data, day, failed, headers_of, message)


def stocked(world: World, expires_in_s: int = 86_400) -> int:
    world.fake.add(message("m1", day(3, 4), "Menu", text="soup", labels=("INBOX", "UNREAD")))
    cid = world.connect(expires_in_s=expires_in_s)
    if expires_in_s <= 1:
        world.fake.expired.add(SEED_ACCESS)
    return cid


def test_a_fresh_token_is_used_as_it_is_with_no_refresh(world: World) -> None:
    stocked(world)
    assert headers_of(data(world.turn().call(SEARCH, mailbox=ADDRESS)))
    assert world.fake.calls("token") == []
    assert set(world.fake.bearers()) == {SEED_ACCESS}


def test_an_expired_token_is_renewed_and_every_gmail_call_carries_the_new_one(world: World) -> None:
    stocked(world, expires_in_s=1)
    assert headers_of(data(world.turn().call(SEARCH, mailbox=ADDRESS)))
    [refresh] = world.fake.calls("token")
    assert refresh.form["grant_type"] == "refresh_token" and refresh.form["refresh_token"] == SEED_REFRESH
    assert world.fake.bearers() and set(world.fake.bearers()) == set(world.fake.issued)


def test_the_renewed_token_is_kept_so_a_later_turn_does_not_refresh_again(world: World) -> None:
    stocked(world, expires_in_s=1)
    data(world.turn().call(SEARCH, mailbox=ADDRESS))
    data(world.turn().call(LABELS, mailbox=ADDRESS))
    data(world.turn().call(READ, mailbox=ADDRESS, id="m1"))
    assert len(world.fake.calls("token")) == 1


@pytest.mark.parametrize(("name", "args"), [(LABELS, {"mailbox": ADDRESS}), (SEARCH, {"mailbox": ADDRESS}),
                                            (READ, {"mailbox": ADDRESS, "id": "m1"})])
def test_every_tool_renews_an_expired_token(world: World, name: str, args: dict[str, object]) -> None:
    stocked(world, expires_in_s=1)
    assert not world.turn().call(name, **args).is_error
    assert len(world.fake.calls("token")) == 1 and SEED_ACCESS not in world.fake.bearers()


def test_two_turns_at_once_with_an_expired_token_both_answer(world: World) -> None:
    stocked(world, expires_in_s=1)
    first, second = world.turn(), world.turn()

    async def both() -> list[bool]:
        got = await asyncio.gather(first.acall(SEARCH, mailbox=ADDRESS), second.acall(SEARCH, mailbox=ADDRESS))
        return [r.is_error for r in got]

    assert world.run(both) == [False, False]


@pytest.mark.parametrize(("name", "args"), [(LABELS, {"mailbox": ADDRESS}), (SEARCH, {"mailbox": ADDRESS}),
                                            (READ, {"mailbox": ADDRESS, "id": "m1"})])
def test_a_refused_renewal_answers_needs_reconnect_marks_the_row_and_reaches_no_gmail(
        world: World, name: str, args: dict[str, object]) -> None:
    cid = stocked(world, expires_in_s=1)
    world.fake.refuse_refresh = True
    failed(world.turn().call(name, **args), "needs_reconnect")
    assert world.fake.calls("gmail") == []
    assert world.needs(cid) == "reconnect"


def test_after_a_refusal_the_next_call_says_so_without_asking_google_again(world: World) -> None:
    stocked(world, expires_in_s=1)
    world.fake.refuse_refresh = True
    world.turn().call(SEARCH, mailbox=ADDRESS)
    asked = len(world.fake.calls("token"))
    failed(world.turn().call(READ, mailbox=ADDRESS, id="m1"), "needs_reconnect")
    assert len(world.fake.calls("token")) == asked and world.fake.calls("gmail") == []


def test_a_connection_marked_needs_reconnect_answers_it_not_an_empty_list(world: World) -> None:
    world.mark_reconnect(stocked(world))
    got = world.turn().call(SEARCH, mailbox=ADDRESS)
    failed(got, "needs_reconnect")
    assert '"messages": []' not in got.content and "cut" not in got.content
    assert world.fake.calls("gmail") == [] and world.fake.calls("token") == []


def test_a_token_endpoint_that_is_down_is_unreachable_and_does_not_mark_the_row(world: World) -> None:
    cid = stocked(world, expires_in_s=1)
    world.fake.refresh_down = True
    failed(world.turn().call(SEARCH, mailbox=ADDRESS), "unreachable")
    assert world.needs(cid) is None and world.fake.calls("gmail") == []


def test_a_token_endpoint_that_errors_is_unreachable_and_does_not_mark_the_row(world: World) -> None:
    cid = stocked(world, expires_in_s=1)
    world.fake.refresh_status = 503
    failed(world.turn().call(SEARCH, mailbox=ADDRESS), "unreachable")
    assert world.needs(cid) is None


def test_a_reconnected_connection_answers_again(world: World) -> None:
    cid = stocked(world)
    world.mark_reconnect(cid)
    failed(world.turn().call(SEARCH, mailbox=ADDRESS), "needs_reconnect")
    world.fake.accept("at-new-0009-ACCESSTOKEN", "rt-new-0009-REFRESHTOKEN")

    async def reconnect() -> None:
        grant = Grant("at-new-0009-ACCESSTOKEN", "rt-new-0009-REFRESHTOKEN", 86_400, (*BASE_SCOPES, GMAIL_SCOPE))
        assert await services.get(OAuthConnections).replace_oauth(
            cid, world.hid, world.alana, "https://www.googleapis.com", grant) is not None

    world.run(reconnect)
    assert headers_of(data(world.turn().call(SEARCH, mailbox=ADDRESS)))
