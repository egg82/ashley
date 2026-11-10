"""Directed tests for the mutants the blind suite alone let live (MUTANTS.txt, R8, S21, K13)."""

import json

from collections.abc import Callable

from mail_bridge_blind_keeper_support import FENCE_S, FakeApp, Keeper
from mail_bridge_blind_kube_support import FakeKube, Running
from mail_bridge_blind_support import VAULT, World, forms


def test_a_write_back_refused_at_a_stale_generation_does_not_stamp_the_heartbeat(world: World) -> None:
    pod = world.begin()
    assert world.put(pod, 5).status_code == 409
    assert world.state().heartbeat_at is None


def test_the_token_secret_carries_the_vault_in_no_form(world: World, kube: FakeKube) -> None:
    old = world.begin("site-b", "away")
    assert world.put(old, 0, VAULT).status_code == 200
    with Running(world, kube) as job:
        assert job.wait_for(lambda: len(kube.created) == 1, limit=6)
    text = json.dumps([kube.created, kube.secrets_by_name])
    for form in forms(VAULT):
        assert form not in text


def test_a_write_back_that_cannot_reach_the_app_stops_bridge_before_the_fence_would(fake_app: FakeApp, keeper_for: Callable[..., Keeper]) -> None:
    keeper = keeper_for(fake_app, refresh=False)
    assert keeper.bridge_up()
    fake_app.hang_up_writes = True
    keeper.rewrite_vault(b"never-stored")
    code = keeper.exited(FENCE_S - 0.5)
    assert code not in (None, 0), keeper.output()
    assert not keeper.bridge_alive()
