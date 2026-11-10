"""What the record, the routes and the singleton log: ids and counts, never a password, a 2FA code, vault bytes, an
address or a token (design: "Nothing typed is stored or logged"; the repo rule that logs carry ids and counts)."""

import logging
import time

import pytest
from mail_bridge_blind_kube_support import FakeKube, Running, texts
from mail_bridge_blind_support import VAULT, World, b64, forms

EXTRA = b"KEYCHAINBYTES-51d2"


def test_routes_and_singleton_log_no_vault_token_or_address(world: World, kube: FakeKube, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    pod = world.begin("site-b", "pod-away")
    world.account("alana@proton.test")
    world.beat(pod)
    world.put(pod, 0, VAULT, keychain=EXTRA)
    world.put(pod, 0, b"STALE-VAULT-BYTES")
    world.event(pod, "sync_finished", "alana@proton.test")
    world.event(pod, "user_signed_out", "alana@proton.test")
    world.fetch(pod)
    world.beat(pod)
    with Running(world, kube) as job:
        job.wait_for(lambda: len(kube.created) == 1, limit=6)
    tokens = [pod.token, *kube.tokens_made()]
    logged = texts(caplog)
    assert "ashley.mail" in logged or "bridge" in logged.lower(), "control: the probe sees what was logged"
    for raw in (VAULT, EXTRA, b"STALE-VAULT-BYTES"):
        for form in forms(raw):
            assert form not in logged, f"{raw!r} reached a log line"
    for token in tokens:
        assert token not in logged, "a token reached a log line"
    assert "alana@proton.test" not in logged
    assert "Bearer" not in logged


def test_a_refused_write_back_is_logged_with_its_epoch_and_generation_and_not_its_vault(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    pod = world.begin()
    assert world.put(pod, 7, b"REFUSED-VAULT").status_code == 409
    logged = texts(caplog)
    assert "REFUSED-VAULT" not in logged and b64(b"REFUSED-VAULT") not in logged
    refused = [r for r in caplog.records if "refus" in r.getMessage() or "stale" in r.getMessage() or "conflict" in r.getMessage()]
    assert refused, "a refused write-back leaves a line (a failure the code answers is the one wanted afterwards)"
    fields = {str(k): str(v) for r in refused for k, v in dict(getattr(r, "fields", {})).items()}
    assert str(pod.epoch) in fields.values() or "epoch" in fields


def test_the_singleton_logs_each_pod_it_makes_with_ids_and_counts(world: World, kube: FakeKube, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    with Running(world, kube) as job:
        job.wait_for(lambda: len(kube.created) == 1)
        time.sleep(0.2)
    mail = [r for r in caplog.records if r.name.startswith("ashley.mail")]
    assert mail, "the singleton logs under ashley.mail"
    assert any(str(world.state().epoch) in str(getattr(r, "fields", {})) for r in mail), "a line names the epoch"
