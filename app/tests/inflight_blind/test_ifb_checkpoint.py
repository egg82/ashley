"""A turn's checkpoint, blind: its JSON round-trips, text `dumps` did not write is refused, and a change that began
with no result is resumed as an error, never to be run."""

import json
from dataclasses import replace

import pytest
from ashley.channels.checkpoint import INTERRUPTED, Checkpoint, dumps, loads
from ashley.channels.tool_loop import Progress
from ashley.inference.model import Message, ToolResult
from hypothesis import HealthCheck, given, settings
from ifb_checkpoint_support import asked, checkpoint, checkpoints, inbound

PROPERTY = settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@given(checkpoints())
@PROPERTY
def test_loads_of_dumps_is_the_same_checkpoint(c: Checkpoint) -> None:
    assert loads(dumps(c)) == c


@given(checkpoints())
@PROPERTY
def test_dumps_is_text_that_is_valid_json_and_stable_across_a_round_trip(c: Checkpoint) -> None:
    text = dumps(c)
    assert isinstance(json.loads(text), dict)
    assert dumps(loads(text)) == text


@given(checkpoints())
@PROPERTY
def test_a_round_trip_keeps_the_resume_the_same(c: Checkpoint) -> None:
    assert loads(dumps(c)).to_resume() == c.to_resume()


def test_a_round_trip_keeps_each_field() -> None:
    c = replace(checkpoint(asked(("c1", "look"), ("c2", "switch")), started=frozenset({"c2"}),
                           offered=frozenset({4, 9}), phone=12), turn="tok-1")
    got = loads(dumps(c))
    assert (got.conversation_id, got.said_id, got.speaker_id, got.phone, got.turn) == (5, 77, 1, 12, "tok-1")
    assert got.started == {"c2"} and got.offered == {4, 9}
    assert got.inbound == inbound() and got.system == c.system
    assert got.progress.asked is not None and [x.id for x in got.progress.asked.calls] == ["c1", "c2"]


def test_the_order_of_calls_and_entries_survives() -> None:
    c = checkpoint(asked(("z", "a"), ("a", "b"), ("m", "c")))
    got = loads(dumps(c))
    assert got.progress.asked is not None
    assert [x.id for x in got.progress.asked.calls] == ["z", "a", "m"]


def test_text_with_awkward_characters_survives() -> None:
    text = 'quote " backslash \\ newline \n tab \t nul \x00 emoji \U0001f600 é'
    c = replace(checkpoint(), inbound=inbound(text), progress=Progress((Message("person", text),), 0, 0))
    assert loads(dumps(c)) == c


@pytest.mark.parametrize("text", ["", "not json", "{}", '{"inbound": 1}'])
def test_loads_refuses_text_dumps_did_not_write(text: str) -> None:
    with pytest.raises((ValueError, KeyError)):
        loads(text)


@pytest.mark.parametrize("text", ["[]", "null", "7", '"text"'])
def test_loads_refuses_json_that_is_not_an_object_with_value_or_key_error(text: str) -> None:
    with pytest.raises((ValueError, KeyError)):
        loads(text)


def test_loads_refuses_a_round_in_flight_that_is_not_tool_calls() -> None:
    raw = json.loads(dumps(checkpoint(asked(("c1", "look")))))
    raw["asked"] = {"message": {"author": "person", "text": "hi"}}
    with pytest.raises(ValueError):
        loads(json.dumps(raw))


def test_loads_refuses_a_truncated_checkpoint() -> None:
    text = dumps(checkpoint(asked(("c1", "look"))))
    with pytest.raises((ValueError, KeyError)):
        loads(text[: len(text) // 2])


def test_a_started_change_with_no_result_resumes_as_an_interrupted_error() -> None:
    c = checkpoint(asked(("c1", "look"), ("c2", "switch")), started=frozenset({"c2"}))
    done = c.to_resume().done
    assert set(done) == {"c2"}
    assert done["c2"] == ToolResult("c2", INTERRUPTED, is_error=True)
    assert "may or may not have taken effect" in INTERRUPTED


def test_a_started_change_that_has_its_result_keeps_it() -> None:
    progress = replace(asked(("c2", "switch")), done={"c2": ToolResult("c2", '{"on": true}')})
    resumed = checkpoint(progress, started=frozenset({"c2"})).to_resume()
    assert resumed.done == {"c2": ToolResult("c2", '{"on": true}')}


def test_with_nothing_started_the_progress_is_unchanged() -> None:
    progress = replace(asked(("c1", "look")), done={})
    assert checkpoint(progress).to_resume() == progress


def test_resume_keeps_every_other_part_of_the_progress() -> None:
    progress = replace(asked(("c1", "look"), ("c2", "switch")), done={"c1": ToolResult("c1", "seen")}, rounds=3,
                       calls=9)
    resumed = checkpoint(progress, started=frozenset({"c2"})).to_resume()
    assert (resumed.entries, resumed.rounds, resumed.calls, resumed.asked) == (
        progress.entries, 3, 9, progress.asked)
    assert resumed.done["c1"] == ToolResult("c1", "seen")


def test_resume_does_not_change_the_checkpoint_it_was_asked_of() -> None:
    c = checkpoint(asked(("c2", "switch")), started=frozenset({"c2"}))
    before = dumps(c)
    c.to_resume()
    assert dumps(c) == before
    assert c.progress.done == {}


def test_each_started_change_with_no_result_is_made_an_error() -> None:
    c = checkpoint(asked(("c1", "a"), ("c2", "b"), ("c3", "c")), started=frozenset({"c1", "c2", "c3"}))
    assert {i: r.is_error for i, r in c.to_resume().done.items()} == {"c1": True, "c2": True, "c3": True}
