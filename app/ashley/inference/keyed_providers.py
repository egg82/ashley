"""The keyed model providers wired now: a per-pod cache over `ProviderKeys`, never state. Losing it costs one read of
the keys; nothing in it is the only copy of anything.

A key added, rotated or removed in the connections room on any pod, on either site, reaches every pod's calls within
`refresh_s` (`REFRESH_S`, 30 seconds) with no restart: each call to `RoutedInference` first awaits `refresh`, which
reads the keys again once the last read is that old."""

import asyncio
import logging
import time
from collections.abc import Callable, Iterable, Mapping

from .. import logs
from .balance import BalanceSource
from .keyed import Built, KeyedProvider
from .provider import Wired
from .provider_keys import KeyInForce, KeysUnavailable, ProviderKeys

log = logging.getLogger("ashley.inference")

REFRESH_S = 30.0
"""How old the keys read last may be before a call reads them again: the bound on how long a pod calls with a key
that was rotated or removed elsewhere."""

PLACEHOLDER = "unset"
"""The key `checkers` are built with: never sent anywhere."""


class KeyedProviders:
    """`keyed` are the providers a key turns on (two sharing a kind name or a route name raise ValueError); `keys` says
    which key each uses now; `env` (kind name to the env's key, empty when unset) is what is wired before the first read
    of `keys` succeeds, so a process serves from the env's keys while the database is away, as it did before keys were
    stored. `clock` is monotonic seconds."""

    def __init__(self, keyed: Iterable[KeyedProvider], keys: ProviderKeys, env: Mapping[str, str],
                 clock: Callable[[], float] = time.monotonic, refresh_s: float = REFRESH_S) -> None:
        self._keyed: dict[str, KeyedProvider] = {}
        names: set[str] = set()
        for provider in keyed:
            if provider.kind.name in self._keyed or names & provider.names:
                raise ValueError(f"two keyed providers share the kind or a route name of {provider.kind.name!r}")
            self._keyed[provider.kind.name] = provider
            names |= provider.names
        self._names = frozenset(names)
        self._keys = keys
        self._clock = clock
        self._refresh_s = refresh_s
        self._lock = asyncio.Lock()
        self._read_at: float | None = None
        self._in_force: dict[str, KeyInForce] = {}
        self._builds: dict[str, Built] = {}
        self._retired: list[Built] = []
        self._checkers: dict[str, Built] = {}
        self._wired: dict[str, Wired] = {}
        self._rebuild({kind: KeyInForce(kind, secret, None) for kind, secret in env.items()
                       if secret and kind in self._keyed})

    def names(self) -> frozenset[str]:
        """Every route name a build of these providers can carry, wired now or not."""
        return self._names

    def checkers(self) -> Mapping[str, Wired]:
        """One provider per name in `names`, built with `PLACEHOLDER` for its key, so the routes' params can be checked
        at start for a provider whose key is not set yet (`ashley.inference.routes.load`). Never call one."""
        if not self._checkers:
            self._checkers = {kind: p.build(PLACEHOLDER) for kind, p in self._keyed.items()}
        return {w.name: w for built in self._checkers.values() for w in built.wired}

    def current(self) -> Mapping[str, Wired]:
        """The providers wired now, by route name: each build of a key in force at the last successful read (before
        any, the env's)."""
        return self._wired

    def balances(self) -> Mapping[str, BalanceSource]:
        """The balance sources of the builds in `current`, by provider name."""
        return {name: source for built in self._builds.values() for name, source in built.balances.items()}

    async def refresh(self) -> frozenset[str]:
        """Read the keys again when the last read began `refresh_s` or more ago (or none has), and rebuild what changed:
        a kind whose key appeared or changed gets a new build, one whose key is gone is unwired, one whose key is the
        same keeps its build. Returns the route names whose build appeared, changed or went (empty when nothing was
        read or nothing changed), which the caller treats as new providers (one that was resting stops).

        Concurrent callers share one read. When the read raises KeysUnavailable, what is wired stays as it was and
        the next read waits `refresh_s` again; logged `inference.keys_unreadable`. Each read that changed something
        logs `inference.keys` with the kinds wired and where each key came from (`connection` or `env`) and the
        count changed; never a key. Never raises."""
        if not self._due():
            return frozenset()
        async with self._lock:
            if not self._due():
                return frozenset()
            self._read_at = self._clock()
            try:
                keys = await self._keys.in_force()
            except KeysUnavailable:
                logs.warning(log, "inference.keys_unreadable")
                return frozenset()
            except Exception:
                logs.error(log, "inference.keys_unreadable", exc=True)
                return frozenset()
            return self._rebuild(keys)

    def _due(self) -> bool:
        return self._read_at is None or self._clock() - self._read_at >= self._refresh_s

    def _rebuild(self, keys: Mapping[str, KeyInForce]) -> frozenset[str]:
        """Each kind's build made to match `keys`; the route names whose build appeared, changed or went."""
        changed: set[str] = set()
        for kind, provider in self._keyed.items():
            key, had = keys.get(kind), self._in_force.get(kind)
            if (None if key is None else key.secret) == (None if had is None else had.secret):
                if key is not None:
                    self._in_force[kind] = key
                continue
            old = self._builds.pop(kind, None)
            if old is not None:
                self._retired.append(old)
            self._in_force.pop(kind, None)
            if key is not None:
                self._builds[kind] = provider.build(key.secret)
                self._in_force[kind] = key
            changed |= provider.names
        self._wired = {w.name: w for built in self._builds.values() for w in built.wired}
        if changed:
            logs.info(log, "inference.keys", changed=len(changed), sources=",".join(
                f"{kind}:{'env' if key.connection_id is None else 'connection'}"
                for kind, key in sorted(self._in_force.items())))
        return frozenset(changed)

    async def balance_sources(self) -> Mapping[str, BalanceSource]:
        """`balances` after `refresh`, for the spend page, so a rotated ElevenLabs key's quota is read with the new key."""
        await self.refresh()
        return self.balances()

    async def close(self) -> None:
        """Release every build this made: the current ones, the checkers, and each one a refresh replaced, which is
        kept open until now because a call already in flight may still be using its client."""
        builds = [*self._builds.values(), *self._retired, *self._checkers.values()]
        self._builds, self._retired, self._checkers, self._in_force, self._wired = {}, [], {}, {}, {}
        for built in builds:
            await built.close()
