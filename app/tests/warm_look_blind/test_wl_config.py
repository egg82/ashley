"""The warm pod's settings: `warm_tick_s`, `warm_max_age_s` and `warm_connect_s` are data in `looks.json` (`parse`
rejects them missing or not positive), `Settings.look_warm_url` needs `look_image` and `etcd_url` and loses a trailing
slash, and wiring puts the warm looker in front of the pod-per-look one only when it is set."""

import json
from collections.abc import Callable, Coroutine, Generator
from typing import Any

import pytest
from ashley import services
from ashley.looks import config as looks_config
from ashley.looks.kubernetes import KubernetesLooker
from ashley.looks.looker import Looker, Shot, Target
from ashley.looks.warm_looker import WarmLooker
from ashley.settings import Settings, from_env
from ashley.wiring_sandbox import wire_looker
from warm_blind_support import FakeKube

RAW: dict[str, Any] = json.loads(looks_config.FILE.read_text())
ENV = {
    "DATABASE_URL": "postgresql://x", "BUILD_VERSION": "t", "SANDBOX_TOKEN_FILE": "/t", "SANDBOX_CA_FILE": "/c",
    "FILES_ENDPOINTS": "http://s3:9000", "FILES_BUCKET": "b", "FILES_ACCESS_KEY": "a", "FILES_SECRET_KEY": "s",
    "FILES_LINK_KEY": "k" * 40, "LOOK_IMAGE": "registry.test/look@sha256:" + "a" * 64, "LOOK_APP_URL": "http://app:8080",
    "ETCD_URL": "http://etcd:2379",
}
WARM = "http://ashley-look-warm.ashley-sandbox.svc:8080"


def test_the_shipped_limits_are_positive_and_load() -> None:
    config = looks_config.load()
    assert config.warm_tick_s > 0 and config.warm_max_age_s > 0 and config.warm_connect_s > 0


def test_the_shipped_file_holds_the_three_keys() -> None:
    assert {"warm_tick_s", "warm_max_age_s", "warm_connect_s"} <= set(RAW)


def test_a_value_in_the_file_is_the_value_loaded() -> None:
    config = looks_config.parse({**RAW, "warm_tick_s": 12, "warm_max_age_s": 3600, "warm_connect_s": 1.5})
    assert (config.warm_tick_s, config.warm_max_age_s, config.warm_connect_s) == (12, 3600, 1.5)


@pytest.mark.parametrize("key", ["warm_tick_s", "warm_max_age_s", "warm_connect_s"])
def test_a_missing_key_is_refused(key: str) -> None:
    data = {k: v for k, v in RAW.items() if k != key}
    with pytest.raises(ValueError):
        looks_config.parse(data)


@pytest.mark.parametrize("key", ["warm_tick_s", "warm_max_age_s", "warm_connect_s"])
@pytest.mark.parametrize("bad", [0, -1, -0.5, "5", None, [1]])
def test_a_value_that_is_not_a_positive_number_is_refused(key: str, bad: object) -> None:
    with pytest.raises(ValueError):
        looks_config.parse({**RAW, key: bad})


def test_an_unknown_key_is_still_refused() -> None:
    with pytest.raises(ValueError):
        looks_config.parse({**RAW, "warm_tock_s": 1})


def test_the_warm_url_loses_a_trailing_slash_and_is_empty_when_unset() -> None:
    assert from_env({**ENV, "LOOK_WARM_URL": WARM + "/"}).look_warm_url == WARM
    assert from_env({**ENV, "LOOK_WARM_URL": WARM}).look_warm_url == WARM
    assert from_env(ENV).look_warm_url == ""
    assert Settings(database_url="x", build_version="t").look_warm_url == ""


@pytest.mark.parametrize("without", ["LOOK_IMAGE", "ETCD_URL"])
def test_the_warm_url_needs_the_look_image_and_etcd(without: str) -> None:
    env = {**ENV, "LOOK_WARM_URL": WARM}
    del env[without]
    if without == "LOOK_IMAGE":
        del env["LOOK_APP_URL"]
    with pytest.raises(ValueError):
        from_env(env)


def test_the_warm_url_alone_is_refused() -> None:
    with pytest.raises(ValueError):
        from_env({"DATABASE_URL": "postgresql://x", "BUILD_VERSION": "t", "LOOK_WARM_URL": WARM})


@pytest.fixture
def looker_slot() -> Generator[None]:
    yield
    services.unregister(Looker)


def wired(env: dict[str, str]) -> Looker:
    closers: list[Callable[[], Coroutine[Any, Any, None]]] = []
    wire_looker(from_env(env), FakeKube(), "ashley-sandbox", "gvisor", closers)
    return services.get(Looker)


def test_without_a_warm_url_every_look_has_a_pod_of_its_own(looker_slot: None) -> None:
    looker = wired(ENV)
    assert isinstance(looker, KubernetesLooker) and not isinstance(looker, WarmLooker)


def test_with_a_warm_url_the_warm_looker_is_in_front(looker_slot: None) -> None:
    looker = wired({**ENV, "LOOK_WARM_URL": WARM})
    assert isinstance(looker, WarmLooker) and looker.renders()


def test_the_pod_is_kept_for_the_look_page_of_the_app_and_looks_go_to_the_warm_url(looker_slot: None) -> None:
    from warm_blind_support import go, pod_server
    from ashley.looks.warm_pod import NAME
    app_prefix = ENV["LOOK_APP_URL"] + "/look/"
    kube = FakeKube()
    with pod_server(prefix=app_prefix) as pod:
        closers: list[Callable[[], Coroutine[Any, Any, None]]] = []
        wire_looker(from_env({**ENV, "LOOK_WARM_URL": pod.base}), kube, "ashley-sandbox", "gvisor", closers)
        looker = services.get(Looker)
        assert isinstance(looker, WarmLooker)

        async def scenario() -> Shot:
            await looker.keeper.tick()
            try:
                return await looker.look("look-a", Target(1, 2, 3, None))
            finally:
                for close in closers:
                    await close()

        shot = go(scenario())
    env = {e["name"]: e["value"] for e in kube.created[0]["spec"]["containers"][0]["env"]}
    assert env["ASHLEY_LOOK_PREFIX"] == app_prefix and NAME in kube.pods_by_name
    assert len(pod.seen) == 1 and pod.seen[0].startswith(app_prefix)
    assert shot.data and kube.count("create") == 1
