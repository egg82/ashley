"""Shared setup for the household routes tests: a small deployment's routes data with three household tasks, and stored
choices that answer as told."""

from collections.abc import Mapping
from typing import Any

import pytest
from ashley.inference.model import Task
from ashley.inference.route_choices import Choice, RouteChoiceReads, RoutesUnavailable
from ashley.inference.routes import TASKS


def raw(provider: str, model: str, timeout_s: float = 10, **params: object) -> dict[str, object]:
    return {"provider": provider, "model": model, "timeout_s": timeout_s, "params": dict(params)}


def data() -> dict[str, Any]:
    """Every text task on alpha/m1, except: `command` (a household's) on beta/m1, `chat` (a household's) on alpha/m1
    then beta/m1, `brainstorm` (a household's) on alpha/m2 with a longer timeout, and `escalated` like `brainstorm`."""
    tasks: dict[str, object] = {t: [raw("alpha", "m1")] for t in TASKS}
    tasks["command"] = {"household": True, "routes": [raw("beta", "m1", 5)]}
    tasks["chat"] = {"household": True, "routes": [raw("alpha", "m1"), raw("beta", "m1")]}
    tasks["brainstorm"] = {"household": True, "routes": [raw("alpha", "m2", 60, depth="deep")]}
    tasks["escalated"] = {"like": "brainstorm"}
    return {"cooldown_s": 300, "tasks": tasks}


class Choices(RouteChoiceReads):
    """Answers `stored` (household -> task -> choice), `homes` (conversation -> household); raises RoutesUnavailable
    while `down`. Counts each read."""

    def __init__(self, stored: dict[int, dict[Task, Choice]] | None = None,
                 homes: dict[int, int] | None = None) -> None:
        self.stored = stored or {}
        self.homes = homes or {}
        self.down = False
        self.reads = 0
        self.lookups = 0

    async def all(self) -> Mapping[int, Mapping[Task, Choice]]:
        self.reads += 1
        if self.down:
            raise RoutesUnavailable("down (scripted)")
        return {h: dict(c) for h, c in self.stored.items()}

    async def of_household(self, household_id: int) -> Mapping[Task, Choice]:
        if self.down:
            raise RoutesUnavailable("down (scripted)")
        return dict(self.stored.get(household_id, {}))

    async def household_of(self, conversation_id: int) -> int | None:
        self.lookups += 1
        if self.down:
            raise RoutesUnavailable("down (scripted)")
        return self.homes.get(conversation_id)


def events(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, object]]:
    """The fields of each logged `event`, in order."""
    return [getattr(r, "fields", {}) for r in caplog.records if r.getMessage() == event]
