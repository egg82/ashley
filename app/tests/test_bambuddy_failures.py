"""A printer's failed print as a camera detection, over a fake Bambuddy built from its documented and live-read shapes
(`ArchiveResponse`: `status`, `completed_at` in UTC with no zone): a print archive that ended `failed` is one detection of
the class `failed`, the printer's snapshot is what she looks at as she tells it, and the same failure read on every pass,
a printer the household has not listed, a class not in `speak_on`, a print that was cancelled or finished and a failure
from before the lookback each make nothing more."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import bambuddy_support
import pytest
from files_support import sync
from ashley import services
from ashley.bambuddy.cameras import NAME, BambuddyCameras
from ashley.bambuddy.client import Bambuddy
from ashley.cameras.cameras import Cameras
from ashley.cameras.detection_settings import DetectionSettings, load
from ashley.cameras.routed import RoutedCameras
from ashley.connections.connections import Connections
from ashley.connections.settings_read import SettingsReader
from ashley.channels.wake import runner
from bambuddy_support import FakeBambuddy, archive, held, printer
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from look_pictures_support import corner
from test_bambuddy_cameras import Settings, named
from test_camera_detections import outcomes, settled
from test_detection_speaks import SAYS, SPEAKING, Spoken, spoken

SHED, LOFT = "printer.1", "printer.2"
PRINTING = replace(SPEAKING, show_feed_on=frozenset(), speak_on=frozenset({"failed"}), look_now_on=frozenset({"failed"}))


def ended(status: str, ago_s: float, id_: int = 31, printer_id: int = 1) -> dict[str, object]:
    """A print archive that ended `ago_s` ago, as Bambuddy writes it: UTC, no zone."""
    at = (datetime.now(UTC) - timedelta(seconds=ago_s)).replace(tzinfo=None).isoformat()
    return {**archive(id_, printer_id, "Benchy", timelapse=False), "status": status, "completed_at": at}


@asynccontextmanager
async def printers(url: str, monkeypatch: pytest.MonkeyPatch, archives: list[dict[str, object]],
                   listed: tuple[str, ...] = (SHED,)) -> AsyncGenerator[tuple[Spoken, FakeBambuddy]]:
    monkeypatch.setattr(bambuddy_support, "JPEG", corner((64, 48)))
    async with spoken(url) as s:
        fake = FakeBambuddy()
        fake.answers["/api/v1/printers/"] = [printer(1, "Shed X1C"), printer(2, "Loft P1S")]
        fake.archives = archives
        services.register(Connections, held(s.w.home))
        services.register(Bambuddy, fake.client())
        services.register(SettingsReader, Settings({1: named(*listed)}))
        services.register(Cameras, RoutedCameras({NAME: BambuddyCameras()}, 3))
        yield s, fake


def test_the_shipped_settings_speak_on_a_failed_print_and_look_at_the_printer_as_it_is_now() -> None:
    shipped = load()
    assert "failed" in shipped.speak_on and "failed" in shipped.look_now_on and "failed" not in shipped.show_feed_on


@sync
async def test_a_failed_print_is_one_detection_told_with_the_printers_snapshot_as_the_picture_she_sees(
        db_url: str, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    caplog.set_level(logging.INFO)
    async with printers(db_url, monkeypatch, [ended("failed", 20)]) as (s, fake):
        await s.w.tick(PRINTING)
        assert await settled(caplog, 1) == ["told"] and await s.wakes() == 1
        s.model.script = [SAYS]
        assert await runner.sweep() == 1
        assert await s.outcome() == "turn" and s.seen_in() == 1 and "`failed`" in s.note()
        assert [p for p, _, _ in fake.seen if "snapshot" in p] == ["/api/v1/printers/1/camera/snapshot"]
        assert await s.outbox() == 1
        text = "\n".join(r.getMessage() for r in caplog.records)
        assert "Shed" not in text and "Benchy" not in text


@sync
async def test_the_same_failure_read_on_every_pass_is_one_detection_and_one_wake(
        db_url: str, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    caplog.set_level(logging.INFO)
    async with printers(db_url, monkeypatch, [ended("failed", 20)]) as (s, _):
        await s.w.tick(PRINTING)
        await s.w.tick(PRINTING)
        assert await settled(caplog, 2) == ["told", "duplicate"] and await s.wakes() == 1


@sync
async def test_a_printer_off_the_households_list_is_not_followed(
        db_url: str, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    caplog.set_level(logging.INFO)
    failed = [ended("failed", 20, 41, 2)]
    async with printers(db_url, monkeypatch, failed) as (s, fake):
        counts = await s.w.tick(PRINTING)
        assert counts["followed"] == 1 and outcomes(caplog) == [] and await s.wakes() == 0
        assert [q["printer_id"] for p, q, _ in fake.seen if p == "/api/v1/archives/"] == ["1"]


@sync
async def test_a_class_not_in_speak_on_makes_no_wake(
        db_url: str, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    caplog.set_level(logging.INFO)
    async with printers(db_url, monkeypatch, [ended("failed", 20)]) as (s, _):
        quiet: DetectionSettings = replace(PRINTING, speak_on=frozenset({"ring"}))
        await s.w.tick(quiet)
        assert await settled(caplog, 1) == ["ignored"] and await s.wakes() == 0


@sync
async def test_only_a_print_that_failed_within_the_lookback_is_a_detection(
        db_url: str, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    caplog.set_level(logging.INFO)
    lookback = load().failure_lookback_s
    archives = [ended("cancelled", 20, 31), ended("completed", 20, 32), ended("failed", lookback + 60, 33),
                {**ended("failed", 20, 34), "completed_at": None}]
    async with printers(db_url, monkeypatch, archives) as (s, _):
        await s.w.tick(PRINTING)
        assert outcomes(caplog) == [] and await s.wakes() == 0


@sync
async def test_a_failure_that_ended_across_a_gap_longer_than_three_passes_is_still_told_once(
        db_url: str, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    caplog.set_level(logging.INFO)
    gap = 10 * load().tick_s
    assert gap < load().failure_lookback_s
    async with printers(db_url, monkeypatch, [ended("failed", gap)]) as (s, _):
        await s.w.tick(PRINTING)
        await s.w.tick(PRINTING)
        assert await settled(caplog, 2) == ["told", "duplicate"] and await s.wakes() == 1
