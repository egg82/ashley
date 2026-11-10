"""`KeyedProviders` (per-pod cache over `ProviderKeys`): construction rejects shared kind or route names; `names` and
`checkers` cover every route name; `current` serves the env's keys before a read succeeds; `refresh` reads only once the
last read began `refresh_s` ago (a failed read counts), shares one read among concurrent callers, rebuilds exactly the
kinds whose key appeared, changed or went and reports their route names, keeps an unchanged build, keeps what is wired
when a read fails, and never raises; replaced builds stay open until `close`; logs never carry a key."""

import asyncio
import logging

import pytest
from ashley.inference.keyed_providers import PLACEHOLDER, REFRESH_S, KeyedProviders
from ashley.inference.provider_keys import KeyInForce
from hypothesis import given, settings
from hypothesis import strategies as st
from contract.inference_support import Clock, settle
from pkb_support import A, B, C, ROUTES, KeyedFake, Recorder, ScriptedKeys, keyed

SECRETS = ("sk-first-key-AAAA", "sk-second-key-BBBB", "sk-env-key-CCCC", "sk-third-key-DDDD")


def build(keys: ScriptedKeys, env: dict[str, str] | None = None, clock: Clock | None = None,
          refresh_s: float = 30.0, kinds: tuple[str, ...] = (A, B, C)) -> tuple[KeyedProviders, Recorder]:
    recorder = Recorder()
    providers = KeyedProviders([keyed(recorder, k) for k in kinds], keys, env or {}, clock or Clock(), refresh_s)
    return providers, recorder


def served(providers: KeyedProviders, name: str) -> KeyedFake:
    got = providers.current()[name]
    assert isinstance(got, KeyedFake)
    return got


def test_the_refresh_bound_defaults_to_thirty_seconds() -> None:
    assert REFRESH_S == 30.0 and PLACEHOLDER


def test_two_providers_sharing_a_kind_name_raise() -> None:
    recorder = Recorder()
    with pytest.raises(ValueError):
        KeyedProviders([keyed(recorder, A), keyed(recorder, A, frozenset({"other"}))], ScriptedKeys(), {})


@pytest.mark.parametrize("second", [frozenset({C}), frozenset({B, C + "_image"})])
def test_two_providers_sharing_a_route_name_raise(second: frozenset[str]) -> None:
    recorder = Recorder()
    with pytest.raises(ValueError):
        KeyedProviders([keyed(recorder, C), keyed(recorder, B, second)], ScriptedKeys(), {})


def test_names_are_every_route_name_wired_or_not() -> None:
    providers, _ = build(ScriptedKeys())
    assert providers.names() == ROUTES[A] | ROUTES[B] | ROUTES[C]
    assert providers.current() == {}


def test_checkers_are_one_provider_per_name_built_with_the_placeholder() -> None:
    providers, recorder = build(ScriptedKeys())
    checkers = providers.checkers()
    assert set(checkers) == providers.names()
    assert all(isinstance(c, KeyedFake) and c.key == PLACEHOLDER and c.name == n for n, c in checkers.items())
    assert {k for k, _ in recorder.made} == {A, B, C} and {s for _, s in recorder.made} == {PLACEHOLDER}
    assert providers.current() == {}, "a checker is never wired"


def test_before_any_read_the_envs_keys_are_wired_and_an_empty_one_is_not() -> None:
    providers, _ = build(ScriptedKeys(), env={A: SECRETS[0], B: ""})
    assert set(providers.current()) == ROUTES[A]
    assert served(providers, A).key == SECRETS[0]


def test_a_first_read_returns_what_it_changed_and_wires_the_keys_in_force() -> None:
    keys = ScriptedKeys({A: SECRETS[0], C: SECRETS[1]})
    providers, _ = build(keys)
    changed = settle(providers.refresh())
    assert changed == ROUTES[A] | ROUTES[C]
    assert set(providers.current()) == ROUTES[A] | ROUTES[C]
    assert {served(providers, n).key for n in ROUTES[C]} == {SECRETS[1]}


def test_a_stored_key_equal_to_the_envs_keeps_the_envs_build_and_reports_nothing() -> None:
    keys = ScriptedKeys({A: SECRETS[0]})
    providers, recorder = build(keys, env={A: SECRETS[0]})
    before = served(providers, A)
    assert settle(providers.refresh()) == frozenset()
    assert served(providers, A) is before and recorder.builds_of(A, SECRETS[0]) == 1


def test_a_stored_key_replaces_a_different_env_key() -> None:
    keys = ScriptedKeys({A: SECRETS[0]})
    providers, _ = build(keys, env={A: SECRETS[2]})
    assert settle(providers.refresh()) == ROUTES[A]
    assert served(providers, A).key == SECRETS[0]


def test_an_unchanged_key_keeps_its_build() -> None:
    keys = ScriptedKeys({A: SECRETS[0], B: SECRETS[1]})
    clock = Clock()
    providers, recorder = build(keys, clock=clock)
    settle(providers.refresh())
    before = {n: w for n, w in providers.current().items()}
    clock.advance(31)
    assert settle(providers.refresh()) == frozenset()
    assert all(providers.current()[n] is w for n, w in before.items())
    assert recorder.builds_of(A, SECRETS[0]) == 1 and recorder.builds_of(B, SECRETS[1]) == 1


def test_a_rotated_key_makes_a_new_build_and_reports_all_its_route_names_only() -> None:
    keys = ScriptedKeys({A: SECRETS[0], C: SECRETS[1]})
    clock = Clock()
    providers, recorder = build(keys, clock=clock)
    settle(providers.refresh())
    a_before = served(providers, A)
    keys.keys[C] = SECRETS[3]
    clock.advance(30)
    assert settle(providers.refresh()) == ROUTES[C]
    assert served(providers, A) is a_before and recorder.builds_of(A) == 1
    assert {served(providers, n).key for n in ROUTES[C]} == {SECRETS[3]}


def test_a_removed_key_unwires_its_names_and_reports_them() -> None:
    keys = ScriptedKeys({A: SECRETS[0], C: SECRETS[1]})
    clock = Clock()
    providers, _ = build(keys, clock=clock)
    settle(providers.refresh())
    del keys.keys[C]
    clock.advance(30)
    assert settle(providers.refresh()) == ROUTES[C]
    assert set(providers.current()) == ROUTES[A]


def test_a_key_removed_everywhere_unwires_the_envs_build_too() -> None:
    keys = ScriptedKeys({})
    providers, _ = build(keys, env={A: SECRETS[2]})
    assert set(providers.current()) == ROUTES[A]
    assert settle(providers.refresh()) == ROUTES[A]
    assert providers.current() == {}


def test_a_replaced_build_stays_open_until_close_and_close_releases_every_build() -> None:
    keys = ScriptedKeys({A: SECRETS[0]})
    clock = Clock()
    providers, recorder = build(keys, clock=clock)
    providers.checkers()
    settle(providers.refresh())
    old = served(providers, A)
    keys.keys[A] = SECRETS[1]
    clock.advance(30)
    settle(providers.refresh())
    assert old is not served(providers, A) and not old.closed
    del keys.keys[A]
    clock.advance(30)
    settle(providers.refresh())
    assert recorder.open_ones(), "nothing closes before `close`"
    settle(providers.close())
    assert recorder.open_ones() == []


def test_refresh_reads_nothing_before_the_bound_and_reads_at_it() -> None:
    keys = ScriptedKeys({A: SECRETS[0]})
    clock = Clock()
    providers, _ = build(keys, clock=clock, refresh_s=30.0)
    settle(providers.refresh())
    assert keys.reads == 1
    clock.advance(29.9)
    assert settle(providers.refresh()) == frozenset() and keys.reads == 1
    clock.advance(0.1)
    settle(providers.refresh())
    assert keys.reads == 2


def test_a_rotation_is_not_seen_before_the_bound() -> None:
    keys = ScriptedKeys({A: SECRETS[0]})
    clock = Clock()
    providers, _ = build(keys, clock=clock)
    settle(providers.refresh())
    keys.keys[A] = SECRETS[1]
    clock.advance(10)
    assert settle(providers.refresh()) == frozenset()
    assert served(providers, A).key == SECRETS[0]


@settings(max_examples=60)
@given(st.lists(st.tuples(st.floats(0, 70), st.booleans()), min_size=1, max_size=12))
def test_a_read_happens_exactly_when_the_last_one_began_refresh_s_ago(steps: list[tuple[float, bool]]) -> None:
    keys = ScriptedKeys({A: SECRETS[0]})
    clock = Clock()
    providers, _ = build(keys, clock=clock, refresh_s=30.0)
    last: float | None = None
    expected = 0
    for advance, fails in steps:
        clock.advance(advance)
        keys.fail = fails
        if last is None or clock.now - last >= 30.0:
            expected += 1
            last = clock.now
        settle(providers.refresh())
        assert keys.reads == expected


def test_concurrent_callers_share_one_read_and_all_see_the_result_when_they_return() -> None:
    keys = ScriptedKeys({A: SECRETS[0]})
    providers, recorder = build(keys)

    async def scenario() -> list[frozenset[str]]:
        keys.gate = asyncio.Event()
        calls = [asyncio.create_task(providers.refresh()) for _ in range(6)]
        for _ in range(10):
            await asyncio.sleep(0)
        keys.gate.set()
        done = await asyncio.gather(*calls)
        assert set(providers.current()) == ROUTES[A]
        return list(done)

    got = settle(scenario())
    assert keys.reads == 1
    assert frozenset().union(*got) == ROUTES[A]
    assert recorder.builds_of(A, SECRETS[0]) == 1


def test_a_failed_read_keeps_what_is_wired_returns_nothing_and_waits_the_bound_again(
        caplog: pytest.LogCaptureFixture) -> None:
    keys = ScriptedKeys({A: SECRETS[0]})
    clock = Clock()
    providers, _ = build(keys, clock=clock)
    settle(providers.refresh())
    before = served(providers, A)
    keys.fail = True
    keys.keys[A] = SECRETS[1]
    clock.advance(30)
    with caplog.at_level(logging.DEBUG):
        assert settle(providers.refresh()) == frozenset()
    assert [r for r in caplog.records if r.getMessage() == "inference.keys_unreadable"]
    assert served(providers, A) is before and keys.reads == 2
    clock.advance(29)
    settle(providers.refresh())
    assert keys.reads == 2
    keys.fail = False
    clock.advance(1)
    assert settle(providers.refresh()) == ROUTES[A]
    assert served(providers, A).key == SECRETS[1]


def test_a_read_that_never_succeeded_leaves_the_envs_keys_wired() -> None:
    keys = ScriptedKeys({A: SECRETS[0]})
    keys.fail = True
    providers, _ = build(keys, env={A: SECRETS[2], B: SECRETS[2]})
    assert settle(providers.refresh()) == frozenset()
    assert set(providers.current()) == ROUTES[A] | ROUTES[B]
    assert served(providers, A).key == SECRETS[2]


def test_a_change_logs_the_kinds_and_sources_and_never_a_key(caplog: pytest.LogCaptureFixture) -> None:
    keys = ScriptedKeys({A: SECRETS[0], B: SECRETS[3]})
    keys.from_env.add(B)
    clock = Clock()
    providers, _ = build(keys, clock=clock)
    with caplog.at_level(logging.DEBUG):
        settle(providers.refresh())
        keys.fail = True
        clock.advance(30)
        settle(providers.refresh())
    changed = [r for r in caplog.records if r.getMessage() == "inference.keys"]
    assert changed, "a read that changed something logs `inference.keys`"
    assert "connection" in repr(changed[0].__dict__.get("fields")) and "env" in repr(changed[0].__dict__.get("fields"))
    everything = caplog.text + repr([r.__dict__ for r in caplog.records])
    assert not any(s in everything for s in SECRETS)


def test_a_read_that_changed_nothing_logs_no_inference_keys_line(caplog: pytest.LogCaptureFixture) -> None:
    keys = ScriptedKeys({A: SECRETS[0]})
    clock = Clock()
    providers, _ = build(keys, clock=clock)
    settle(providers.refresh())
    caplog.clear()
    clock.advance(30)
    with caplog.at_level(logging.DEBUG):
        settle(providers.refresh())
    assert not [r for r in caplog.records if r.getMessage() == "inference.keys"]


def test_balances_follow_the_builds_wired_and_a_rotated_key_is_read_with_the_new_key() -> None:
    keys = ScriptedKeys({B: SECRETS[0]})
    clock = Clock()
    recorder = Recorder()
    providers = KeyedProviders([keyed(recorder, A), keyed(recorder, B, balance=True)], keys, {}, clock, 30.0)
    assert providers.balances() == {}
    first = settle(providers.balance_sources())
    assert set(first) == {B} and getattr(first[B], "key") == SECRETS[0]
    keys.keys[B] = SECRETS[1]
    clock.advance(30)
    again = settle(providers.balance_sources())
    assert getattr(again[B], "key") == SECRETS[1]
    assert providers.balances() == again
    del keys.keys[B]
    clock.advance(30)
    assert settle(providers.balance_sources()) == {}


def test_key_in_force_hides_its_secret_from_repr() -> None:
    assert SECRETS[0] not in repr(KeyInForce(A, SECRETS[0], None))

