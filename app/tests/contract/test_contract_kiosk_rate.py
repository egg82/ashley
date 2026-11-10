"""Blind contract tests for the hallway tablet's rate (messages and controls count, reads never do) and its logs."""

from typing import Any

import pytest
from ashley import logs
from ashley.channels.devices import DevicesUnavailable
from ashley.channels.model import Outbound
from kiosk_support import HOME, MARK, TOKEN, Kiosk, kiosk as kiosk, reads, writes
from web_chat_support import conversation, error_of, turn


EVIL = {"origin": "https://evil.test"}


# ---- the rate: messages and controls count, reads never do ---------------------------------------------------------

def test_a_message_and_a_control_each_count_once_against_the_device(kiosk: Kiosk) -> None:
    kiosk.post("/api/kiosk/messages")
    assert kiosk.devices.counted == [9]
    kiosk.post("/api/kiosk/controls/hall-light")
    assert kiosk.devices.counted == [9, 9]


def test_reads_never_count_however_many_there_are(kiosk: Kiosk) -> None:
    for _ in range(3):
        for path in reads():
            assert kiosk.get(path).status_code == 200
    kiosk.post("/api/kiosk/session", {"token": TOKEN}, token=None)
    assert kiosk.devices.counted == []


@pytest.mark.parametrize("path,body", writes())
def test_over_the_rate_is_429_rate_limited_and_does_nothing(kiosk: Kiosk, path: str, body: dict[str, Any]) -> None:
    kiosk.devices.over = True
    got = kiosk.post(path, body)
    assert got.status_code == 429 and error_of(got).code == "rate_limited"
    assert kiosk.loop.seen == [] and kiosk.tools.calls == []


def test_reads_still_answer_while_the_device_is_over_its_rate(kiosk: Kiosk) -> None:
    kiosk.devices.over = True
    assert all(kiosk.get(path).status_code == 200 for path in reads())


def test_a_refused_request_is_not_counted(kiosk: Kiosk) -> None:
    kiosk.post("/api/kiosk/messages", token=None)
    kiosk.post("/api/kiosk/messages", headers={"Cf-Connecting-IP": "203.0.113.9"})
    kiosk.post("/api/kiosk/messages", headers=EVIL)
    kiosk.post("/api/kiosk/messages", {"text": ""})
    assert kiosk.devices.counted == []


@pytest.mark.parametrize("path,body", writes())
def test_the_rate_store_down_is_503_and_does_nothing(kiosk: Kiosk, monkeypatch: pytest.MonkeyPatch, path: str,
                                                     body: dict[str, Any]) -> None:
    async def down(device_id: int) -> bool:
        raise DevicesUnavailable("down")
    monkeypatch.setattr(kiosk.devices, "allow", down)
    got = kiosk.post(path, body)
    assert got.status_code == 503 and error_of(got).code == "unavailable"
    assert kiosk.loop.seen == [] and kiosk.tools.calls == []


# ---- logs --------------------------------------------------------------------------------------------------------

def test_logs_carry_neither_the_token_nor_message_text_nor_what_a_tool_returned(kiosk: Kiosk,
                                                                                 capsys: pytest.CaptureFixture[str]
                                                                                 ) -> None:
    kiosk.loop.reply = Outbound(5, "text", f"reply {MARK}", False)
    kiosk.conversations.by_thread[(HOME, "device:9")] = conversation(31, (turn(1, "person", f"stored {MARK}"),))
    logs.setup()
    capsys.readouterr()
    kiosk.post("/api/kiosk/session", {"token": TOKEN}, token=None)
    kiosk.post("/api/kiosk/session", {"token": f"bad-{MARK}"}, token=None)
    kiosk.post("/api/kiosk/messages", {"text": f"asked {MARK}"})
    kiosk.post("/api/kiosk/controls/hall-light")
    kiosk.post("/api/kiosk/controls/lock-up")
    for path in reads():
        kiosk.get(path)
    kiosk.get("/api/kiosk/device", token=f"stale-{MARK}")
    seen = capsys.readouterr()
    out = seen.out + seen.err
    assert MARK not in out and TOKEN not in out
    assert "Hallway light" not in out and "Front door" not in out
