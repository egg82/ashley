"""The pure half of a household's routes: what it may choose for each task, and its choices laid over the deployment's
routes data through the same loader path (`routes.overlay`, `routes.parse`). Contract: `household_routes`."""

from collections.abc import Mapping

from .model import DEFAULT_VARIANT, Route, Task
from .provider import Wired
from .route_choices import Choice
from .routes import TASKS, Routes, overlay, parse


def options(parsed: Routes) -> dict[Task, tuple[Route, ...]]:
    """For each task in `parsed.households`: its own routes in order, then those of the other household tasks (in
    `Task` order) whose provider and model are not already listed."""
    out: dict[Task, tuple[Route, ...]] = {}
    for task in _households(parsed):
        listed = list(parsed.by_task[task])
        for other in _households(parsed):
            listed += [r for r in parsed.by_task[other] if _find(listed, Choice(r.provider, r.model)) is None]
        out[task] = tuple(listed)
    return out


def offered(options: Mapping[Task, tuple[Route, ...]], task: Task, choice: Choice) -> Route | None:
    """The option of `task` that `choice` names; None when the task has none by that provider and model."""
    return _find(options.get(task, ()), choice)


def entries(parsed: Routes, chosen: Mapping[Task, Route]) -> dict[str, object]:
    """The household's layer as routes data: for each task with a chosen route, that route first and the task's
    deployment routes after it with it left out, keeping the task's flags."""
    out: dict[str, object] = {}
    for task, route in chosen.items():
        rest = [r for r in parsed.by_task[task] if r != route]
        flags: dict[str, object] = {"household": True}
        if task in parsed.waits_for_first:
            flags["fallback"] = False
        out[task] = {**flags, "routes": [_raw(r) for r in (route, *rest)]}
    return out


def layered(deployment: Mapping[str, object], checkers: Mapping[str, Wired], parsed: Routes,
            chosen: Mapping[Task, Route]) -> Routes:
    """The deployment's routes data with the household's layer over it, checked by `routes.parse` as the deployment's
    is. Raises ValueError as `parse`."""
    return parse(overlay(deployment, {"tasks": entries(parsed, chosen)}), checkers)


def _households(parsed: Routes) -> list[Task]:
    return [t for t in TASKS if t in parsed.households]


def _find(routes: list[Route] | tuple[Route, ...], choice: Choice) -> Route | None:
    return next((r for r in routes if r.provider == choice.provider and r.model == choice.model), None)


def _raw(route: Route) -> dict[str, object]:
    raw: dict[str, object] = {"provider": route.provider, "model": route.model, "timeout_s": route.timeout_s,
                              "params": dict(route.params)}
    if route.variant != DEFAULT_VARIANT:
        raw["variant"] = route.variant
    return raw
