"""A detector event the household chose (`speak_on`) becomes her own turn through the wake path: a ring stored as one
`detection` wake, then told on a screen's thread with her look at the recording the detector captured as the picture in
her first step, and said where the screens are. A class outside the list, a camera off the list and a detection told
twice make no second turn; a recording that has not appeared leaves the wake due until the wait is over and then she is
told she could not see; every person of the household in their quiet hours holds it; no log names a camera or a title.
Home Assistant, the house's recordings, Postgres and the real turn loop are real; the model is scripted."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import timedelta

import pytest
from files_support import sync
from ashley import services
from ashley.cameras.detection_settings import DetectionSettings, load
from ashley.cameras.model import Detection
from ashley.channels.kiosk import detected
from ashley.channels.outbox import Outbox
from ashley.channels.postgres_outbox import PostgresOutbox
from ashley.channels.wake import runner
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.conversations.postgres import PostgresConversations
from ashley.conversations.postgres_inflight import PostgresInFlight
from ashley.files.memory import MemoryStore
from ashley.files.store import ObjectStore
from ashley.home_assistant.house import Event, Snapshot
from ashley.inference.inference import Inference
from ashley.inference.model import Message, ToolResults
from ashley.inference.reply import Reply
from ashley.initiative.initiative import Initiative
from ashley.looks.looks import Looks
from ashley.looks.postgres import PostgresLooks
from ashley.people.model import Household, Person, QuietHours
from ashley.people.people import People
from ashley.senses.postgres_wakes import PostgresWakes
from ashley.senses.wakes import DetectionWake, Wakes
from ashley.tools.tools import Tools
from bench_reacts_support import OnePerson
from contract.conversations_support import POLICY, ascalar
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from initiative_support import speaking
from test_camera_detections import BELL, HALL_BELL, MOTION, SEEN, World, outcomes, settled, world
from test_camera_port import HALL, PORCH
from test_camera_recordings import GREEN, RED, gif
from wake_support import Model, Switchboard

SAYS = Reply(spoken="Someone is at the door.", text="Someone is at the door.", says="reply")
SPEAKING = DetectionSettings(frozenset({"ring"}), 30, 86400, 60, frozenset({"ring"}), 60)
PREVIEW = gif((RED, GREEN))
TITLE = "Doorbell @ 2026-11-21 10:00:00"


@dataclass
class Spoken:
    w: World
    model: Model

    def recording(self, camera: str, name: str) -> Event:
        """A new newest recording of the camera, whose preview is a picture."""
        event = Event(f"media-source://nest/d/{name}", TITLE)
        house = self.w.house
        house.captured[camera] = [event, *house.captured.get(camera, [])]
        house.previews = {**house.previews, (camera, event.id): Snapshot(PREVIEW, "image/gif")}
        return event

    async def wakes(self) -> int:
        return int(await ascalar(self.w.url, "SELECT count(*) FROM wakes WHERE kind = 'detection'"))

    async def outcome(self) -> str | None:
        return await ascalar(self.w.url, "SELECT outcome FROM wakes WHERE kind = 'detection'")

    async def outbox(self) -> int:
        return int(await ascalar(self.w.url, "SELECT count(*) FROM outbox"))

    async def age(self, seconds: float) -> None:
        await ascalar(self.w.url, "WITH u AS (UPDATE wakes SET due_at = now() - make_interval(secs => %s) "
                                           "RETURNING 1) SELECT count(*) FROM u", (seconds,))

    def seen_in(self, prompt_index: int = 0) -> int:
        """How many pictures the model was shown in its steps' tool results."""
        return sum(len(r.images) for e in self.model.prompts[prompt_index].messages if isinstance(e, ToolResults)
                   for r in e.results)

    def note(self) -> str:
        last = [m for m in self.model.prompts[0].messages if isinstance(m, Message)][-1]
        return last.text


@asynccontextmanager
async def spoken(url: str, quiet: tuple[QuietHours | None, ...] = (None,)) -> AsyncGenerator[Spoken]:
    async with world(url) as w:
        db = w.database
        model = Model()
        ann = int(await ascalar(w.url, "SELECT id FROM people WHERE household_id = %s", (w.home,)))
        people = tuple(Person(ann if n == 0 else 900 + n, w.home, f"Person {n}", quiet=q) for n, q in enumerate(quiet))
        registered = (
            (People, OnePerson(Household(w.home, "home", "America/Denver", "", people))),
            (Conversations, PostgresConversations(db, POLICY)), (InFlight, PostgresInFlight(db, POLICY, 60.0)),
            (Outbox, PostgresOutbox(db, 600.0, POLICY)), (Tools, Switchboard()), (Inference, model),
            (Initiative, speaking()), (Wakes, PostgresWakes(db)), (ObjectStore, MemoryStore()), (Looks, PostgresLooks(db)))
        for interface, service in registered:
            services.register(interface, service)
        try:
            yield Spoken(w, model)
        finally:
            for interface, _ in registered:
                services.unregister(interface)


@sync
async def test_a_ring_is_one_wake_and_one_turn_that_begins_with_her_look_at_the_new_recording_and_is_said_on_the_screen(
        db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    async with spoken(db_url) as s:
        w = s.w
        s.recording(PORCH, "old")
        await w.tick(SPEAKING)
        await w.ring(BELL, SEEN)
        assert await settled(caplog, 1) == ["shown"] and await s.wakes() == 1
        s.recording(PORCH, "new")
        s.model.script = [SAYS]
        assert await runner.sweep() == 1
        assert await s.outcome() == "turn" and s.seen_in() == 1
        assert "`ring`" in s.note() and "do not guess" in s.note()
        assert await s.outbox() == 1
        thread = await ascalar(w.url, "SELECT thread FROM outbox")
        assert thread == f"device:{w.kiosk}"
        assert await runner.sweep() == 0
        text = "\n".join(r.getMessage() for r in caplog.records)
        assert PORCH not in text and TITLE not in text and "zq_porch" not in text


@sync
async def test_a_class_outside_speak_on_makes_no_wake_and_one_only_spoken_on_makes_a_wake_and_no_feed(
        db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    async with spoken(db_url) as s:
        spoken_only = replace(SPEAKING, show_feed_on=frozenset(), speak_on=frozenset({"ring", "camera_person"}))
        await s.w.tick(spoken_only)
        await s.w.ring(MOTION, SEEN, "camera_motion")
        assert await settled(caplog, 1) == ["ignored"] and await s.wakes() == 0
        await s.w.ring(MOTION, SEEN + timedelta(seconds=40), "camera_person")
        assert await settled(caplog, 2) == ["ignored", "told"]
        assert await s.wakes() == 1 and await s.w.shown() is None


@sync
async def test_a_detection_told_twice_is_one_wake_and_one_turn(db_url: str) -> None:
    async with spoken(db_url) as s:
        seen = Detection(PORCH, "ring", SEEN)
        first = await detected.act(s.w.home, seen, SPEAKING, SEEN)
        second = await detected.act(s.w.home, seen, SPEAKING, SEEN)
        assert (first, second) == ("shown", "duplicate") and await s.wakes() == 1
        s.recording(PORCH, "new")
        s.model.script = [SAYS]
        assert await runner.sweep() == 1 and len(s.model.prompts) == 1


@sync
async def test_a_second_ring_inside_the_cameras_gap_makes_no_second_wake(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    async with spoken(db_url) as s:
        await s.w.tick(SPEAKING)
        await s.w.ring(BELL, SEEN)
        await s.w.ring(BELL, SEEN + timedelta(seconds=10))
        assert await settled(caplog, 2) == ["shown", "too_soon"] and await s.wakes() == 1


@sync
async def test_a_recording_that_has_not_appeared_leaves_the_wake_due_then_she_speaks_without_a_picture(
        db_url: str) -> None:
    async with spoken(db_url) as s:
        s.recording(PORCH, "old")
        await detected.act(s.w.home, Detection(PORCH, "ring", SEEN), SPEAKING, SEEN)
        assert await runner.sweep() == 1 and await s.outcome() is None and s.model.prompts == []
        await s.age(SPEAKING.look_wait_s - 5)
        assert await runner.sweep() == 1 and await s.outcome() is None
        await s.age(SPEAKING.look_wait_s + 5)
        s.model.script = [SAYS]
        assert await runner.sweep() == 1
        assert await s.outcome() == "turn" and s.seen_in() == 0


@sync
async def test_recordings_unreadable_at_the_event_mean_no_recording_is_ever_taken_for_its_own(db_url: str) -> None:
    async with spoken(db_url) as s:
        s.recording(PORCH, "old")
        await services.get(Wakes).detected(DetectionWake(s.w.home, PORCH, "ring", SEEN, None))
        s.model.script = [SAYS]
        assert await runner.sweep() == 1 and await s.outcome() == "turn" and s.seen_in() == 0


@sync
async def test_every_person_in_their_quiet_hours_holds_it_and_one_awake_person_does_not(db_url: str) -> None:
    asleep = QuietHours(9, 11, "UTC")
    async with spoken(db_url, (asleep,)) as s:
        s.recording(PORCH, "old")
        await detected.act(s.w.home, Detection(PORCH, "ring", SEEN), SPEAKING, SEEN)
        s.recording(PORCH, "new")
        s.model.script = [SAYS]
        assert await runner.sweep() == 1 and await s.outcome() == "turn" and await s.outbox() == 0
    async with spoken(db_url, (asleep, None)) as s:
        s.recording(PORCH, "old")
        await detected.act(s.w.home, Detection(PORCH, "ring", SEEN), SPEAKING, SEEN)
        s.recording(PORCH, "new")
        s.model.script = [SAYS]
        assert await runner.sweep() == 1 and await s.outbox() == 1


@sync
async def test_a_camera_off_the_list_is_not_followed_and_one_dropped_after_the_event_ends_the_wake_unspoken(
        db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    async with spoken(db_url) as s:
        s.w.settings.looks = (PORCH,)
        await s.w.tick(SPEAKING)
        await s.w.ring(HALL_BELL, SEEN)
        await asyncio.sleep(0.05)
        assert await s.wakes() == 0 and outcomes(caplog) == []
        s.recording(PORCH, "old")
        await detected.act(s.w.home, Detection(PORCH, "ring", SEEN), SPEAKING, SEEN)
        s.w.settings.looks = (HALL,)
        assert await runner.sweep() == 1 and await s.outcome() == "cancelled" and s.model.prompts == []


@sync
async def test_a_wake_past_its_use_expires_untold_and_the_inbound_names_no_person(db_url: str) -> None:
    async with spoken(db_url) as s:
        await detected.act(s.w.home, Detection(PORCH, "ring", SEEN), SPEAKING, SEEN)
        await s.age(10_000)
        assert await runner.sweep() == 1 and await s.outcome() == "expired" and s.model.prompts == []


def test_the_shipped_settings_speak_on_a_ring() -> None:
    got = load()
    assert "ring" in got.speak_on and got.look_wait_s > 0
