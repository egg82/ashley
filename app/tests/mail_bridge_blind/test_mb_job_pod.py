"""What the singleton makes: the pod and its token Secret (design: "The pod, built from ... Containerfile ... made by the
singleton through `KubeApi` ... Its cache is an `emptyDir`, never shipped", and "a token minted per epoch whose hash the
record keeps")."""

import json
import time
from typing import Any

from mail_bridge_blind_kube_support import FakeKube, Running
from mail_bridge_blind_support import IMAGE, NS, World, sha


def made_once(world: World, kube: FakeKube) -> dict[str, Any]:
    with Running(world, kube) as job:
        assert job.wait_for(lambda: len(kube.created) == 1)
        time.sleep(0.2)
    return kube.created[0]


def test_the_pod_is_made_in_the_configured_namespace_from_the_pinned_image(world: World, kube: FakeKube) -> None:
    manifest = made_once(world, kube)
    assert kube.namespaces == {NS}
    images = [c["image"] for c in manifest["spec"]["containers"]]
    assert images and set(images) == {IMAGE}


def test_the_cache_is_an_emptydir_and_no_volume_is_a_claim_a_host_path_or_a_secret(world: World, kube: FakeKube) -> None:
    manifest = made_once(world, kube)
    volumes = manifest["spec"].get("volumes", [])
    assert any("emptyDir" in v for v in volumes), volumes
    for volume in volumes:
        assert not {"persistentVolumeClaim", "hostPath", "configMap", "nfs"} & set(volume), volume
    assert "volumeClaimTemplates" not in json.dumps(manifest)


def test_the_token_is_minted_per_epoch_and_the_record_keeps_only_its_hash(world: World, kube: FakeKube) -> None:
    with Running(world, kube) as job:
        assert job.wait_for(lambda: len(kube.created) == 1)
        first = world.state()
        kube.end_pod(first.pod, "deleted")
        assert job.wait_for(lambda: len(kube.created) == 2, limit=6)
    state = world.state()
    tokens = kube.tokens_made()
    assert len(tokens) == 2 and len(set(tokens)) == 2, "one fresh token per epoch"
    assert first.token_hash == sha(tokens[0]) and state.token_hash == sha(tokens[1])
    assert tokens[0] not in repr(state)


def test_no_pod_manifest_carries_the_token_in_the_clear(world: World, kube: FakeKube) -> None:
    with Running(world, kube) as job:
        assert job.wait_for(lambda: len(kube.created) == 1)
        job.wait_for(lambda: bool(kube.tokens_made()))
    token = kube.tokens_made()[0]
    assert token not in json.dumps(kube.created)


def test_the_secret_is_made_before_the_pod_that_reads_it(world: World, kube: FakeKube) -> None:
    made_once(world, kube)
    order = [v for _, v, _ in kube.events if v in ("create_secret", "create_pod")]
    assert order[:2] == ["create_secret", "create_pod"]


def test_the_record_names_the_pod_that_was_made_and_the_site_that_made_it(world: World, kube: FakeKube) -> None:
    manifest = made_once(world, kube)
    state = world.state()
    assert state.pod == manifest["metadata"]["name"] and state.site == "site-a"


def test_nothing_in_the_manifest_or_secret_carries_a_vault_or_a_password(world: World, kube: FakeKube) -> None:
    pod = world.begin("site-b", "away")
    world.put(pod, 0, b"VAULTBYTES-7f3a9c-0")
    with Running(world, kube) as job:
        job.wait_for(lambda: len(kube.created) == 1, limit=6)
    text = json.dumps([kube.created, kube.secrets_by_name])
    assert "VAULTBYTES" not in text
