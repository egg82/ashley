"""The warm pod's keeper against a fake API (`sandbox_support.FakeKube`): it makes the pod when there is none, leaves a
good one (a holder taking over adopts it), replaces one that ended, is for other limits or an image, or is too old, and
tries again after the API fails. The pod it makes is the look pod kept up, not a copy that drifted."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from ashley.looks import config
from ashley.looks.kubernetes import SHOOTER
from ashley.looks.pod_spec import LABEL, WARM_LABEL, manifest
from ashley.looks.warm_pod import NAME, RECHECK_S, SPEC_ANNOTATION, WarmPod
from sandbox_support import Clock, FakeKube, Script
from warm_look_support import events

CONFIG = config.load()
IMAGE = "mcr.example/browser@sha256:" + "b" * 64
PREFIX = "http://ashley.test:8080/look/"


def keeper(fake: FakeKube, image: str = IMAGE, cfg: config.LooksConfig = CONFIG, clock: Clock | None = None) -> WarmPod:
    clock = clock or Clock()
    return WarmPod(fake.api(), "ashley-sandbox", "gvisor", image, PREFIX, SHOOTER, cfg, sleep=clock.sleep, clock=clock)


@pytest.fixture
def fake(tmp_path: Path) -> FakeKube:
    return FakeKube(tmp_path / "token", Script(phases=["Running"]))


def age(fake: FakeKube, seconds: int) -> None:
    fake.pods[NAME]["metadata"]["creationTimestamp"] = (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()


def test_with_no_pod_it_makes_one_named_for_the_service_and_the_network_policy(fake: FakeKube) -> None:
    assert asyncio.run(keeper(fake).tick()) is False
    pod = fake.created[0]
    assert pod["metadata"]["name"] == NAME
    assert pod["metadata"]["labels"] == {LABEL: "true", WARM_LABEL: "true"}
    spec = pod["spec"]
    assert spec["restartPolicy"] == "Always" and "activeDeadlineSeconds" not in spec
    assert spec["runtimeClassName"] == "gvisor" and spec["automountServiceAccountToken"] is False
    container = spec["containers"][0]
    env = {e["name"]: e["value"] for e in container["env"]}
    assert env["ASHLEY_LOOK_MODE"] == "serve" and env["ASHLEY_LOOK_PREFIX"] == PREFIX and "ASHLEY_LOOK_URL" not in env
    assert container["command"][-1] == SHOOTER and container["image"] == IMAGE
    assert container["ports"] == [{"containerPort": 8080}]
    assert container["readinessProbe"]["httpGet"] == {"path": "/healthz", "port": 8080}
    assert container["resources"]["limits"]["memory"] == CONFIG.memory


def test_the_warm_pod_is_locked_down_as_a_look_pod_is(fake: FakeKube) -> None:
    asyncio.run(keeper(fake).tick())
    warm = fake.created[0]["spec"]
    cold = manifest("look-x", "http://u", CONFIG, IMAGE, "gvisor", SHOOTER)["spec"]
    for key in ("securityContext", "volumes", "hostNetwork", "hostPID", "hostIPC", "enableServiceLinks",
                "terminationGracePeriodSeconds"):
        assert warm[key] == cold[key]
    assert warm["containers"][0]["securityContext"] == cold["containers"][0]["securityContext"]
    assert warm["containers"][0]["resources"] == cold["containers"][0]["resources"]


def test_a_good_pod_is_left_alone_and_adopted_once(fake: FakeKube, caplog: pytest.LogCaptureFixture) -> None:
    asyncio.run(keeper(fake).tick())
    taker = keeper(fake)
    with caplog.at_level(logging.INFO, logger="ashley.looks"):
        assert asyncio.run(taker.tick()) is False
        assert asyncio.run(taker.tick()) is False
    assert len(fake.created) == 1 and fake.deleted == []
    adopted = events(caplog, "looks.warm_adopted")
    assert len(adopted) == 1 and adopted[0]["pod"] == NAME


@pytest.mark.parametrize("change", ["ended", "image", "limits", "aged"])
def test_a_pod_that_is_wrong_is_deleted_then_made_again(fake: FakeKube, change: str,
                                                        caplog: pytest.LogCaptureFixture) -> None:
    asyncio.run(keeper(fake).tick())
    image, cfg = IMAGE, CONFIG
    if change == "ended":
        fake.script.phases = ["Failed"]
    elif change == "image":
        image = "mcr.example/browser@sha256:" + "c" * 64
    elif change == "limits":
        cfg = config.parse({**{f: getattr(CONFIG, f) for f in CONFIG.__dataclass_fields__}, "width": 999})
    else:
        age(fake, CONFIG.warm_max_age_s + 10)
    taker = keeper(fake, image, cfg)
    with caplog.at_level(logging.INFO, logger="ashley.looks"):
        assert asyncio.run(taker.tick()) is True
        assert fake.deleted == [NAME] and NAME not in fake.pods
        assert asyncio.run(taker.tick()) is False
    assert len(fake.created) == 2 and NAME in fake.pods
    replaced = events(caplog, "looks.warm_replaced")
    assert [e["reason"] for e in replaced] == [{"ended": "ended", "image": "spec_changed", "limits": "spec_changed",
                                                "aged": "aged"}[change]]


def test_a_young_pod_of_the_same_spec_is_not_replaced(fake: FakeKube) -> None:
    asyncio.run(keeper(fake).tick())
    age(fake, CONFIG.warm_max_age_s - 60)
    assert asyncio.run(keeper(fake).tick()) is False and fake.deleted == []


def test_a_pod_already_being_deleted_is_left_to_finish(fake: FakeKube) -> None:
    asyncio.run(keeper(fake).tick())
    fake.pods[NAME]["metadata"]["deletionTimestamp"] = "2099-01-01T00:00:00Z"
    fake.script.phases = ["Failed"]
    assert asyncio.run(keeper(fake).tick()) is False and fake.deleted == []


def test_the_annotation_names_the_spec_and_another_image_names_another(fake: FakeKube) -> None:
    asyncio.run(keeper(fake).tick())
    asyncio.run(keeper(fake, "mcr.example/browser@sha256:" + "d" * 64).tick())
    first = fake.created[0]["metadata"]["annotations"][SPEC_ANNOTATION]
    assert len(first) == 16 and fake.deleted == [NAME]


class Stop(Exception):
    pass


def test_run_keeps_going_after_the_api_fails_and_sleeps_the_tick(fake: FakeKube, caplog: pytest.LogCaptureFixture) -> None:
    slept: list[float] = []
    calls: list[str] = []

    def refuse(request: Any) -> int | None:
        calls.append(request.method)
        return 500 if len(calls) == 1 else None

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        if len(slept) == 3:
            raise Stop

    fake.fail = refuse
    pod = WarmPod(fake.api(), "ashley-sandbox", "gvisor", IMAGE, PREFIX, SHOOTER, CONFIG, sleep=sleep)
    with caplog.at_level(logging.INFO, logger="ashley.looks"), pytest.raises(Stop):
        asyncio.run(pod.run())
    assert slept == [CONFIG.warm_tick_s] * 3
    assert events(caplog, "looks.warm_failed")
    assert len(fake.created) == 1


def test_after_it_deletes_a_pod_it_looks_again_soon(fake: FakeKube) -> None:
    asyncio.run(keeper(fake).tick())
    fake.script.phases = ["Failed"]
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        if len(slept) == 2:
            raise Stop

    pod = WarmPod(fake.api(), "ashley-sandbox", "gvisor", IMAGE, PREFIX, SHOOTER, CONFIG, sleep=sleep)
    with pytest.raises(Stop):
        asyncio.run(pod.run())
    assert slept == [RECHECK_S, CONFIG.warm_tick_s] and len(fake.created) == 2
