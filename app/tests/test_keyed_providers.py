"""`KeyedProviders`, the per-pod cache of the providers the keys in force turn on, over a scripted `ProviderKeys` and
a fake build: the env's keys are wired before any read; the keys are read again only once `refresh_s` has passed;
a build is made again only when its key changed, and a replaced one is closed only at `close`; a failed read keeps
what was wired; concurrent callers share one read; the log never carries a key. Then `RoutedInference` over it: a
provider whose key arrives after start answers the next call once the bound has passed, and a rotated key stops a
resting provider resting."""

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

import pytest
from ashley.connections.kinds import ConnectionKind
from ashley.inference.inference import InferenceUnavailable
from ashley.inference.keyed import Built, KeyedProvider
from ashley.inference.keyed_providers import KeyedProviders
from ashley.inference.kinds import ANTHROPIC
from ashley.inference.model import Entry, Message, Prompt, SystemPrompt, ToolChoice, ToolSpec, Usage
from catalogue_support import NONE
from ashley.inference.provider import Completion, Provider, ProviderFailed, ToolUse, Wired
from ashley.inference.provider_keys import KeyInForce, KeysUnavailable, ProviderKeys
from ashley.inference.router import RoutedInference
from ashley.inference.routes import TASKS, parse
from pydantic import BaseModel
from speech_support import MemoryLedger


class Answer(BaseModel):
    text: str


@dataclass
class Keys(ProviderKeys):
    """Answers `now`, or raises KeysUnavailable while `down`; counts reads."""

    now: dict[str, KeyInForce] = field(default_factory=dict[str, KeyInForce])
    down: bool = False
    reads: int = 0
    gate: asyncio.Event | None = None

    async def in_force(self) -> Mapping[str, KeyInForce]:
        self.reads += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.down:
            raise KeysUnavailable("away")
        return dict(self.now)


@dataclass
class Named(Wired):
    label: str
    key: str = field(repr=False)

    @property
    def name(self) -> str:
        return self.label


@dataclass
class Builds:
    """A fake provider kind's builds: which keys were built and which builds were closed."""

    made: list[str] = field(default_factory=list[str])
    closed: list[str] = field(default_factory=list[str])

    def build(self, key: str) -> Built:
        self.made.append(key)

        async def close() -> None:
            self.closed.append(key)
        return Built((Named("chat", key), Named("chat_image", key)), {}, close)


KIND: ConnectionKind = replace(ANTHROPIC.kind, name="fake")


def keyed(builds: Builds, keys: Keys, env: dict[str, str], clock: list[float]) -> KeyedProviders:
    return KeyedProviders([KeyedProvider(KIND, frozenset({"chat", "chat_image"}), builds.build)], keys, env,
                          clock=lambda: clock[0], refresh_s=30)


def row(secret: str, connection_id: int = 7) -> KeyInForce:
    return KeyInForce("fake", secret, connection_id)


def key_of(k: KeyedProviders) -> str | None:
    found = k.current().get("chat")
    return None if found is None else getattr(found, "key")


def test_the_envs_key_is_wired_before_any_read_and_a_row_then_replaces_it() -> None:
    builds, keys, clock = Builds(), Keys({"fake": row("from-row")}), [0.0]
    k = keyed(builds, keys, {"fake": "from-env"}, clock)
    assert key_of(k) == "from-env" and keys.reads == 0
    assert asyncio.run(k.refresh()) == {"chat", "chat_image"}
    assert key_of(k) == "from-row" and builds.made == ["from-env", "from-row"]


def test_the_keys_are_read_again_only_once_the_bound_has_passed() -> None:
    builds, keys, clock = Builds(), Keys({"fake": row("one")}), [0.0]
    k = keyed(builds, keys, {}, clock)
    asyncio.run(k.refresh())
    keys.now = {"fake": row("two")}
    clock[0] = 29.9
    assert asyncio.run(k.refresh()) == frozenset() and keys.reads == 1 and key_of(k) == "one"
    clock[0] = 30.0
    assert asyncio.run(k.refresh()) == {"chat", "chat_image"} and keys.reads == 2 and key_of(k) == "two"


def test_the_same_key_keeps_its_build_and_a_replaced_build_is_closed_only_at_close() -> None:
    builds, keys, clock = Builds(), Keys({"fake": row("one")}), [0.0]
    k = keyed(builds, keys, {"fake": "one"}, clock)
    assert asyncio.run(k.refresh()) == frozenset() and builds.made == ["one"]
    keys.now, clock[0] = {"fake": row("two")}, 60.0
    asyncio.run(k.refresh())
    assert builds.closed == []
    asyncio.run(k.close())
    assert sorted(builds.closed) == ["one", "two"] and k.current() == {}


def test_a_removed_key_unwires_the_provider() -> None:
    builds, keys, clock = Builds(), Keys({}), [0.0]
    k = keyed(builds, keys, {"fake": "env"}, clock)
    assert asyncio.run(k.refresh()) == {"chat", "chat_image"} and k.current() == {}


def test_a_failed_read_keeps_what_was_wired_and_waits_the_bound_again(caplog: pytest.LogCaptureFixture) -> None:
    builds, keys, clock = Builds(), Keys({"fake": row("one")}, down=True), [0.0]
    k = keyed(builds, keys, {"fake": "env"}, clock)
    assert asyncio.run(k.refresh()) == frozenset() and key_of(k) == "env"
    assert "inference.keys_unreadable" in caplog.text
    keys.down, clock[0] = False, 10.0
    assert asyncio.run(k.refresh()) == frozenset() and keys.reads == 1
    clock[0] = 30.0
    asyncio.run(k.refresh())
    assert key_of(k) == "one"


def test_concurrent_callers_share_one_read() -> None:
    builds, keys, clock = Builds(), Keys({"fake": row("one")}), [0.0]
    k = keyed(builds, keys, {}, clock)

    async def scenario() -> None:
        keys.gate = asyncio.Event()
        waiting = [asyncio.create_task(k.refresh()) for _ in range(5)]
        await asyncio.sleep(0)
        keys.gate.set()
        await asyncio.gather(*waiting)
    asyncio.run(scenario())
    assert keys.reads == 1 and builds.made == ["one"]


def test_the_log_names_where_each_key_came_from_and_never_the_key(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="ashley.inference"):
        builds, keys, clock = Builds(), Keys({"fake": row("sk-secret-value")}), [0.0]
        k = keyed(builds, keys, {"fake": "sk-env-value"}, clock)
        asyncio.run(k.refresh())
    fields = [getattr(r, "fields") for r in caplog.records if r.getMessage() == "inference.keys"]
    assert [f["sources"] for f in fields] == ["fake:env", "fake:connection"]
    assert "sk-" not in repr(fields)


def test_two_providers_sharing_a_route_name_are_refused() -> None:
    builds = Builds()
    other = KeyedProvider(replace(KIND, name="other"), frozenset({"chat"}), builds.build)
    with pytest.raises(ValueError):
        KeyedProviders([KeyedProvider(KIND, frozenset({"chat"}), builds.build), other], Keys(), {})


class Keyed(Provider):
    """Named `anthropic`: answers with the key it was built with, or fails `unavailable` for the key `spent`."""

    def __init__(self, key: str) -> None:
        self._key = key

    @property
    def name(self) -> str:
        return "anthropic"

    def check_params(self, params: Mapping[str, object]) -> None:
        return None

    async def complete[O: BaseModel](self, model: str, params: Mapping[str, object], system: SystemPrompt,
                                      messages: tuple[Entry, ...], tools: tuple[ToolSpec, ...], tool_choice: ToolChoice,
                                      output: type[O], timeout_s: float) -> Completion[O] | ToolUse:
        if self._key == "spent":
            raise ProviderFailed("unavailable", "402")
        return Completion(output.model_validate({"text": self._key}), Usage(1, 1))


def build(key: str) -> Built:
    async def close() -> None:
        return None
    return Built((Keyed(key),), {}, close)


def inference(keys: Keys, clock: list[float]) -> RoutedInference:
    k = KeyedProviders([replace(ANTHROPIC, build=build)], keys, {}, clock=lambda: clock[0], refresh_s=30)
    data = {"cooldown_s": 300, "tasks": {t: [{"provider": "anthropic", "model": "m", "timeout_s": 5}] for t in TASKS}}
    return RoutedInference(parse(data, k.checkers()), [], MemoryLedger(), NONE, clock=lambda: clock[0], keyed=k)


PROMPT = Prompt({"default": SystemPrompt("s")}, (Message("person", "hi"),))


def test_a_key_added_after_start_answers_once_the_bound_has_passed() -> None:
    keys, clock = Keys(), [0.0]
    routed = inference(keys, clock)
    with pytest.raises(InferenceUnavailable):
        asyncio.run(routed.generate("chat", PROMPT, Answer))
    keys.now, clock[0] = {"anthropic": KeyInForce("anthropic", "fresh", 3)}, 30.0
    assert asyncio.run(routed.generate("chat", PROMPT, Answer)).text == "fresh"


def test_a_rotated_key_stops_a_resting_provider_resting() -> None:
    keys, clock = Keys({"anthropic": KeyInForce("anthropic", "spent", 3)}), [0.0]
    routed = inference(keys, clock)
    with pytest.raises(InferenceUnavailable):
        asyncio.run(routed.generate("chat", PROMPT, Answer))
    keys.now, clock[0] = {"anthropic": KeyInForce("anthropic", "topped-up", 3)}, 30.0
    assert asyncio.run(routed.generate("chat", PROMPT, Answer)).text == "topped-up"
