"""The keyed model providers wired now: a per-pod cache over `ProviderKeys`, never state. Losing it costs one read of
the keys; nothing in it is the only copy of anything.

A key added, rotated or removed in the connections room on any pod, on either site, reaches every pod's calls within
`refresh_s` (`REFRESH_S`, 30 seconds) with no restart: each call to `RoutedInference` first awaits `refresh`, which
reads the keys again once the last read is that old."""

import time
from collections.abc import Callable, Iterable, Mapping

from .balance import BalanceSource
from .keyed import KeyedProvider
from .provider import Wired
from .provider_keys import ProviderKeys

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
        raise NotImplementedError

    def names(self) -> frozenset[str]:
        """Every route name a build of these providers can carry, wired now or not."""
        raise NotImplementedError

    def checkers(self) -> Mapping[str, Wired]:
        """One provider per name in `names`, built with `PLACEHOLDER` for its key, so the routes' params can be checked
        at start for a provider whose key is not set yet (`ashley.inference.routes.load`). Never call one."""
        raise NotImplementedError

    def current(self) -> Mapping[str, Wired]:
        """The providers wired now, by route name: each build of a key in force at the last successful read (before
        any, the env's)."""
        raise NotImplementedError

    def balances(self) -> Mapping[str, BalanceSource]:
        """The balance sources of the builds in `current`, by provider name."""
        raise NotImplementedError

    async def refresh(self) -> frozenset[str]:
        """Read the keys again when the last read began `refresh_s` or more ago (or none has), and rebuild what changed:
        a kind whose key appeared or changed gets a new build, one whose key is gone is unwired, one whose key is the
        same keeps its build. Returns the route names whose build appeared, changed or went (empty when nothing was
        read or nothing changed), which the caller treats as new providers (one that was resting stops).

        Concurrent callers share one read. When the read raises KeysUnavailable, what is wired stays as it was and
        the next read waits `refresh_s` again; logged `inference.keys_unreadable`. Each read that changed something
        logs `inference.keys` with the kinds wired and where each key came from (`connection` or `env`) and the
        count changed; never a key. Never raises."""
        raise NotImplementedError

    async def balance_sources(self) -> Mapping[str, BalanceSource]:
        """`balances` after `refresh`, for the spend page, so a rotated ElevenLabs key's quota is read with the new key."""
        raise NotImplementedError

    async def close(self) -> None:
        """Release every build this made: the current ones, the checkers, and each one a refresh replaced, which is
        kept open until now because a call already in flight may still be using its client."""
        raise NotImplementedError
