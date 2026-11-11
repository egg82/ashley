"""The warm look pod is wired only with its Service address, the look image behind it; wired, the Looker is the
warm one and a singleton keeps the pod; unwired, a look has a pod of its own and nothing keeps one."""

import asyncio
from collections.abc import Callable, Coroutine, Generator
from pathlib import Path
from typing import Any

import httpx2
import pytest
from ashley import services, wiring_sandbox, wiring_singletons
from ashley.looks.kubernetes import KubernetesLooker
from ashley.looks.looker import Looker
from ashley.looks.warm_looker import WarmLooker
from ashley.runs.kube_api import KubeApi
from ashley.settings import Settings, from_env

IMAGE = "registry.example/look@sha256:" + "e" * 64
BASE = {"database_url": "postgresql://x", "build_version": "t", "sandbox_token_file": "/token", "sandbox_ca_file": "/ca",
        "files_endpoints": "http://nas.test", "files_bucket": "b", "files_access_key": "k", "files_secret_key": "s",
        "files_link_key": "l" * 40, "look_image": IMAGE, "look_app_url": "http://app:8080"}
ETCD = {"etcd_url": "http://127.0.0.1:1", "site": "willow"}
WARM = "http://ashley-look-warm.ashley-sandbox.svc:8080"


@pytest.fixture
def api(tmp_path: Path) -> Generator[KubeApi]:
    yield KubeApi(httpx2.AsyncClient(base_url="https://kube.test"), str(tmp_path / "token"))
    services.unregister(Looker)


def test_the_warm_pod_needs_the_look_image_and_not_etcd() -> None:
    with pytest.raises(ValueError, match="LOOK_WARM_URL needs"):
        Settings(look_warm_url=WARM, **{**BASE, **ETCD, "look_image": "", "look_app_url": ""})
    assert Settings(look_warm_url=WARM, **BASE).look_warm_url == WARM
    assert Settings(look_warm_url=WARM, **BASE, **ETCD).look_warm_url == WARM


def test_the_address_comes_from_the_environment_without_a_trailing_slash() -> None:
    env = {k.upper(): str(v) for k, v in {**BASE, **ETCD}.items()}
    assert from_env({**env, "LOOK_WARM_URL": WARM + "/"}).look_warm_url == WARM
    assert from_env(env).look_warm_url == ""


def test_with_an_address_the_looker_is_the_warm_one_and_its_client_is_closed_on_shutdown(api: KubeApi) -> None:
    closers: list[Callable[[], Coroutine[Any, Any, None]]] = []
    wiring_sandbox.wire_looker(Settings(look_warm_url=WARM, **BASE, **ETCD), api, closers)
    assert isinstance(services.get(Looker), WarmLooker) and len(closers) == 1
    asyncio.run(closers[0]())


def test_without_an_address_every_look_has_a_pod_of_its_own(api: KubeApi) -> None:
    closers: list[Callable[[], Coroutine[Any, Any, None]]] = []
    wiring_sandbox.wire_looker(Settings(**BASE), api, closers)
    assert isinstance(services.get(Looker), KubernetesLooker) and closers == []


def test_a_floating_look_image_is_refused_with_or_without_the_warm_pod(api: KubeApi) -> None:
    loose = Settings(**{**BASE, "look_image": "registry.example/look:latest"})
    with pytest.raises(ValueError, match="pinned"):
        wiring_sandbox.wire_looker(loose, api, [])


@pytest.mark.parametrize(("warm", "extra"), [(WARM, 1), ("", 0)])
def test_a_singleton_keeps_the_warm_pod_only_when_the_looker_is_the_warm_one(api: KubeApi, warm: str, extra: int) -> None:
    settings = Settings(look_warm_url=warm, **BASE, **ETCD)
    bare = wiring_singletons.singletons(Settings(database_url="x", build_version="t", **ETCD))
    wiring_sandbox.wire_looker(settings, api, [])
    running = wiring_singletons.singletons(settings)
    for coroutine in [*bare, *running]:
        coroutine.close()
    assert len(running) - len(bare) == extra
