"""The Kubernetes looker against a fake API (`sandbox_support.FakeKube`): the pod it asks for has gVisor, no token, a
deadline, limits, a pinned image and the page's address in its environment alone; the picture comes from the pod's log,
checked; and the pod is deleted however the look ends."""

import asyncio
import dataclasses
import base64
import json
from pathlib import Path
from typing import Any

import pytest
from ashley.looks import config, links
from ashley.looks.kubernetes import FAILED, MARK, SHOOTER, KubernetesLooker, picture
from ashley.looks.looker import LookUnavailable, Target
from sandbox_support import Clock, FakeKube, Script

CONFIG = config.load()
IMAGE = "mcr.example/browser@sha256:" + "b" * 64
KEY = b"k" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"p" * 30
TARGET = Target(household_id=3, person_id=5, bench_id=9, piece_id=None)
LINE = MARK + base64.b64encode(JPEG).decode()


def looker(fake: FakeKube, clock: Clock | None = None) -> KubernetesLooker:
    clock = clock or Clock()
    return KubernetesLooker(fake.api(), "ashley-sandbox", "gvisor", IMAGE, "http://ashley.test:8080", lambda: KEY, CONFIG,
                            sleep=clock.sleep, clock=clock, wall=lambda: 1000.0)


def looked(fake: FakeKube) -> bytes:
    return asyncio.run(looker(fake).look("look-a1", TARGET)).data


@pytest.fixture
def fake(tmp_path: Path) -> FakeKube:
    return FakeKube(tmp_path / "token", Script(log=LINE))


def spec_of(fake: FakeKube) -> dict[str, Any]:
    assert len(fake.created) == 1
    return fake.created[0]["spec"]


def test_the_picture_is_the_one_the_pod_printed_and_the_pod_is_deleted(fake: FakeKube) -> None:
    assert looked(fake) == JPEG
    assert fake.deleted == ["look-a1"] and not fake.pods


def test_the_pod_runs_the_pinned_browser_image_under_gvisor_with_no_token_and_a_deadline(fake: FakeKube) -> None:
    looked(fake)
    spec = spec_of(fake)
    container = spec["containers"][0]
    assert spec["runtimeClassName"] == "gvisor" and fake.created[0]["metadata"]["namespace"] == "ashley-sandbox"
    assert spec["automountServiceAccountToken"] is False and spec["restartPolicy"] == "Never"
    assert spec["hostNetwork"] is False and spec["enableServiceLinks"] is False
    assert spec["activeDeadlineSeconds"] == CONFIG.pod_deadline_s
    assert container["image"] == IMAGE and container["command"][-1] == SHOOTER
    storage = f"{CONFIG.ephemeral_mib}Mi"
    assert container["resources"]["limits"] == {"cpu": CONFIG.cpu, "memory": CONFIG.memory, "ephemeral-storage": storage}
    assert container["resources"]["requests"]["ephemeral-storage"] == storage
    home = next(v for v in spec["volumes"] if v["name"] == "home")
    assert home["emptyDir"]["sizeLimit"] == f"{CONFIG.home_mib}Mi"
    env = {e["name"]: e["value"] for e in container["env"]}
    assert env["TMPDIR"] == env["HOME"] == "/home/look"
    context = container["securityContext"]
    assert context["runAsNonRoot"] is True and context["readOnlyRootFilesystem"] is True
    assert context["allowPrivilegeEscalation"] is False and context["capabilities"] == {"drop": ["ALL"]}
    assert fake.created[0]["metadata"]["labels"] == {"ashley.yggdrasil.pub/look": "true"}


def test_the_pods_page_link_names_the_target_and_is_in_the_environment_alone(fake: FakeKube) -> None:
    looked(fake)
    env = {e["name"]: e["value"] for e in spec_of(fake)["containers"][0]["env"]}
    prefix = "http://ashley.test:8080" + links.PAGE
    assert env["ASHLEY_LOOK_URL"].startswith(prefix)
    grant = links.check(KEY, env["ASHLEY_LOOK_URL"][len(prefix):], now=1000.0)
    assert grant == links.Grant(3, 5, 9, None, 1000 + CONFIG.link_ttl_s)
    assert json.loads(env["ASHLEY_LOOK_LIMITS"])["max_bytes"] == CONFIG.max_image_bytes
    assert prefix not in json.dumps(spec_of(fake)["containers"][0]["command"])


def test_a_view_rides_the_pages_address_as_a_query_beside_a_token_that_still_checks(fake: FakeKube) -> None:
    asyncio.run(looker(fake).look("look-a1", dataclasses.replace(TARGET, piece_id=4, view="top")))
    address = {e["name"]: e["value"] for e in spec_of(fake)["containers"][0]["env"]}["ASHLEY_LOOK_URL"]
    path, _, query = address.partition("?")
    assert query == "view=top"
    grant = links.check(KEY, path[len("http://ashley.test:8080" + links.PAGE):], now=1000.0)
    assert grant is not None and grant.piece_id == 4


@pytest.mark.parametrize("text, reason", [
    (FAILED + "not_ready\n", "not_ready"), ("", "no_picture"), ("chatter\n", "no_picture"),
    (MARK + "!!notbase64\n", "bad_picture"), (MARK + base64.b64encode(b"GIF89a").decode() + "\n", "bad_picture")])
def test_what_the_pod_printed_that_is_not_a_picture_is_refused_with_its_reason(fake: FakeKube, text: str,
                                                                               reason: str) -> None:
    fake.script = Script(log=text)
    with pytest.raises(LookUnavailable, match=reason):
        looked(fake)
    assert fake.deleted == ["look-a1"]


def test_the_last_picture_line_wins_and_a_line_the_page_forged_before_it_does_not() -> None:
    other = MARK + base64.b64encode(b"\xff\xd8\xff-first").decode()
    assert picture(other + "\n" + LINE + "\n").data == JPEG


def test_a_pod_that_never_leaves_pending_is_deleted_and_unavailable(fake: FakeKube) -> None:
    fake.script = Script(phases=["Pending"], log=LINE)
    with pytest.raises(LookUnavailable, match="never_ran"):
        looked(fake)
    assert fake.deleted == ["look-a1"]


def test_a_refused_pod_is_unavailable_and_deleted(fake: FakeKube) -> None:
    fake.fail = lambda request: 403 if request.method == "POST" else None
    with pytest.raises(LookUnavailable, match="http 403"):
        looked(fake)


def test_a_look_pod_a_stopped_app_left_behind_is_swept_but_not_a_fresh_one_nor_a_code_run(fake: FakeKube) -> None:
    for name, created, label in (("look-old", "2000-01-01T00:00:00Z", "look"), ("look-new", "2099-01-01T00:00:00Z", "look")):
        fake.pods[name] = {"metadata": {"name": name, "creationTimestamp": created,
                                        "labels": {"ashley.yggdrasil.pub/" + label: "true"}}}
    looked(fake)
    assert "look-old" in fake.deleted and "look-new" not in fake.deleted


def test_the_log_names_the_pod_and_outcome_and_never_the_link_or_the_picture(fake: FakeKube,
                                                                              caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO", logger="ashley.looks")
    looked(fake)
    text = "\n".join(f"{r.getMessage()} {getattr(r, 'fields', {})}" for r in caplog.records)
    assert "looks.pod" in text and "'pod': 'look-a1'" in text and "'outcome': 'drawn'" in text
    assert "/look/" not in text and LINE[len(MARK):] not in text
