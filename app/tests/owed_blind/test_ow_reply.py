"""`Reply.owed`: the key of the source she needed when she could not do what was asked for want of it; null otherwise."""

import pytest
from ashley.inference.reply import Reply
from owed_blind_support import HOUSE, reply
from pydantic import ValidationError


def test_owed_is_null_unless_the_model_sets_it() -> None:
    assert reply().model_dump()["owed"] is None
    assert Reply(spoken="a", text="b").model_dump()["owed"] is None


def test_owed_carries_the_source_key() -> None:
    assert reply(HOUSE).model_dump()["owed"] == HOUSE


def test_owed_is_in_the_schema_every_provider_is_sent_and_is_required_there() -> None:
    schema = Reply.model_json_schema()
    assert "owed" in schema["properties"]
    assert "owed" in schema["required"]
    assert "default" not in schema["properties"]["owed"]


def test_owed_is_not_a_free_form_object() -> None:
    with pytest.raises(ValidationError):
        Reply.model_validate({"spoken": "a", "text": "b", "owed": {"source": HOUSE}})
