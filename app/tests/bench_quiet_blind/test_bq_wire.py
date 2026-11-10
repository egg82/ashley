"""The wire models: `ChatAttachment` (title up to 120 characters, text 1 to `ATTACHMENT_MAX_CHARS`, not only
whitespace), `ChatMessage.attachment` and `BenchMessage.piece_id`."""

import pytest
from ashley.api import chat_models
from ashley.api.chat_models import ATTACHMENT_MAX_CHARS, BenchMessage, ChatAttachment, ChatMessage
from pydantic import ValidationError

MAX = ATTACHMENT_MAX_CHARS


def test_the_maximum_is_twenty_thousand() -> None:
    assert MAX == 20000


def test_a_paste_of_exactly_the_maximum_is_accepted_and_one_over_is_not() -> None:
    assert len(ChatAttachment(text="a" * MAX).text) == MAX
    with pytest.raises(ValidationError):
        ChatAttachment(text="a" * (MAX + 1))


def test_the_maximum_counts_characters_not_bytes() -> None:
    assert len(ChatAttachment(text="é" * MAX).text) == MAX
    with pytest.raises(ValidationError):
        ChatAttachment(text="é" * (MAX + 1))


@pytest.mark.parametrize("text", ["", " ", " \n\t ", " "])
def test_a_paste_of_nothing_is_refused(text: str) -> None:
    with pytest.raises(ValidationError):
        ChatAttachment(text=text)


def test_a_paste_with_a_nul_is_refused() -> None:
    with pytest.raises(ValidationError):
        ChatAttachment(text="ab\x00cd")
    with pytest.raises(ValidationError):
        ChatAttachment(title="a\x00b", text="body")


def test_the_title_is_optional_up_to_120_characters_and_not_empty() -> None:
    assert ChatAttachment(text="body").title is None
    assert ChatAttachment(title=None, text="body").title is None
    assert ChatAttachment(title="t" * 120, text="body").title == "t" * 120
    for bad in ("t" * 121, ""):
        with pytest.raises(ValidationError):
            ChatAttachment(title=bad, text="body")


def test_a_paste_keeps_its_text_exactly() -> None:
    text = "  line one\n\n\tline two  \n"
    assert ChatAttachment(text=text).text == text


def test_a_paste_takes_no_other_field() -> None:
    with pytest.raises(ValidationError):
        ChatAttachment.model_validate({"text": "body", "kind": "note"})


def test_a_chat_message_has_an_optional_attachment_beside_its_text() -> None:
    assert ChatMessage(text="hi").attachment is None
    got = ChatMessage.model_validate({"text": "hi", "attachment": {"title": "T", "text": "body"}})
    assert got.attachment == ChatAttachment(title="T", text="body")
    assert got.text == "hi"


def test_a_chat_message_is_still_a_typed_message() -> None:
    with pytest.raises(ValidationError):
        ChatMessage.model_validate({"text": "  ", "attachment": {"text": "body"}})
    with pytest.raises(ValidationError):
        ChatMessage.model_validate({"text": "x" * 4001})
    assert len(ChatMessage(text="x" * 4000).text) == 4000
    with pytest.raises(ValidationError):
        ChatMessage.model_validate({"text": "hi", "attachment": {"text": "a" * (MAX + 1)}})


def test_a_bench_message_names_a_piece_by_a_positive_id_and_takes_no_attachment() -> None:
    assert BenchMessage(text="hi").piece_id is None
    assert BenchMessage(text="hi", piece_id=1).piece_id == 1
    for bad in (0, -3):
        with pytest.raises(ValidationError):
            BenchMessage(text="hi", piece_id=bad)
    with pytest.raises(ValidationError):
        BenchMessage.model_validate({"text": "hi", "attachment": {"text": "body"}})
    with pytest.raises(ValidationError):
        BenchMessage.model_validate({"text": "hi", "piece_id": 4, "attachment": {"text": "body"}})


def test_the_models_live_in_chat_models() -> None:
    assert {"ChatAttachment", "ChatMessage", "BenchMessage"} <= set(dir(chat_models))
