"""The warm Looker: a look goes to the warm pod and is answered by it; when that pod is busy, missing, unreachable or
broken the look is taken in a pod of its own as before, and a page that never drew is the answer, not a reason to try
again."""

import asyncio
import base64
import json
import logging
from pathlib import Path
from typing import Any

import httpx2
import pytest
from ashley.looks import config, links
from ashley.looks.kubernetes import FAILED, MARK, KubernetesLooker
from ashley.looks.looker import LookUnavailable, Target
from ashley.looks.warm_looker import WarmLooker
from ashley.looks.warm_pod import WarmPod
from sandbox_support import Clock, FakeKube, Script
from warm_look_support import events

CONFIG = config.load()
IMAGE = "mcr.example/browser@sha256:" + "b" * 64
KEY = b"k" * 32
APP = "http://ashley.test:8080"
WARM = "http://ashley-look-warm.ashley-sandbox.svc:8080"
WARM_JPEG = b"\xff\xd8\xff\xe0" + b"w" * 30
COLD_JPEG = b"\xff\xd8\xff\xe0" + b"c" * 30
TARGET = Target(household_id=3, person_id=5, bench_id=9, piece_id=None)


def line(jpeg: bytes) -> str:
    return MARK + base64.b64encode(jpeg).decode()


class Warm:
    """The warm pod's Service: answers each call with `reply`, or raises `error`, and keeps what it was sent."""

    def __init__(self, reply: httpx2.Response | None = None, error: Exception | None = None) -> None:
        self.reply = reply or httpx2.Response(200, text=line(WARM_JPEG))
        self.error = error
        self.sent: list[httpx2.Request] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.sent.append(request)
        if self.error is not None:
            raise self.error
        return self.reply


def looker(tmp_path: Path, warm: Warm) -> tuple[WarmLooker, FakeKube]:
    fake = FakeKube(tmp_path / "token", Script(log=line(COLD_JPEG)))
    clock = Clock()
    api = fake.api()
    cold = KubernetesLooker(api, "ashley-sandbox", "gvisor", IMAGE, APP, KEY, CONFIG, sleep=clock.sleep, clock=clock,
                            wall=lambda: 1000.0)
    keeper = WarmPod(api, "ashley-sandbox", "gvisor", IMAGE, APP + links.PAGE, "", CONFIG)
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(warm.handle))
    return WarmLooker(cold, keeper, http, WARM, CONFIG, clock=clock), fake


def look(tmp_path: Path, warm: Warm) -> tuple[bytes, FakeKube]:
    wl, fake = looker(tmp_path, warm)
    return asyncio.run(wl.look("look-a1", TARGET)).data, fake


def test_a_look_is_drawn_by_the_warm_pod_and_starts_no_pod(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    warm = Warm()
    with caplog.at_level(logging.INFO, logger="ashley.looks"):
        data, fake = look(tmp_path, warm)
    assert data == WARM_JPEG and fake.created == [] and fake.deleted == []
    assert events(caplog, "looks.warm")[0]["outcome"] == "drawn" and events(caplog, "looks.warm")[0]["bytes"] == len(data)


def test_the_warm_pod_is_sent_the_page_of_this_target_with_a_link_good_for_the_ttl(tmp_path: Path) -> None:
    warm = Warm()
    look(tmp_path, warm)
    (request,) = warm.sent
    assert str(request.url) == WARM + "/look"
    url: str = json.loads(request.content)["url"]
    prefix = APP + links.PAGE
    assert url.startswith(prefix)
    assert links.check(KEY, url[len(prefix):], now=1000.0) == links.Grant(3, 5, 9, None, 1000 + CONFIG.link_ttl_s)
    assert request.extensions["timeout"]["connect"] == CONFIG.warm_connect_s


@pytest.mark.parametrize("warm, why", [
    (Warm(httpx2.Response(503)), "busy"),
    (Warm(httpx2.Response(500)), "http_500"),
    (Warm(httpx2.Response(504)), "http_504"),
    (Warm(error=httpx2.ConnectError("no route")), "ConnectError"),
    (Warm(error=httpx2.ReadTimeout("slow")), "ReadTimeout"),
    (Warm(httpx2.Response(200, text=FAILED + "browser")), "browser"),
    (Warm(httpx2.Response(200, text="")), "no_picture"),
    (Warm(httpx2.Response(200, text=MARK + "!!!")), "bad_picture"),
])
def test_a_warm_pod_that_cannot_take_the_look_sends_it_to_a_pod_of_its_own(tmp_path: Path, warm: Warm, why: str,
                                                                           caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="ashley.looks"):
        data, fake = look(tmp_path, warm)
    assert data == COLD_JPEG and len(fake.created) == 1 and fake.deleted == ["look-a1"]
    assert [e["reason"] for e in events(caplog, "looks.warm_fallback")] == [why]


@pytest.mark.parametrize("reason", ["not_ready", "too_large"])
def test_a_page_that_would_not_draw_is_the_answer_and_costs_no_second_try(tmp_path: Path, reason: str,
                                                                          caplog: pytest.LogCaptureFixture) -> None:
    warm = Warm(httpx2.Response(200, text=FAILED + reason))
    wl, fake = looker(tmp_path, warm)
    with caplog.at_level(logging.INFO, logger="ashley.looks"), pytest.raises(LookUnavailable, match=reason):
        asyncio.run(wl.look("look-a1", TARGET))
    assert fake.created == [] and len(warm.sent) == 1
    assert events(caplog, "looks.warm")[0]["outcome"] == "failed"


def test_a_cold_look_that_fails_after_a_fallback_still_raises(tmp_path: Path) -> None:
    wl, fake = looker(tmp_path, Warm(httpx2.Response(503)))
    fake.script.log = FAILED + "not_ready"
    with pytest.raises(LookUnavailable):
        asyncio.run(wl.look("look-a1", TARGET))
    assert fake.deleted == ["look-a1"]


def test_the_warm_pod_is_never_swept_as_a_stray_look_pod(tmp_path: Path) -> None:
    wl, fake = looker(tmp_path, Warm(httpx2.Response(503)))
    seen: list[Any] = []

    def spy(request: httpx2.Request) -> int | None:
        if request.method == "GET" and request.url.path.endswith("/pods"):
            seen.append(request.url.params["labelSelector"])
        return None

    fake.fail = spy
    asyncio.run(wl.look("look-a1", TARGET))
    assert seen == ["ashley.yggdrasil.pub/look=true,ashley.yggdrasil.pub/look-warm!=true"]
