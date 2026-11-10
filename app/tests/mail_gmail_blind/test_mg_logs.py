"""What mail logs (design: "`mail.call` (connection id, mailbox's resource id, call, status, count, duration_ms) ... None
carries an address, a subject, a body, a query, a token, a password or the vault")."""

import logging
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from mail_gmail_blind_support import ADDRESS, BOXES, LABELS, READ, SEARCH, SEED_ACCESS, SEED_REFRESH, World, day, message


def text_of(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(f"{r.name} {r.getMessage()} {getattr(r, 'fields', {})!r} {r.exc_text or ''}" for r in caplog.records)


def events(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, object]]:
    return [dict(getattr(r, "fields", {})) for r in caplog.records if r.getMessage() == event]


def stocked(world: World) -> None:
    world.fake.add(message("m1", day(3, 4), "Secret plans for Friday", sender="Zelda Quux <zelda@hyrule.test>",
                           snippet="Meet me at the old mill", text="The vault code is swordfish-9917",
                           labels=("INBOX", "Label_12")))
    world.connect(expires_in_s=1)
    world.fake.expired.add(SEED_ACCESS)


def use_all(world: World) -> None:
    turn = world.turn()
    turn.call(BOXES)
    turn.call(LABELS, mailbox=ADDRESS)
    turn.call(SEARCH, mailbox=ADDRESS, subject="Secret plans", text="swordfish", **{"from": "zelda@hyrule.test"})
    turn.call(READ, mailbox=ADDRESS, id="m1")


def test_each_tool_call_logs_one_mail_call_with_its_outcome_and_duration(world: World, caplog: pytest.LogCaptureFixture) -> None:
    stocked(world)
    caplog.set_level(logging.DEBUG)
    use_all(world)
    calls = events(caplog, "mail.call")
    assert len(calls) >= 3
    for fields in calls:
        assert {"call", "status", "count", "duration_ms"} <= set(fields), fields
    assert {str(f["status"]) for f in calls} == {"ok"}


def test_a_failed_call_logs_its_reason_as_its_status(world: World, caplog: pytest.LogCaptureFixture) -> None:
    stocked(world)
    world.fake.refuse_refresh = True
    caplog.set_level(logging.DEBUG)
    world.turn().call(SEARCH, mailbox=ADDRESS)
    assert [str(f["status"]) for f in events(caplog, "mail.call")] == ["needs_reconnect"]


def test_no_log_line_carries_an_address_subject_body_snippet_label_or_query(world: World, caplog: pytest.LogCaptureFixture) -> None:
    stocked(world)
    caplog.set_level(logging.DEBUG)
    use_all(world)
    logged = text_of(caplog)
    assert "mail.call" in logged
    leaked = [s for s in (*world.fake.private_text(), "swordfish", "Secret plans", "zelda", "hyrule", "old mill",
                          "alana@") if s.lower() in logged.lower()]
    assert not leaked, leaked


def test_no_log_line_carries_a_token_or_the_client_secret(world: World, caplog: pytest.LogCaptureFixture) -> None:
    stocked(world)
    caplog.set_level(logging.DEBUG)
    use_all(world)
    logged = text_of(caplog)
    assert world.fake.issued, "the expired token was not renewed, so the renewal path was not exercised"
    leaked = [s for s in (*world.fake.secret_values(), SEED_ACCESS, SEED_REFRESH) if s in logged]
    assert not leaked, leaked


def test_failures_log_no_content_either(world: World, caplog: pytest.LogCaptureFixture) -> None:
    stocked(world)
    caplog.set_level(logging.DEBUG)
    turn = world.turn()
    world.fake.gmail_status = 503
    turn.call(SEARCH, mailbox=ADDRESS, text="swordfish")
    world.fake.gmail_status, world.fake.gmail_down = None, True
    turn.call(READ, mailbox=ADDRESS, id="m1")
    assert not [s for s in ("swordfish", ADDRESS, "m1@") if s in text_of(caplog)] and events(caplog, "mail.call")


def test_a_search_that_cannot_reach_gmail_logs_no_query_words(world: World, caplog: pytest.LogCaptureFixture,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    stocked(world)
    served: Callable[..., Any] = getattr(world.fake, "_gmail")
    caplog.set_level(logging.DEBUG)

    def only_the_list_is_down(request: httpx2.Request, path: str, query: dict[str, list[str]], bearer: str) -> Any:
        if path == "/messages":
            raise httpx2.ConnectError("gmail is down")
        return served(request, path, query, bearer)

    monkeypatch.setattr(world.fake, "_gmail", only_the_list_is_down)
    assert world.turn().call(SEARCH, mailbox=ADDRESS, text="swordfish", **{"from": "zelda@hyrule.test"}).is_error
    assert not [s for s in ("swordfish", "zelda@hyrule.test") if s in text_of(caplog)] and events(caplog, "mail.call")
