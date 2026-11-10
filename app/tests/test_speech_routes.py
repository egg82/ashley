"""Speech tasks in `routes.parse` and the shipped `routes.json`: who may take which task, and the ledger and wiring
that carry speech calls."""

from collections.abc import Mapping
from decimal import Decimal

import httpx2
import psycopg
import pytest
from ashley import services
from ashley.db.database import Database
from ashley.db.migrate import migrate
from ashley.db.pool import PoolDatabase
from ashley.inference import routes
from ashley.inference.inference import Inference
from ashley.inference.elevenlabs_tts import ElevenLabsSpeaker
from ashley.inference.model import Usage
from ashley.inference.postgres import PostgresSpendLedger
from ashley.inference.provider import Wired
from ashley.inference.providers import OpenAICompatibleProvider
from ashley.inference.spend import Call
from ashley.inference.wyoming_stt import WyomingTranscriber
from ashley.settings import from_env
from ashley.wiring import wire
from openai import AsyncOpenAI
from speech_support import ScriptedSpeaker, ScriptedTranscriber, run


def table(task: str, provider: str, params: Mapping[str, object] | None = None) -> dict[str, object]:
    text = {t: [{"provider": "none", "model": "m", "timeout_s": 1}] for t in routes.TASKS}
    route = {"provider": provider, "model": "m", "timeout_s": 1, "params": dict(params or {})}
    return {"cooldown_s": 60, "tasks": {**text, task: [route]}}


def test_a_provider_that_cannot_do_the_task_is_refused_when_the_routes_load() -> None:
    listener, speaker = ScriptedTranscriber("t"), ScriptedSpeaker("s")
    providers: dict[str, Wired] = {"t": listener, "s": speaker}
    assert routes.parse(table("transcribe", "t"), providers).speech["transcribe"][0].provider == "t"
    assert routes.parse(table("speak", "s"), providers).speech["speak"][0].provider == "s"
    for task, provider in (("transcribe", "s"), ("speak", "t"), ("chat", "t"), ("chat", "s")):
        with pytest.raises(ValueError, match="cannot do"):
            routes.parse(table(task, provider), providers)


def test_an_unwired_provider_may_be_named_and_speech_tasks_may_be_absent() -> None:
    parsed = routes.parse(table("speak", "later"), {})
    assert parsed.speech["speak"][0].provider == "later"
    bare = routes.parse({"cooldown_s": 60, "tasks": {t: [{"provider": "x", "model": "m", "timeout_s": 1}]
                                                      for t in routes.TASKS}}, {})
    assert bare.speech == {} and bare.for_task("speak") == ()


def test_the_shipped_routes_load_with_the_real_providers_and_put_wyoming_first() -> None:
    providers: dict[str, Wired] = {
        "wyoming": WyomingTranscriber("wyoming", "tcp://stt:10300"),
        "openai": OpenAICompatibleProvider("openai", AsyncOpenAI(api_key="k")),
        "elevenlabs": ElevenLabsSpeaker("elevenlabs", httpx2.AsyncClient())}
    loaded = routes.load(providers)
    assert [r.provider for r in loaded.speech["transcribe"]] == ["wyoming", "openai"]
    assert [r.provider for r in loaded.speech["speak"]] == ["elevenlabs"]
    assert routes.load({}).speech["speak"][0].params["voice_id"]


def test_a_speech_call_is_one_ledger_row_carrying_what_it_was_billed_by(empty_database: str) -> None:
    migrate(empty_database)

    async def scenario() -> None:
        db = PoolDatabase(empty_database, connect_timeout_s=5.0)
        await db.open()
        try:
            ledger = PostgresSpendLedger(db)
            await ledger.record(Call("transcribe", "wyoming", "whisper", "ok", Usage(0, 0, audio_ms=1500), None, 80))
            await ledger.record(Call("speak", "elevenlabs", "flash", "ok", Usage(0, 0, characters=42),
                                     Decimal("0.001"), 300))
            await ledger.record(Call("chat", "anthropic", "m", "ok", Usage(5, 6), None, 10))
            await ledger.record(Call("chat", "anthropic", "m", "error", None, None, 10))
        finally:
            await db.close()

    run(scenario())
    with psycopg.connect(empty_database, autocommit=True) as conn:
        rows = conn.execute(b"SELECT task, input_tokens, audio_ms, characters FROM inference_calls ORDER BY id"
                            ).fetchall()
    assert rows == [("transcribe", 0, 1500, 0), ("speak", 0, 0, 42), ("chat", 5, 0, 0), ("chat", None, None, None)]


def test_the_speech_settings_wire_their_providers_against_the_shipped_routes() -> None:
    env = {"DATABASE_URL": "postgresql://nobody@127.0.0.1:1/none", "WYOMING_STT_URL": "tcp://stt:10300",
           "ELEVENLABS_API_KEY": "k", "OPENAI_API_KEY": "k"}
    settings = from_env(env)
    assert (settings.wyoming_stt_url, settings.elevenlabs_api_key) == ("tcp://stt:10300", "k")
    try:
        assert len(wire(settings)) == 4, "the keyed providers, the live feed, Homes and the search client to close"
        assert len(wire(from_env({"DATABASE_URL": env["DATABASE_URL"]}))) == 4, "the same four without a key"
    finally:
        services.unregister(Database)
        services.unregister(Inference)
    with pytest.raises(ValueError):
        wire(from_env({**env, "WYOMING_STT_URL": "http://stt"}))
    services.unregister(Database)
