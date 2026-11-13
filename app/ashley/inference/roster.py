"""What every task kind shares in `RoutedInference`: the wired providers by name, the routes, which providers are
resting, and the spend ledger with its one log line per call."""

import logging
import time
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping
from decimal import Decimal

from .. import logs
from .catalogue import ModelCatalogue
from .keyed_providers import KeyedProviders
from .model import Route, TaskName, Usage
from .provider import ProviderFailed, Wired
from .routes import Routes
from .spend import Call, Outcome, SpendLedger

log = logging.getLogger("ashley.inference")


class Roster:
    def __init__(self, routes: Routes, providers: Iterable[Wired], ledger: SpendLedger, catalogue: ModelCatalogue,
                 clock: Callable[[], float] = time.monotonic, keyed: KeyedProviders | None = None) -> None:
        self._providers: dict[str, Wired] = {}
        for provider in providers:
            if provider.name in self._providers or (keyed is not None and provider.name in keyed.names()):
                raise ValueError(f"two providers are named {provider.name!r}")
            self._providers[provider.name] = provider
        self._keyed = keyed
        self._routes = routes
        self._ledger = ledger
        self._catalogue = catalogue
        self.clock = clock
        self._resting_until: dict[str, float] = {}

    async def refresh(self) -> None:
        """The catalogue and the keyed providers brought up to date (`ModelCatalogue.refresh`,
        `KeyedProviders.refresh`); a keyed provider whose build changed stops resting."""
        await self._catalogue.refresh()
        if self._keyed is not None:
            for name in await self._keyed.refresh():
                self._resting_until.pop(name, None)

    def _provider(self, name: str) -> Wired | None:
        found = self._providers.get(name)
        return found if found is not None or self._keyed is None else self._keyed.current().get(name)

    def candidates[W: Wired](self, task: TaskName, kind: type[W], routes: Routes | None = None,
                             tools: bool = False) -> Iterator[tuple[Route, W]]:
        """The task's routes in order (from `routes`, the roster's own when None) whose provider is wired, can do
        `kind`'s work and is not resting, and, when the call offers `tools`, whose model the catalogue does not list
        as making no tool calls; each route passed over is logged `inference.route_skipped`. A provider that rests
        during the walk is skipped when reached."""
        for route in (self._routes if routes is None else routes).for_task(task):
            provider = self._provider(route.provider)
            refused = tools and self._refuses_tools(route)
            if isinstance(provider, kind) and self._clock_ok(route) and not refused:
                yield route, provider
                continue
            reason = ("unwired" if not isinstance(provider, kind) else "no_tool_calls" if refused else "resting")
            logs.info(log, "inference.route_skipped", task=task, provider=route.provider, model=route.model,
                      reason=reason)

    def _compatible(self, route: Route) -> tuple[bool, str | None]:
        """Whether the route names an OpenAI-compatible provider wired now, and the catalogue provider it is priced as."""
        priced_as: Mapping[str, str | None] = {} if self._keyed is None else self._keyed.catalogue_providers()
        return route.provider in priced_as, priced_as.get(route.provider)

    def _refuses_tools(self, route: Route) -> bool:
        compatible, listed = self._compatible(route)
        if compatible:
            return self._catalogue.priced().refuses_tools_in(listed, route.model)
        return self._catalogue.priced().refuses_tools(route.provider, route.model)

    def _cost(self, route: Route, usage: Usage) -> Decimal | None:
        """The call's cost; an OpenAI-compatible provider's from the catalogue provider its connection names, so one
        at a custom address is unpriced."""
        compatible, listed = self._compatible(route)
        if compatible:
            return self._catalogue.priced().cost_usd_in(listed, route.model, usage)
        return self._catalogue.priced().cost_usd(route.provider, route.model, usage)

    def _clock_ok(self, route: Route) -> bool:
        return self.clock() >= self._resting_until.get(route.provider, float("-inf"))

    def failed(self, route: Route, failure: Outcome) -> None:
        """A call to the route's provider produced `failure`: `unavailable` rests the provider."""
        if failure == "unavailable":
            self._resting_until[route.provider] = self.clock() + self._routes.cooldown_s

    async def warm(self, task: TaskName, route: Route, warming: Awaitable[None]) -> None:
        """Awaits `warming`, a provider's `warm` for `route`, and logs `inference.warm`; never raises."""
        started = self.clock()
        outcome: Outcome = "ok"
        reason: str | None = None
        try:
            await warming
        except ProviderFailed as e:
            outcome = e.failure
            reason = str(e)
        except Exception:
            outcome = "error"
            logs.error(log, "inference.warm_error", exc=True, provider=route.provider, model=route.model)
        logs.info(log, "inference.warm", task=task, provider=route.provider, model=route.model, outcome=outcome,
                  **_reason(reason), duration_ms=max(0, round((self.clock() - started) * 1000)))

    async def record(self, task: TaskName, route: Route, outcome: Outcome, usage: Usage | None, started: float,
                     fields: Mapping[str, object], conversation_id: int | None = None,
                     reason: str | None = None) -> None:
        """Logs `inference.call` and enters it in the ledger. `reason` is a failed call's `ProviderFailed` message."""
        duration_ms = max(0, round((self.clock() - started) * 1000))
        cost = None if usage is None else self._cost(route, usage)
        logs.info(log, "inference.call", task=task, provider=route.provider, model=route.model, outcome=outcome,
                  **_reason(reason), **fields, duration_ms=duration_ms)
        try:
            await self._ledger.record(Call(task, route.provider, route.model, outcome, usage, cost, duration_ms,
                                          conversation_id))
        except Exception:
            logs.error(log, "inference.spend_unrecorded", exc=True, task=task, provider=route.provider,
                       model=route.model, outcome=outcome)


def _reason(reason: str | None) -> dict[str, str]:
    return {} if reason is None else {"reason": reason}
