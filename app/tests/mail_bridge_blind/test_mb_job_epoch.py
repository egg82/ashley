"""The singleton's decisions about epochs, adoption and the fence (design: "Exactly one Bridge, fenced by the epoch",
points 1 and 5), driven with the real record and a fake Kubernetes. Times are real and short (`config()`: fence 1.0 s,
margin 0.5 s); a test that waits is waiting out the fence. Most move the old pod's last sign of life back with
`World.age`, so only the tail of that wait passes in real time."""

import time

import pytest
from ashley.mail import config as mail_config
from ashley.runs.kube_api import KubeError
from mail_bridge_blind_kube_support import FakeKube, Keeping, Running
from mail_bridge_blind_support import FAST, World, config

FENCE, MARGIN = FAST["fence_s"], FAST["fence_margin_s"]
TOL = 0.12


def test_the_first_start_raises_the_epoch_once_and_makes_one_pod_at_once(world: World, kube: FakeKube) -> None:
    with Running(world, kube) as job:
        assert job.wait_for(lambda: len(kube.created) == 1)
        time.sleep(0.3)
    state = world.state()
    assert state.epoch == 1 and state.site == "site-a"
    assert len(kube.created) == 1 and state.pod == kube.created[0]["metadata"]["name"]


def test_a_pod_of_the_current_epoch_on_this_site_with_a_fresh_heartbeat_is_adopted_as_it_is(world: World, kube: FakeKube) -> None:
    pod = world.begin("site-a", "bridge-live")
    world.beat(pod)
    kube.add_pod("bridge-live")
    with Running(world, kube) as job:
        time.sleep(0.8)
        job.survived()
    assert world.state().epoch == pod.epoch
    assert kube.created == [] and kube.at("delete_pod") == []
    assert world.beat(pod).status_code == 200, "the adopted pod is not retired"


def test_adoption_keeps_every_accounts_sync(world: World, kube: FakeKube) -> None:
    pod = world.begin("site-a", "bridge-live")
    world.account("u1")
    world.beat(pod)
    assert world.event(pod, "sync_finished").status_code == 200
    kube.add_pod("bridge-live")
    with Running(world, kube):
        time.sleep(0.6)
    assert [a.syncing for a in world.accounts()] == [False]


def test_a_same_site_pod_whose_heartbeat_is_older_than_fence_s_is_not_adopted_and_the_epoch_is_raised_by_one(world: World, kube: FakeKube) -> None:
    pod = world.begin("site-a", "bridge-quiet")
    world.beat(pod)
    kube.add_pod("bridge-quiet")
    world.age(FENCE + 0.15, pod)
    with Running(world, kube) as job:
        assert job.wait_for(lambda: world.state().epoch == pod.epoch + 1)
    assert world.state().epoch == pod.epoch + 1
    assert world.beat(pod).status_code in (401, 403, 409)


def test_a_new_holder_waits_until_the_old_epochs_last_heartbeat_is_fence_plus_margin_old_before_it_makes_a_pod(world: World, kube: FakeKube) -> None:
    pod = world.begin("site-a", "bridge-old")
    world.beat(pod)
    world.age(FENCE + 0.15, pod)
    beat_at = pod.last_beat
    kube.add_pod("bridge-old")
    with Running(world, kube) as job:
        assert job.wait_for(lambda: len(kube.created) == 1, limit=6)
    made = kube.created_at()[0]
    assert made - beat_at >= FENCE + MARGIN - TOL, f"made a pod {made - beat_at:.2f}s after the old heartbeat"
    assert made - beat_at <= FENCE + MARGIN + 0.8


def test_the_epoch_is_raised_before_the_wait_so_the_old_pod_is_retired_while_the_new_holder_waits(world: World, kube: FakeKube) -> None:
    old = world.begin("site-b", "bridge-away")
    world.beat(old)
    with Running(world, kube) as job:
        assert job.wait_for(lambda: world.state().epoch == old.epoch + 1, limit=0.6)
        assert kube.created == []
        assert world.beat(old).status_code in (401, 403, 409)


def test_a_pod_of_the_other_site_is_never_adopted_however_fresh_its_heartbeat(world: World, kube: FakeKube) -> None:
    other = world.begin("site-b", "bridge-away")
    world.beat(other)
    world.age(FENCE + 0.2, other)
    kube.add_pod("bridge-away")
    with Running(world, kube) as job:
        assert job.wait_for(lambda: len(kube.created) == 1, limit=6)
    state = world.state()
    assert state.epoch == other.epoch + 1 and state.site == "site-a" and state.pod != "bridge-away"
    assert kube.at("delete_pod") == [] or all(n != state.pod for _, n in kube.at("delete_pod"))


def test_the_wait_is_counted_from_the_old_epochs_last_heartbeat_not_from_the_moment_the_holder_took_over(world: World, kube: FakeKube) -> None:
    old = world.begin("site-b", "bridge-away")
    world.beat(old)
    world.age(1.2, old)
    beat_at = old.last_beat
    with Running(world, kube) as job:
        assert job.wait_for(lambda: len(kube.created) == 1, limit=6)
    made = kube.created_at()[0]
    assert FENCE + MARGIN - TOL <= made - beat_at <= FENCE + MARGIN + 0.45, f"{made - beat_at:.2f}s"


def test_two_bridges_never_run_from_one_vault_a_cut_off_pod_that_keeps_heartbeating_is_retired_and_its_write_back_refused(world: World, kube: FakeKube) -> None:
    old = world.begin("site-b", "bridge-away")
    world.put(old, 0, b"vault-of-the-old-site")
    keeping = Keeping(world, old, every=0.1)
    time.sleep(0.4)
    try:
        with Running(world, kube) as job:
            assert job.wait_for(lambda: world.state().epoch == old.epoch + 1, limit=3)
            raised = time.monotonic()
            assert job.wait_for(lambda: keeping.refused is not None, limit=2)
            assert keeping.refused in (401, 403, 409)
            assert keeping.refused_at - raised < 0.5, "the old pod was retired at its next heartbeat"
            assert world.put(old, 1, b"FORKED-vault").status_code in (401, 403, 409)
            assert kube.created == [], "no pod is made while the old one could still be running"
            assert job.wait_for(lambda: len(kube.created) == 1, limit=6)
            assert kube.created_at()[0] - old.last_beat >= FENCE + MARGIN - TOL
    finally:
        keeping.stop()
    assert world.state().generation == 1


def test_a_pod_that_ends_is_followed_by_a_new_epoch_and_pod_after_restart_s(world: World, kube: FakeKube) -> None:
    with Running(world, kube) as job:
        assert job.wait_for(lambda: len(kube.created) == 1)
        first = world.state()
        ended = time.monotonic()
        kube.end_pod(first.pod, "deleted")
        world.age(FENCE - 0.1)
        assert job.wait_for(lambda: len(kube.created) == 2, limit=6)
    made = kube.created_at()[1]
    assert made - ended >= FAST["restart_s"] - 0.1, f"restarted after {made - ended:.2f}s"
    state = world.state()
    assert state.epoch == first.epoch + 1 and state.pod != first.pod


@pytest.mark.parametrize("phase", ["Failed", "Succeeded"])
def test_a_pod_whose_phase_says_it_ended_is_replaced_under_a_new_epoch(world: World, kube: FakeKube, phase: str) -> None:
    with Running(world, kube) as job:
        assert job.wait_for(lambda: len(kube.created) == 1)
        first = world.state()
        kube.end_pod(first.pod, phase)
        assert job.wait_for(lambda: len(kube.created) == 2, limit=6)
    assert world.state().epoch == first.epoch + 1


def test_a_holder_that_loses_the_lease_does_not_delete_its_pod(world: World, kube: FakeKube) -> None:
    job = Running(world, kube)
    assert job.wait_for(lambda: len(kube.created) == 1)
    job.stop()
    assert kube.at("delete_pod") == [] and kube.at("delete_secret") == []
    assert len(kube.pods_by_name) == 1


def test_a_failed_pod_create_is_survived_and_tried_again(world: World, kube: FakeKube) -> None:
    kube.fail_create.append(KubeError("http 500"))
    with Running(world, kube) as job:
        assert job.wait_for(lambda: world.state().epoch == 2)
        world.age(FENCE)
        assert job.wait_for(lambda: len(kube.created) >= 1, limit=8)
        job.survived()


def test_the_job_never_writes_the_vault_or_raises_the_generation(world: World, kube: FakeKube) -> None:
    pod = world.begin("site-a", "bridge-live")
    world.put(pod, 0, b"vault-0")
    world.beat(pod)
    kube.add_pod("bridge-live")
    with Running(world, kube):
        time.sleep(0.5)
    assert world.state().generation == 1


def test_config_holds_the_four_named_settings_as_positive_seconds() -> None:
    cfg = config()
    for name in ("fence_s", "fence_margin_s", "heartbeat_s", "restart_s"):
        assert getattr(cfg, name) > 0, name
    shipped = mail_config.load()
    assert shipped.heartbeat_s < shipped.fence_s, "a keeper heartbeats inside the fence"
