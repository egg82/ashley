"""Helpers for the blind provider-key contract tests: deployment kinds built from values, keyed providers whose builds are
recorded, a scripted `ProviderKeys`, `Connections` that cannot be reached, and a Postgres-backed set of connections."""

import asyncio
import os
from collections.abc import AsyncGenerator, Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from ashley.connections.connections import Connections, ConnectionsUnavailable
from ashley.connections.kinds import Check, ConnectionKind, Refusal
from ashley.connections.model import Connection, Holder, Kind, Opened
from ashley.connections.postgres import PostgresConnections
from ashley.connections.sealing import VERSION, Sealer
from ashley.db.pool import PoolDatabase
from ashley.inference.balance import BalanceSource, Quota
from ashley.inference.keyed import Built, KeyedProvider
from ashley.inference.provider_keys import KeyInForce, KeysUnavailable, ProviderKeys
from contract.inference_support import Clock, FakeProvider, Step

SEALING_KEY = os.urandom(32)

A, B, C = "alpha", "beta", "gamma"
"""Three provider kind names, each also the route name its build carries; `C` carries two (`gamma` and `gamma_image`)."""
ROUTES: Mapping[str, frozenset[str]] = {A: frozenset({A}), B: frozenset({B}), C: frozenset({C, C + "_image"})}


async def _answers(url: str, key: str, person: int) -> Refusal | None:
    return None


def deployment_kind(name: str, deployment: bool = True, holders: frozenset[Holder] = frozenset({"household"}),
                    check: Check = _answers) -> ConnectionKind:
    """A model provider's kind as the contract describes it: a `deployment` kind of the `inference` port at one address."""
    return ConnectionKind(
        name=name, title=name.title(), what="model calls", blurb="blurb", connected="connected", removed="removed",
        holders=holders, schemes=frozenset({"https"}), address_placeholder="", secret_field="api_key",
        secret_label="Key", secret_noun="key", check=check, refusals={"key_refused": "refused"}, ports=frozenset({"inference"}),
        fixed_address=f"https://api.{name}.test", deployment=deployment)


class KeyedFake(FakeProvider):
    """A provider built from `key`, answering with the key's name so a test can tell which build served."""

    def __init__(self, name: str, key: str, script: Iterable[Step] = ()) -> None:
        super().__init__(name, script)
        self.key = key
        self.closed = False


class FakeBalance(BalanceSource):
    def __init__(self, key: str) -> None:
        self.key = key

    async def read(self) -> Quota:
        raise AssertionError("a test never reads a balance")


@dataclass
class Recorder:
    """Every build every provider made: (kind name, key) in order, the providers built, and which were closed."""

    made: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    wired: list[KeyedFake] = field(default_factory=list[KeyedFake])
    balance_sources: list[FakeBalance] = field(default_factory=list[FakeBalance])
    steps: dict[str, list[Step]] = field(default_factory=dict[str, list[Step]])
    """What a build made from a key does when called (an answer when the key is not here)."""

    def builds_of(self, kind: str, key: str | None = None) -> int:
        return sum(1 for k, s in self.made if k == kind and (key is None or s == key))

    def open_ones(self) -> list[KeyedFake]:
        return [w for w in self.wired if not w.closed]


def keyed(recorder: Recorder, kind: str, names: frozenset[str] | None = None, deployment: bool = True,
          balance: bool = False) -> KeyedProvider:
    """A `KeyedProvider` of `kind` whose builds are `KeyedFake`s, one per name, recorded in `recorder`."""
    carried = ROUTES.get(kind, frozenset({kind})) if names is None else names

    def build(key: str) -> Built:
        recorder.made.append((kind, key))
        mine = [KeyedFake(n, key, recorder.steps.get(key, ())) for n in sorted(carried)]
        recorder.wired.extend(mine)
        sources: dict[str, BalanceSource] = {}
        if balance:
            source = FakeBalance(key)
            recorder.balance_sources.append(source)
            sources[kind] = source

        async def close() -> None:
            for w in mine:
                w.closed = True

        return Built(tuple(mine), sources, close)

    return KeyedProvider(deployment_kind(kind, deployment), carried, build)


class ScriptedKeys(ProviderKeys):
    """Says what `keys` says (kind name to key) until `fail` is set, counting each read, a kind in `from_env` as the env's; `gate`, when set, holds a read
    open until the test sets it."""

    def __init__(self, keys: Mapping[str, str] | None = None) -> None:
        self.keys: dict[str, str] = dict(keys or {})
        self.from_env: set[str] = set()
        self.fail = False
        self.reads = 0
        self.gate: asyncio.Event | None = None

    async def in_force(self) -> Mapping[str, KeyInForce]:
        self.reads += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.fail:
            raise KeysUnavailable("scripted")
        return {k: KeyInForce(k, s, None if k in self.from_env else 100 + i) for i, (k, s) in enumerate(self.keys.items())}


class Unreachable(Connections):
    """A `Connections` that holds the key but whose database is away."""

    def can_open(self) -> bool:
        return True

    async def of_household(self, household_id: int, person_id: int | None = None) -> tuple[Connection, ...]:
        raise ConnectionsUnavailable("away")

    async def opened(self, connection_id: int, household_id: int, person_id: int | None = None) -> Opened | None:
        raise ConnectionsUnavailable("away")

    async def add(self, household_id: int, kind: Kind, label: str, base_url: str, secret: str, added_by: int,
                  holder: Holder | None = None) -> Connection:
        raise ConnectionsUnavailable("away")

    async def replace(self, connection_id: int, household_id: int, person_id: int, base_url: str,
                      secret: str) -> Connection | None:
        raise ConnectionsUnavailable("away")

    async def relabel(self, connection_id: int, household_id: int, person_id: int, label: str) -> Connection | None:
        raise ConnectionsUnavailable("away")

    async def seed(self, household_id: int, kind: Kind, base_url: str, secret: str) -> Connection | None:
        raise ConnectionsUnavailable("away")

    async def remove(self, connection_id: int, household_id: int, person_id: int | None) -> bool:
        raise ConnectionsUnavailable("away")

    async def answered(self, connection_id: int) -> None:
        raise ConnectionsUnavailable("away")


@asynccontextmanager
async def connections_on(url: str, key: bytes = SEALING_KEY) -> AsyncGenerator[Connections]:
    database = PoolDatabase(url)
    await database.open()
    try:
        yield PostgresConnections(database, Sealer({VERSION: key}))
    finally:
        await database.close()


def new_clock() -> Clock:
    return Clock(1000.0)
