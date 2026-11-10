"""The fence decision (`ashley.mail.proton_fence.decide`) as a table: a pod of this site heard within `fence_s` is adopted;
one of the other site, unheard, gone or none is retired by raising the epoch; a raised epoch's pod is made only once the
older epoch's last sign of life is `fence_s + fence_margin_s` old; an ended pod is replaced without that wait."""

import pytest
from ashley.mail.proton_bridge import Holder
from ashley.mail.proton_fence import PodState, Step, decide

FENCE, MARGIN = 30.0, 15.0


def step(holder: Holder, pod: PodState = "running", site: str = "birch") -> tuple[Step, float]:
    got = decide(holder, site, pod, FENCE, MARGIN)
    return got.step, got.wait_s


@pytest.mark.parametrize("holder,pod,expected", [
    (Holder(3, "birch", "p", 2.0), "running", Step.ADOPT),
    (Holder(3, "birch", "p", FENCE - 0.1), "running", Step.ADOPT),
    (Holder(3, "birch", "p", FENCE), "running", Step.RAISE),
    (Holder(3, "willow", "p", 1.0), "running", Step.RAISE),
    (Holder(3, "willow", "p", 1.0), "absent", Step.RAISE),
    (Holder(3, "birch", "p", 1.0), "absent", Step.RAISE),
    (Holder(0, None, None, None), "absent", Step.RAISE),
    (Holder(3, "birch", "p", 1.0), "ended", Step.REPLACE),
    (Holder(3, "willow", "p", 1.0), "ended", Step.RAISE),
    (Holder(3, "birch", "p", 1.0), "stale", Step.RAISE),
    (Holder(3, "willow", "p", 1.0), "stale", Step.RAISE),
])
def test_what_the_holder_and_its_pod_decide(holder: Holder, pod: PodState, expected: Step) -> None:
    assert step(holder, pod)[0] is expected


def test_each_raise_says_why() -> None:
    cases: list[tuple[Holder, PodState]] = [
        (Holder(0, None, None, None), "absent"), (Holder(3, "willow", "p", 1.0), "running"),
        (Holder(3, "birch", "p", 99.0), "running"), (Holder(3, "birch", "p", 1.0), "absent"),
        (Holder(3, "birch", "p", 1.0), "stale")]
    reasons = [decide(h, "birch", p, FENCE, MARGIN).reason for h, p in cases]
    assert reasons == ["first", "other_site", "unheard", "gone", "image"]


def test_a_raised_epoch_waits_out_the_older_fence_by_the_database_clock() -> None:
    needed = FENCE + MARGIN
    assert step(Holder(4, "birch", None, 10.0), "absent") == (Step.WAIT, needed - 10.0)
    assert step(Holder(4, "birch", None, needed - 0.5), "absent")[0] is Step.WAIT
    assert step(Holder(4, "birch", None, needed), "absent")[0] is Step.MAKE
    assert step(Holder(4, "birch", None, None), "absent")[0] is Step.MAKE


def test_a_raised_epoch_of_the_other_site_is_not_this_sites_to_make() -> None:
    assert step(Holder(4, "willow", None, 1.0), "absent")[0] is Step.RAISE
