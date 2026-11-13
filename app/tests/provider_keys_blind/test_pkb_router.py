"""`RoutedInference` with `keyed`: a name `keyed` can carry that `providers` also has raises ValueError; every call
awaits `refresh` first and serves from the keys in force beside `providers`; a rotated key is used within the bound by
a new provider and the old one is not called again; a provider resting after a failure is tried again once its build
changed and not otherwise; a removed key unwires its routes; a database away leaves the env's keys serving."""

import pytest
from ashley.inference.inference import InferenceUnavailable
from ashley.inference.keyed_providers import KeyedProviders
from ashley.inference.reply import Reply
from ashley.inference.router import RoutedInference
from contract.inference_support import COOLDOWN_S, PRICES, Clock, FakeLedger, FakeProvider, fail, prompt, route, settle, table
from pkb_support import A, B, Recorder, ScriptedKeys, keyed

KEY1, KEY2 = "sk-router-key-1111", "sk-router-key-2222"


def routed(keys: ScriptedKeys, env: dict[str, str] | None = None, clock: Clock | None = None,
           providers: list[FakeProvider] | None = None, routes: list[str] | None = None,
           recorder: Recorder | None = None) -> tuple[RoutedInference, KeyedProviders, Clock, Recorder]:
    clock = clock or Clock()
    recorder = recorder or Recorder()
    kp = KeyedProviders([keyed(recorder, A), keyed(recorder, B)], keys, env or {}, clock, 30.0)
    router = RoutedInference(table([route(r) for r in routes or [A]]), providers or [], FakeLedger(), PRICES, clock,
                             keyed=kp)
    return router, kp, clock, recorder


def ask(router: RoutedInference) -> str:
    return settle(router.generate("chat", prompt("hi"), Reply)).text


def asked(recorder: Recorder, key: str) -> int:
    return sum(len(w.asked) for w in recorder.wired if w.key == key)


def test_a_provider_name_a_keyed_provider_can_carry_raises_even_when_it_is_not_wired() -> None:
    recorder = Recorder()
    kp = KeyedProviders([keyed(recorder, A)], ScriptedKeys(), {})
    with pytest.raises(ValueError):
        RoutedInference(table([route(A)]), [FakeProvider(A)], FakeLedger(), PRICES, Clock(), keyed=kp)


def test_a_call_serves_from_the_key_in_force_and_a_rotated_key_is_used_after_the_bound() -> None:
    keys = ScriptedKeys({A: KEY1})
    router, _, clock, recorder = routed(keys)
    assert ask(router) == "answer" and asked(recorder, KEY1) == 1
    keys.keys[A] = KEY2
    clock.advance(10)
    ask(router)
    assert asked(recorder, KEY1) == 2 and asked(recorder, KEY2) == 0
    clock.advance(20)
    ask(router)
    assert asked(recorder, KEY1) == 2 and asked(recorder, KEY2) == 1


def test_every_call_awaits_refresh_before_choosing_a_provider() -> None:
    keys = ScriptedKeys({A: KEY1})
    router, _, clock, _ = routed(keys)
    ask(router)
    ask(router)
    assert keys.reads == 1
    clock.advance(30)
    ask(router)
    assert keys.reads == 2


def test_keyed_providers_stand_beside_providers_that_need_no_key() -> None:
    plain = FakeProvider("plain", [fail("unavailable")])
    keys = ScriptedKeys({A: KEY1})
    router, _, _, recorder = routed(keys, providers=[plain], routes=["plain", A])
    assert ask(router) == "answer"
    assert len(plain.asked) == 1 and asked(recorder, KEY1) == 1


def test_a_removed_key_unwires_its_routes() -> None:
    keys = ScriptedKeys({A: KEY1})
    router, _, clock, _ = routed(keys)
    ask(router)
    del keys.keys[A]
    clock.advance(30)
    with pytest.raises(InferenceUnavailable):
        ask(router)


def test_a_provider_resting_after_a_failure_is_not_asked_again_until_its_key_changes() -> None:
    keys = ScriptedKeys({A: KEY1})
    recorder = Recorder()
    recorder.steps[KEY1] = [fail("unavailable")]
    router, _, clock, _ = routed(keys, recorder=recorder)
    with pytest.raises(InferenceUnavailable):
        ask(router)
    clock.advance(31)
    with pytest.raises(InferenceUnavailable):
        ask(router)
    assert asked(recorder, KEY1) == 1, "within the cooldown the failing provider is not asked again"
    keys.keys[A] = KEY2
    clock.advance(31)
    assert clock.now - 1000.0 < COOLDOWN_S
    assert ask(router) == "answer", "a changed build stops resting and is tried at once"
    assert asked(recorder, KEY2) == 1


def test_with_the_database_away_the_envs_keys_still_serve() -> None:
    keys = ScriptedKeys({A: KEY2})
    keys.fail = True
    router, _, _, recorder = routed(keys, env={A: KEY1})
    assert ask(router) == "answer" and asked(recorder, KEY1) == 1 and asked(recorder, KEY2) == 0
