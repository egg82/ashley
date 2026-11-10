"""The body limit agrees with `outside.json`, and arguments that are malformed or would smuggle a header change nothing
(design: "`max_body_chars` for a draft must fit `max_argument_chars` in `app/ashley/tools/outside.json`, and a test holds
the two together, since a held call past that limit is refused")."""

import json
from pathlib import Path

import pytest
from ashley.mail import config
from ashley.tools import outside_config
from mail_changes_blind_support import (ADDRESS, DRAFT, READ, SEND, World, failed, labels_now, send_args, untouched)

CONFIG = outside_config.load()
LETTERS = "abcdefghij"


def body_most() -> int:
    raw = json.loads(Path(config.FILE).read_text())
    assert isinstance(raw["max_body_chars"], int) and raw["max_body_chars"] > 0
    return int(raw["max_body_chars"])


def letters(n: int) -> str:
    return (LETTERS * (n // len(LETTERS) + 1))[:n]


def test_the_body_limit_is_below_the_most_characters_a_held_call_may_take() -> None:
    assert body_most() < CONFIG.max_argument_chars


def test_a_send_of_exactly_the_limit_is_held_after_a_read_and_made_whole_when_carried_out(stocked: World) -> None:
    body = letters(body_most())
    turn = stocked.guarded()
    assert not turn.call(READ, mailbox=ADDRESS, id="m1").is_error
    got = turn.call(SEND, **send_args(body=body))
    assert not got.is_error and got.content.startswith(CONFIG.held)
    assert body in turn.pending()
    assert not stocked.guarded().carry_out().is_error
    assert len(stocked.fake.sent) == 1 and stocked.fake.sent[0].body == body


def test_a_draft_of_exactly_the_limit_is_stored_whole_at_once_after_a_read(stocked: World) -> None:
    body = letters(body_most())
    turn = stocked.guarded()
    assert not turn.call(READ, mailbox=ADDRESS, id="m1").is_error
    assert not turn.call(DRAFT, **send_args(body=body)).is_error
    assert len(stocked.fake.drafts) == 1 and stocked.fake.drafts[0].body == body


@pytest.mark.parametrize("tool", [SEND, DRAFT])
def test_a_body_of_exactly_the_limit_is_made_in_an_untainted_turn(stocked: World, tool: str) -> None:
    body = letters(body_most())
    assert not stocked.guarded().call(tool, **send_args(body=body)).is_error
    made = (stocked.fake.sent if tool == SEND else stocked.fake.drafts)
    assert len(made) == 1 and made[0].body == body


@pytest.mark.parametrize("tool", [SEND, DRAFT])
def test_a_body_over_the_limit_is_refused_and_nothing_is_stored(stocked: World, tool: str) -> None:
    before = labels_now(stocked)
    failed(stocked.guarded().call(tool, **send_args(body=letters(body_most() + 1))))
    untouched(stocked, before)


@pytest.mark.parametrize("tool", [SEND, DRAFT])
def test_a_body_over_the_limit_is_never_made_even_when_it_was_held_first(stocked: World, tool: str) -> None:
    before = labels_now(stocked)
    turn = stocked.guarded()
    turn.call(READ, mailbox=ADDRESS, id="m1")
    turn.call(tool, **send_args(body=letters(body_most() + 1)))
    stocked.guarded().carry_out()
    untouched(stocked, before)


def test_a_send_with_no_recipient_sends_nothing(stocked: World) -> None:
    before = labels_now(stocked)
    args = send_args()
    del args["to"]
    failed(stocked.guarded().call(SEND, **args))
    failed(stocked.guarded().call(SEND, **send_args(to=[])))
    untouched(stocked, before)
    assert not stocked.guarded().call(SEND, **send_args()).is_error  # control: one recipient is sent to


@pytest.mark.parametrize("over", [{"to": ["dana@club.test\r\nBcc: evil@club.test"]},
                                  {"subject": "Hi\r\nBcc: evil@club.test"},
                                  {"cc": ["fay@club.test\nBcc: evil@club.test"]},
                                  {"reply_to": "m1\r\nBcc: evil@club.test"}],
                         ids=["to", "subject", "cc", "reply-to"])
@pytest.mark.parametrize("tool", [SEND, DRAFT])
def test_a_line_break_in_an_argument_adds_no_header_and_no_recipient(stocked: World, tool: str, over: dict[str, object]) -> None:
    stocked.guarded().call(tool, **send_args(**over))
    made = [*stocked.fake.sent, *stocked.fake.drafts]
    assert len(made) <= 1
    for one in made:
        assert "evil@club.test" not in (*one.to, *one.cc, *one.bcc) and one.bcc == () and "bcc" not in one.header_names
    assert not stocked.guarded().call(tool, **send_args()).is_error  # control: the same call without the break is made


def test_header_looking_lines_in_a_body_stay_in_the_body(stocked: World) -> None:
    body = "hello\nBcc: evil@club.test\n\nbye"
    assert not stocked.guarded().call(SEND, **send_args(body=body)).is_error
    one = stocked.fake.sent[0]
    assert one.body == body and one.bcc == () and "bcc" not in one.header_names
