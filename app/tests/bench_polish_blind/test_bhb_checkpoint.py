"""What a steering turn's checkpoint must carry to another pod: the ids handed so far (`Progress.steered`), whether the
turn was left to a turn of its own (`Checkpoint.left`) and the bench talk its ask was carried into
(`Checkpoint.carried`)."""

from dataclasses import replace

import pytest
from ashley.channels.checkpoint import Checkpoint, dumps, loads
from ashley.channels.model import on_bench
from ashley.channels.tool_loop import Progress
from ashley.inference.model import Message, SystemPrompt


def checkpoint(**changes: object) -> Checkpoint:
    progress = Progress((Message("person", "hi"), Message("ashley", "draft")), 2, 1, None, {}, (11, 14, 12))
    base = Checkpoint(on_bench(1, 2, 3, "hi"), 5, 9, 2, {"default": SystemPrompt("s", "m")}, progress)
    return replace(base, **changes)


def test_the_ids_handed_so_far_survive_a_pod_in_the_order_they_were_handed() -> None:
    assert loads(dumps(checkpoint())).progress.steered == (11, 14, 12)


@pytest.mark.parametrize("carried", [(7, 31), None])
def test_the_bench_talk_a_landed_turn_was_carried_into_survives_a_pod(carried: tuple[int, int] | None) -> None:
    assert loads(dumps(checkpoint(carried=carried))).carried == carried


@pytest.mark.parametrize("left", [True, False])
def test_a_turn_left_to_a_turn_of_its_own_stays_left_across_a_pod(left: bool) -> None:
    assert loads(dumps(checkpoint(left=left))).left is left


def test_a_bench_message_keeps_its_steering_in_the_checkpoint() -> None:
    assert loads(dumps(checkpoint())).inbound.steers is True
