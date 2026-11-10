"""What `respond` raises: ValueError for an empty text or thread before anything is read or written;
RespondUnavailable when People, Conversations or Inference cannot be reached or no model answered; RespondRefused when
the model declined, with no turn of hers stored; and once past step 2, the person's turn stays stored."""

import pytest
from ashley.channels.respond import RespondError, RespondRefused, RespondUnavailable, respond
from ashley.conversations.conversations import ConversationsUnavailable
from ashley.inference.inference import InferenceRefused, InferenceUnavailable
from ashley.people.people import PeopleUnavailable
from inference_support import settle
from turns_support import ALANA, World, asks, inbound, world as world


def test_the_errors_share_a_base() -> None:
    assert issubclass(RespondUnavailable, RespondError) and issubclass(RespondRefused, RespondError)


@pytest.mark.parametrize(("text", "thread"), [("", "device:3"), ("hello", ""), ("", "")])
def test_an_empty_text_or_thread_is_a_value_error_before_anything_is_touched(world: World, text: str,
                                                                             thread: str) -> None:
    with pytest.raises(ValueError):
        settle(respond(inbound(text=text, thread=thread)))
    assert world.touched() == 0


def test_people_unreachable_is_unavailable_and_nothing_is_stored(world: World) -> None:
    world.people.error = PeopleUnavailable("down")
    with pytest.raises(RespondUnavailable):
        settle(respond(inbound()))
    assert world.conversations.added == []
    assert world.inference.asked == []


@pytest.mark.parametrize("closing", [0, 1])
def test_conversations_unreachable_is_unavailable(world: World, closing: int) -> None:
    world.conversations.error = ConversationsUnavailable("failover")
    world.conversations.closing = closing
    with pytest.raises(RespondUnavailable):
        settle(respond(inbound()))
    assert world.inference.asked == []


@pytest.mark.parametrize("rounds", [0, 1])
def test_no_model_answering_is_unavailable_and_the_person_turn_stays(world: World, rounds: int) -> None:
    world.inference.script = [asks("lights")] * rounds
    world.inference.then = InferenceUnavailable("no route answered")
    with pytest.raises(RespondUnavailable):
        settle(respond(inbound(text="are you there", speaker_id=ALANA.id)))
    (cid,) = set(world.conversations.threads.values())
    assert world.conversations.turns_of(cid) == [("person", ALANA.id, "are you there")]


@pytest.mark.parametrize("rounds", [0, 2])
def test_a_refusal_raises_refused_and_her_refusal_is_not_stored(world: World, rounds: int) -> None:
    world.inference.script = [asks("lights")] * rounds
    world.inference.then = InferenceRefused("declined")
    with pytest.raises(RespondRefused):
        settle(respond(inbound(text="say something awful")))
    (cid,) = set(world.conversations.threads.values())
    assert world.conversations.turns_of(cid) == [("person", None, "say something awful")]


def test_the_closed_retry_happens_once_only(world: World) -> None:
    """Closed twice running is not retried forever; whatever it raises, it is no more than two `for_thread` calls."""
    world.conversations.closing = 5
    with pytest.raises(Exception):
        settle(respond(inbound()))
    assert len(world.conversations.thread_calls) == 2
