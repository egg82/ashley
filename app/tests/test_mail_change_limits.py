"""The longest draft body and the most messages a label call names are held against `max_argument_chars`
(`ashley/tools/outside.json`): a held call past that limit is refused, so a call the tool accepts must fit it with every
other argument at its own limit."""

import pytest
from ashley.mail import config as mail_config
from ashley.tools import mail_args, outside_config
from ashley.tools.bench_args import BadArguments
from ashley.tools.outside_summary import arguments_chars

MAIL = mail_config.load()
HELD = outside_config.load().max_argument_chars
ADDRESS = "a" * (mail_args.RECIPIENT_MAX - len("@b.test")) + "@b.test"


def longest_draft() -> dict[str, object]:
    return {"mailbox": "m" * mail_args.ADDRESS_MAX, "to": [ADDRESS] * (MAIL.max_recipients - 1), "cc": [ADDRESS],
            "subject": "s" * mail_args.TEXT_MAX, "body": "b" * MAIL.max_body_chars, "reply_to": "r" * MAIL.message_id_chars}


def longest_label() -> dict[str, object]:
    shown = {"id": "i" * MAIL.message_id_chars, "from": "f" * mail_args.SHOWN_MAX, "subject": "s" * mail_args.SHOWN_MAX}
    names = ["n" * mail_args.LABEL_NAME_MAX] * mail_args.LABELS_MAX
    return {"mailbox": "m" * mail_args.ADDRESS_MAX, "messages": [shown] * MAIL.max_change_ids, "add": names,
            "remove": names, "folder": "archive", "unread": False}


def test_the_longest_draft_the_tool_takes_fits_a_held_call() -> None:
    draft = longest_draft()
    assert mail_args.draft(draft, MAIL).body == draft["body"]
    assert arguments_chars(draft) <= HELD


def test_the_longest_label_call_the_tool_takes_fits_a_held_call() -> None:
    call = longest_label()
    assert len(mail_args.targets(call, MAIL)) == MAIL.max_change_ids
    assert arguments_chars(call) <= HELD


def test_one_more_character_of_body_is_refused_by_the_tool() -> None:
    with pytest.raises(BadArguments):
        mail_args.draft({**longest_draft(), "body": "b" * (MAIL.max_body_chars + 1)}, MAIL)


def test_a_body_is_counted_in_characters_not_bytes() -> None:
    body = "é" * MAIL.max_body_chars
    assert mail_args.draft({**longest_draft(), "body": body}, MAIL).body == body


def test_labels_given_as_one_string_are_refused_not_read_as_letters() -> None:
    with pytest.raises(BadArguments):
        mail_args.change({"add": "School"})
    with pytest.raises(BadArguments):
        mail_args.change({"folder": "inbox", "remove": "x"})
