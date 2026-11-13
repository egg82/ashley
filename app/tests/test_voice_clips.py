"""Clips in Postgres and `GET /api/voice/clips/{token}`: a token fetches its text once stored, only its SHA-256 is
kept, the write sweeps clips past the retention and keeps the rest, an expired or unknown token is 404, an unreachable
store or voice is 503, and the audio streams with the speech's media type and a `voice.clip` line of ids and timings."""

import asyncio
import hashlib
from collections.abc import Generator

import psycopg
import pytest
from ashley import logs, services
from ashley.api import voice_clips
from ashley.api.models import ErrorResponse
from ashley.channels.voice.clips import Clip, Clips, ClipsUnavailable, NewClip
from ashley.channels.voice.postgres_clips import PostgresClips
from ashley.db.pool import PoolDatabase
from ashley.inference.inference import Inference, InferenceUnavailable
from contract.conversations_support import db_url as db_url, events, household
from contract.conversations_support import migrated_template as migrated_template, scalar
from fastapi import FastAPI
from fastapi.testclient import TestClient
from voice_support import FakeSpeech, satellite_row

RETENTION_S = 120


@pytest.fixture(autouse=True)
def unwired() -> Generator[None]:
    yield
    services.unregister(Inference)
    services.unregister(Clips)


async def opened(url: str) -> tuple[PoolDatabase, PostgresClips]:
    database = PoolDatabase(url)
    await database.open()
    return database, PostgresClips(database, RETENTION_S)


def add(url: str, device_id: int, body: str, since_wake_ms: int = 1500) -> NewClip:
    made: list[NewClip] = []

    async def scenario() -> None:
        database, clips = await opened(url)
        try:
            made.append(await clips.add(device_id, body, since_wake_ms))
        finally:
            await database.close()

    asyncio.run(scenario())
    return made[0]


def get(url: str, token: str) -> Clip | None:
    found: list[Clip | None] = []

    async def scenario() -> None:
        database, clips = await opened(url)
        try:
            found.append(await clips.get(token))
        finally:
            await database.close()

    asyncio.run(scenario())
    return found[0]


def age(url: str, clip_id: int, seconds: int) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("UPDATE voice_clips SET created_at = clock_timestamp() - make_interval(secs => %s), "
                     "woke_at = clock_timestamp() - make_interval(secs => %s) WHERE id = %s",
                     (seconds, seconds, clip_id))


def test_a_stored_clip_is_fetched_by_its_token_which_is_kept_only_as_its_hash(db_url: str) -> None:
    satellite = satellite_row(db_url, household(db_url))
    made = add(db_url, satellite.device.id, "It is noon.", since_wake_ms=1500)
    got = get(db_url, made.token)
    assert got is not None and (got.id, got.device_id, got.body) == (made.id, satellite.device.id, "It is noon.")
    assert 1500 <= got.since_wake_ms < 10_000
    stored = scalar(db_url, "SELECT token_sha256 FROM voice_clips WHERE id = %s", (made.id,))
    assert bytes(stored) == hashlib.sha256(made.token.encode()).digest()
    assert scalar(db_url, "SELECT household_id FROM voice_clips WHERE id = %s", (made.id,)) == \
        satellite.device.household_id
    assert get(db_url, made.token[:-1]) is None and get(db_url, "") is None


def test_a_write_sweeps_clips_past_the_retention_and_keeps_the_rest(db_url: str) -> None:
    device = satellite_row(db_url, household(db_url)).device.id
    old, recent = add(db_url, device, "old"), add(db_url, device, "recent")
    age(db_url, old.id, RETENTION_S + 5)
    age(db_url, recent.id, RETENTION_S - 30)
    assert scalar(db_url, "SELECT count(*) FROM voice_clips") == 2, "control: nothing sweeps but a write"
    newest = add(db_url, device, "newest")
    assert scalar(db_url, "SELECT array_agg(id ORDER BY id) FROM voice_clips") == [recent.id, newest.id]


def test_an_expired_clip_is_not_fetched_even_before_a_sweep(db_url: str) -> None:
    device = satellite_row(db_url, household(db_url)).device.id
    made = add(db_url, device, "late")
    age(db_url, made.id, RETENTION_S + 1)
    assert get(db_url, made.token) is None


def test_an_unreachable_database_is_clips_unavailable() -> None:
    async def scenario() -> None:
        database = PoolDatabase("postgresql://nobody@127.0.0.1:1/none?connect_timeout=1", connect_timeout_s=0.1)
        await database.open()
        try:
            clips = PostgresClips(database, RETENTION_S)
            with pytest.raises(ClipsUnavailable):
                await clips.get("x")
            with pytest.raises(ClipsUnavailable):
                await clips.add(1, "x", 0)
        finally:
            await database.close()

    asyncio.run(scenario())


class OneClip(Clips):
    def __init__(self, clip: Clip | None = None, down: bool = False) -> None:
        self.clip, self.down, self.asked = clip, down, list[str]()

    async def add(self, device_id: int, body: str, since_wake_ms: int) -> NewClip:
        raise AssertionError("not used")

    async def get(self, token: str) -> Clip | None:
        self.asked.append(token)
        if self.down:
            raise ClipsUnavailable("down")
        return self.clip if token == "tok-en_1" else None


def client() -> TestClient:
    app = FastAPI()
    app.include_router(voice_clips.router)
    return TestClient(app)


def test_the_route_streams_the_speech_of_the_clip(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    speech = FakeSpeech(audio=b"ID3-0123456789")
    services.register(Inference, speech)
    services.register(Clips, OneClip(Clip(7, 3, "Mowchi is asleep.", 2000)))
    r = client().get("/api/voice/clips/tok-en_1")
    assert r.status_code == 200 and r.headers["content-type"].startswith("audio/mpeg")
    assert r.content == b"ID3-0123456789" and speech.spoken == ["Mowchi is asleep."]
    out = capsys.readouterr().out
    [line] = events(out, "voice.clip")
    assert (line["clip"], line["device"], line["bytes"], line["complete"]) == ("7", "3", "14", "true")
    assert int(line["total_ms"]) >= 2000 + int(line["tts_first_byte_ms"])
    assert "tok-en_1" not in out and "Mowchi" not in out


def test_the_clip_line_names_the_route_that_spoke(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    services.register(Inference, FakeSpeech())
    services.register(Clips, OneClip(Clip(7, 3, "hi", 0)))
    client().get("/api/voice/clips/tok-en_1")
    [line] = events(capsys.readouterr().out, "voice.clip")
    assert (line["tts_provider"], line["tts_model"]) == ("fake", "fake-tts")


@pytest.mark.parametrize(("clips", "audio", "status", "code"), [
    (OneClip(None), b"x", 404, "not_found"),
    (OneClip(down=True), b"x", 503, "unavailable"),
    (OneClip(Clip(7, 3, "hi", 0)), InferenceUnavailable("down"), 503, "unavailable"),
])
def test_the_route_answers_404_and_503_with_the_error_body(clips: OneClip, audio: bytes | Exception, status: int,
                                                           code: str) -> None:
    services.register(Inference, FakeSpeech(audio=audio))
    services.register(Clips, clips)
    r = client().get("/api/voice/clips/tok-en_1")
    assert r.status_code == status
    assert ErrorResponse.model_validate(r.json()).code == code
    assert clips.asked == ["tok-en_1"]


def test_any_token_shape_is_404_never_a_validation_error() -> None:
    services.register(Clips, OneClip(None))
    for token in ["a", "x" * 300, "%20", "..."]:
        assert client().get(f"/api/voice/clips/{token}").status_code == 404
