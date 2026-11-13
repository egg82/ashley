"""The singleton (`ashley.mail.proton_bridge_job`) on a real record and a fake Kubernetes API: it raises the epoch and
makes the pod after the older epoch's fence, adopts a heard pod of its site without a restart, retires one of the other
site, replaces an ended pod after `restart_s`, makes a new epoch when the token Secret is gone, and survives a failing API."""

import asyncio
import base64
import logging
from pathlib import Path

import psycopg
import pytest
from ashley.mail import config, proton_pod
from ashley.mail.proton_bridge import BridgeUnavailable, ProtonBridge
from ashley.mail.proton_bridge_job import BridgeKeeping
from ashley.mail.proton_bridge_postgres import token_sha256
from ashley.mail.proton_fence import Step
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from mail_bridge_support import NAMESPACE, BridgeKube, bridge_on, logged

pytestmark = pytest.mark.usefixtures("unwired")
CONFIG = config.load()
IMAGE = "registry.test/ashley-mail-bridge@sha256:" + "c" * 64
APP = "https://ashley.test"


class Sleeps:
    def __init__(self) -> None:
        self.slept: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.slept.append(seconds)


def keeping(bridge: ProtonBridge, kube: BridgeKube, site: str = "birch", sleeps: Sleeps | None = None) -> BridgeKeeping:
    return BridgeKeeping(bridge, kube.api(), NAMESPACE, IMAGE, APP, site, CONFIG, sleep=sleeps or Sleeps())


@pytest.fixture
def kube(tmp_path: Path) -> BridgeKube:
    return BridgeKube(tmp_path / "token")


def age(url: str, seconds: float) -> None:
    """The epoch's pod last showed life `seconds` ago."""
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("UPDATE proton_bridge SET heartbeat_at = now() - make_interval(secs => %s), "
                     "started_at = now() - make_interval(secs => %s)", (seconds, seconds))


def test_the_first_tick_raises_the_epoch_and_hands_the_token_to_a_secret_the_next_makes_a_pod_from(
        db_url: str, kube: BridgeKube) -> None:
    async def scenario() -> None:
        async with bridge_on(db_url) as bridge:
            job = keeping(bridge, kube)
            assert (await job.tick()).step is Step.RAISE
            holder = await bridge.holder()
            assert (holder.epoch, holder.site, holder.pod) == (1, "birch", None) and not kube.pods
            token = kube.secrets["mail-bridge-1"]["data"]["token"]
            assert token and await bridge.authorize(1, base64.b64decode(token).decode()) == "ok"
            access = await bridge.keeper_access(1)
            data = kube.secrets["mail-bridge-1"]["data"]
            assert access is not None and access.token == base64.b64decode(token).decode()
            assert access.certificate == base64.b64decode(data["tls.crt"]).decode()
            assert (await job.tick()).step is Step.MAKE
            assert (await bridge.holder()).pod == "mail-bridge-1"
            pod = kube.pods["mail-bridge-1"]
            env = {e["name"]: e.get("value") or e["valueFrom"] for e in pod["spec"]["containers"][0]["env"]}
            assert env["BRIDGE_EPOCH"] == "1" and env["ASHLEY_URL"] == APP
            assert env["BRIDGE_TOKEN"] == {"secretKeyRef": {"name": "mail-bridge-1", "key": "token"}}
            assert pod["spec"]["containers"][0]["image"] == IMAGE and pod["spec"]["restartPolicy"] == "Never"
            assert pod["spec"]["containers"][0]["securityContext"]["readOnlyRootFilesystem"] is True

    asyncio.run(scenario())


def test_a_heard_pod_of_this_site_is_adopted_once_and_left_alone(db_url: str, kube: BridgeKube,
                                                                  caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with bridge_on(db_url) as bridge:
            await keeping(bridge, kube).tick()
            await keeping(bridge, kube).tick()
            assert await bridge.heartbeat(1, None)
            created = len(kube.calls)
            taker = keeping(bridge, kube)
            with caplog.at_level(logging.INFO, logger="ashley.mail"):
                assert [(await taker.tick()).step for _ in range(2)] == [Step.ADOPT, Step.ADOPT]
            assert (await bridge.holder()).epoch == 1 and list(kube.pods) == ["mail-bridge-1"]
            assert [e for e, _ in logged(caplog)].count("proton_bridge.adopted") == 1
            assert not any(c.startswith(("POST", "DELETE")) for c in kube.calls[created:])

    asyncio.run(scenario())


def test_a_pod_of_the_other_site_is_retired_and_the_new_pod_waits_out_its_fence(db_url: str, kube: BridgeKube,
                                                                                  caplog: pytest.LogCaptureFixture) -> None:
    needed = CONFIG.fence_s + CONFIG.fence_margin_s

    async def scenario() -> None:
        async with bridge_on(db_url) as bridge:
            other = await bridge.raise_epoch(0, "willow", token_sha256("old"))
            assert other is not None and await bridge.pod_started(other, "mail-bridge-1")
            assert await bridge.heartbeat(other, None)
            job = keeping(bridge, kube)
            with caplog.at_level(logging.INFO, logger="ashley.mail"):
                assert (await job.tick()).step is Step.RAISE
            assert ("proton_bridge.retired", {"epoch": 1, "site": "willow", "reason": "other_site"}) in logged(caplog)
            assert not await bridge.heartbeat(other, None)
            age(db_url, needed - 2)
            assert (await job.tick()).step is Step.WAIT and not kube.pods
            age(db_url, needed + 1)
            assert (await job.tick()).step is Step.MAKE and list(kube.pods) == ["mail-bridge-2"]

    asyncio.run(scenario())


def test_a_pod_running_another_image_is_retired_through_a_raised_epoch_and_the_new_pod_waits_out_its_fence(
        db_url: str, kube: BridgeKube, caplog: pytest.LogCaptureFixture) -> None:
    needed = CONFIG.fence_s + CONFIG.fence_margin_s

    async def scenario() -> None:
        async with bridge_on(db_url) as bridge:
            sleeps = Sleeps()
            old = BridgeKeeping(bridge, kube.api(), NAMESPACE, IMAGE.replace("c" * 64, "b" * 64), APP, "birch", CONFIG,
                                sleep=sleeps)
            await old.tick()
            await old.tick()
            assert await bridge.heartbeat(1, None)
            job = keeping(bridge, kube, sleeps=sleeps)
            with caplog.at_level(logging.INFO, logger="ashley.mail"):
                decision = await job.tick()
            assert (decision.step, decision.reason) == (Step.RAISE, "image")
            assert ("proton_bridge.retired", {"epoch": 1, "site": "birch", "reason": "image"}) in logged(caplog)
            assert not await bridge.heartbeat(1, None) and sleeps.slept == []
            assert "mail-bridge-1" not in kube.pods and "mail-bridge-1" not in kube.secrets
            age(db_url, needed - 2)
            assert (await job.tick()).step is Step.WAIT and not kube.pods
            age(db_url, needed + 1)
            assert (await job.tick()).step is Step.MAKE
            assert kube.pods["mail-bridge-2"]["spec"]["containers"][0]["image"] == IMAGE

    asyncio.run(scenario())


def test_a_pod_not_heard_within_the_fence_is_retired_and_deleted(db_url: str, kube: BridgeKube) -> None:
    async def scenario() -> None:
        async with bridge_on(db_url) as bridge:
            await keeping(bridge, kube).tick()
            await keeping(bridge, kube).tick()
            age(db_url, CONFIG.fence_s + 1)
            assert (await keeping(bridge, kube).tick()).step is Step.RAISE
            assert (await bridge.holder()).epoch == 2
            assert "mail-bridge-1" not in kube.pods and "mail-bridge-1" not in kube.secrets
            assert "mail-bridge-2" in kube.secrets

    asyncio.run(scenario())


def test_an_ended_pod_is_replaced_after_restart_s_without_waiting_out_the_fence(db_url: str, kube: BridgeKube) -> None:
    async def scenario() -> None:
        async with bridge_on(db_url) as bridge:
            sleeps = Sleeps()
            job = keeping(bridge, kube, sleeps=sleeps)
            await job.tick()
            await job.tick()
            assert await bridge.heartbeat(1, None)
            kube.phase("mail-bridge-1", "Failed")
            assert (await job.tick()).step is Step.REPLACE
            assert sleeps.slept == [CONFIG.restart_s]
            assert (await bridge.holder()).epoch == 2 and list(kube.pods) == ["mail-bridge-2"]
            assert list(kube.secrets) == ["mail-bridge-2"]

    asyncio.run(scenario())


def test_a_raised_epoch_whose_token_secret_is_gone_is_raised_again(db_url: str, kube: BridgeKube) -> None:
    async def scenario() -> None:
        async with bridge_on(db_url) as bridge:
            job = keeping(bridge, kube)
            await job.tick()
            del kube.secrets["mail-bridge-1"]
            await job.tick()
            assert (await bridge.holder()).epoch == 2 and not kube.pods and "mail-bridge-2" in kube.secrets

    asyncio.run(scenario())


def test_a_failing_api_is_logged_and_tried_again_at_the_next_tick(db_url: str, kube: BridgeKube,
                                                                   caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with bridge_on(db_url) as bridge:
            sleeps = Sleeps()

            async def stop_after_two(seconds: float) -> None:
                await sleeps(seconds)
                kube.broken = len(sleeps.slept) < 1
                if len(sleeps.slept) == 2:
                    raise asyncio.CancelledError

            job = BridgeKeeping(bridge, kube.api(), NAMESPACE, IMAGE, APP, "birch", CONFIG, sleep=stop_after_two)
            kube.broken = True
            with caplog.at_level(logging.WARNING, logger="ashley.mail"), pytest.raises(asyncio.CancelledError):
                await job.run()
            assert "proton_bridge.failed" in [e for e, _ in logged(caplog)]
            assert sleeps.slept == [CONFIG.tick_s, CONFIG.tick_s]

    asyncio.run(scenario())


def test_an_unreachable_record_is_logged_not_raised(kube: BridgeKube, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with bridge_on("postgresql://postgres:t@127.0.0.1:1/postgres", connect_timeout_s=0.1) as bridge:
            async def once(_: float) -> None:
                raise asyncio.CancelledError

            job = BridgeKeeping(bridge, kube.api(), NAMESPACE, IMAGE, APP, "birch", CONFIG, sleep=once)
            with caplog.at_level(logging.WARNING, logger="ashley.mail"), pytest.raises(asyncio.CancelledError):
                await job.run()
            assert "proton_bridge.failed" in [e for e, _ in logged(caplog)]
            with pytest.raises(BridgeUnavailable):
                await job.tick()

    asyncio.run(scenario())


def test_the_pod_spec_never_carries_the_token_and_its_secret_has_the_pods_name() -> None:
    manifest = proton_pod.manifest(7, IMAGE, APP, CONFIG)
    assert "token" not in str(manifest["spec"]).replace("secretKeyRef", "").replace('"key": "token"', "").replace(
        "'key': 'token'", "")
    assert manifest["metadata"]["name"] == proton_pod.pod_name(7) == "mail-bridge-7"
