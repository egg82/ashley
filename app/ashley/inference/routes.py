"""Which models carry out each task, in order of preference: data (`routes.json`) tuned from real use,
so trying another provider, model, prompt variant or parameter is an edit to that file."""

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from importlib import resources
from typing import Any, get_args

from .embedding import EmbedTask
from .image import ImageTask
from .model import DEFAULT_VARIANT, Route, Task, TaskName
from .speech import SpeechTask
from .voiceprint import VoiceprintTask
from .provider import Provider, Wired
from .embed_provider import Embedder
from .image_provider import ImageMaker
from .speech_provider import Speaker, Transcriber
from .voiceprint_provider import VoiceEmbedder

TASKS: tuple[Task, ...] = get_args(Task)
SPEECH_TASKS: tuple[SpeechTask, ...] = get_args(SpeechTask)
EMBED_TASKS: tuple[EmbedTask, ...] = get_args(EmbedTask)
VOICEPRINT_TASKS: tuple[VoiceprintTask, ...] = get_args(VoiceprintTask)
IMAGE_TASKS: tuple[ImageTask, ...] = get_args(ImageTask)
_ROUTE_KEYS = {"provider", "model", "timeout_s", "variant", "params"}
_REQUIRED = ("provider", "model", "timeout_s")

NEVER_HOUSEHOLD: frozenset[Task] = frozenset({"action_judge"})
"""Text tasks no household may choose a model for, whatever the routes data says: `action_judge` is a safety check, and
a weaker model there weakens the check that guards the household itself. Only the operator's `ROUTES_FILE` moves it."""


@dataclass(frozen=True)
class Routes:
    """Every text task has at least one route; a speech, embed or voiceprint task has routes when `routes.json` lists
    it, so a process that never speaks needs none. A provider that failed `unavailable` rests for `cooldown_s` (> 0).
    `waits_for_first` names the text tasks whose entry says `"fallback": false`: the app runs them on their first
    route only (`without_fallback`), while the list stays whole for an eval to pin. `households` names the text tasks
    whose entry says `"household": true`: a household may choose which model carries them
    (`ashley.inference.household_routes`); never a task in `NEVER_HOUSEHOLD`."""

    by_task: Mapping[Task, tuple[Route, ...]]
    cooldown_s: float
    speech: Mapping[SpeechTask, tuple[Route, ...]] = field(default_factory=dict[SpeechTask, tuple[Route, ...]])
    embed: Mapping[EmbedTask, tuple[Route, ...]] = field(default_factory=dict[EmbedTask, tuple[Route, ...]])
    voiceprint: Mapping[VoiceprintTask, tuple[Route, ...]] = field(
        default_factory=dict[VoiceprintTask, tuple[Route, ...]])
    image: Mapping[ImageTask, tuple[Route, ...]] = field(default_factory=dict[ImageTask, tuple[Route, ...]])
    waits_for_first: frozenset[Task] = frozenset()
    households: frozenset[Task] = frozenset()

    def for_task(self, task: TaskName) -> tuple[Route, ...]:
        """The task's routes in order; none for a speech, embed or voiceprint task the routes do not list."""
        return {**self.by_task, **self.speech, **self.embed, **self.voiceprint, **self.image}.get(task, ())


class PinError(ValueError):
    """`only` was asked for a provider the task has no route for."""


def only(routes: Routes, task: Task, provider: str) -> Routes:
    """`routes` with `task`'s list narrowed to the entries naming `provider`, in order; other tasks untouched.
    Raises PinError naming the providers the task does have."""
    kept = tuple(r for r in routes.by_task[task] if r.provider == provider)
    if not kept:
        have = sorted({r.provider for r in routes.by_task[task]})
        raise PinError(f"{task} has no route for provider {provider!r}; it has {have}")
    return replace(routes, by_task={**routes.by_task, task: kept})


def without_fallback(routes: Routes) -> Routes:
    """`routes` with each task in `waits_for_first` narrowed to its first route, for a task that waits for its
    preferred model rather than take the fallback; other tasks untouched."""
    return replace(routes, by_task={task: r[:1] if task in routes.waits_for_first else r
                                    for task, r in routes.by_task.items()})


def load(providers: Mapping[str, Wired], routes_file: str = "") -> Routes:
    """The routes shipped in `routes.json` beside this module, checked against `providers` (`parse`). A non-empty
    `routes_file` is the operator's overlay of them (`overlay`); anything wrong with it, or with the routes it makes,
    is a ValueError naming ROUTES_FILE."""
    data = deployment(routes_file)
    if not routes_file:
        return parse(data, providers)
    try:
        return parse(data, providers)
    except ValueError as e:
        raise ValueError(f"ROUTES_FILE {routes_file}: {e}") from e


def deployment(routes_file: str = "") -> dict[str, object]:
    """The deployment's routes data before it is checked: `routes.json` beside this module with the operator's
    `routes_file` over it (`overlay`) when non-empty. What `load` parses, and what a household's choices are laid over.
    Raises ValueError naming ROUTES_FILE when that file cannot be read or overlaid."""
    shipped = json.loads(resources.files("ashley.inference").joinpath("routes.json").read_text())
    if not routes_file:
        return shipped
    try:
        with open(routes_file) as f:
            return overlay(shipped, json.load(f))
    except (OSError, ValueError) as e:
        raise ValueError(f"ROUTES_FILE {routes_file}: {e}") from e


def overlay(shipped: Mapping[str, object], operator: object) -> dict[str, object]:
    """The shipped routes data with an operator's over it: `{"cooldown_s"?: n, "tasks"?: {...}}`. Each task in
    the overlay replaces that task's whole entry; tasks it leaves out, and an absent `cooldown_s`, stay shipped.
    Neither input is changed, and the result is checked by `parse`, not here."""
    fields = _object(operator)
    if fields is None or not set(fields) <= {"cooldown_s", "tasks"}:
        raise ValueError('routes overlay: expected an object with only "cooldown_s" and "tasks"')
    tasks = _object(fields.get("tasks", {}))
    if tasks is None:
        raise ValueError("routes overlay: tasks is an object with an entry per task to replace")
    kept = _object(shipped["tasks"]) or {}
    return {"cooldown_s": fields.get("cooldown_s", shipped["cooldown_s"]), "tasks": {**kept, **tasks}}


def parse(data: object, providers: Mapping[str, Wired]) -> Routes:
    """Routes from JSON already parsed:
    `{"cooldown_s": n, "tasks": {"<task>": [{"provider": s, "model": s, "timeout_s": n, "variant"?: s,
    "params"?: {...}}, ...]}}`, one entry per text task (`{"like": "<task>"}` in place of the list takes that task's
    routes, which must be a list; `{"routes": [...], "fallback": false}` in place of the list is a text task that
    waits for its first route, see `Routes.waits_for_first`; `{"routes": [...], "household": true}` is a text task a
    household may choose for, see `Routes.households`, and both flags may be given together; `"household": true` on a
    task in `NEVER_HOUSEHOLD` is a ValueError), optionally one per speech task and one each for `embed`, `voiceprint` and `image`, and no others,
    each with at least one route and no keys beyond those. Numbers are finite and > 0 (a bool is not a number); strings are non-empty.

    A route naming a provider absent from `providers` is kept: it is skipped at call time, so routes may list a
    provider before its key exists. A route naming a present provider has its params checked by that provider's
    `check_params` (`check_transcribe_params`, `check_speak_params`, `check_embed_params`, `check_voiceprint_params`, `check_image_params` for the other tasks). A present
    provider that cannot do the route's task (a text task needs a `Provider`, `transcribe` a `Transcriber`, `speak` a
    `Speaker`, `embed` an `Embedder`, `voiceprint` a `VoiceEmbedder`, `image` an `ImageMaker`)
    is a ValueError. Raises ValueError naming the task and route index of what is wrong."""
    top = _object(data)
    if top is None or set(top) != {"cooldown_s", "tasks"}:
        raise ValueError("routes: expected exactly cooldown_s and tasks")
    cooldown = _positive("cooldown_s", top["cooldown_s"])
    tasks = _object(top["tasks"])
    if tasks is None:
        raise ValueError("routes: tasks is an object with one entry per task")
    tasks = _likened(tasks)
    tasks, waits, households = _unwrapped(tasks)
    missing = [k for k in TASKS if k not in tasks]
    extra = sorted(set(tasks) - set(TASKS) - set(SPEECH_TASKS) - set(EMBED_TASKS) - set(VOICEPRINT_TASKS) - set(IMAGE_TASKS))
    if missing or extra:
        raise ValueError(f"routes tasks: missing {missing}, unknown {extra}")
    return Routes({task: _routes_of(task, tasks[task], providers) for task in TASKS}, cooldown,
                  {task: _routes_of(task, tasks[task], providers) for task in SPEECH_TASKS if task in tasks},
                  {task: _routes_of(task, tasks[task], providers) for task in EMBED_TASKS if task in tasks},
                  {task: _routes_of(task, tasks[task], providers) for task in VOICEPRINT_TASKS if task in tasks},
                  {task: _routes_of(task, tasks[task], providers) for task in IMAGE_TASKS if task in tasks},
                  waits, households)


def _unwrapped(tasks: dict[str, object]) -> tuple[dict[str, object], frozenset[Task], frozenset[Task]]:
    """`tasks` with each `{"routes": [...], "fallback": false, "household": true}` entry (either flag or both)
    replaced by its list, and the text tasks that said each flag."""
    plain: dict[str, object] = {}
    waits: set[Task] = set()
    households: set[Task] = set()
    for task, entry in tasks.items():
        fields = _object(entry)
        if fields is None or "routes" not in fields:
            plain[task] = entry
            continue
        flags = set(fields) - {"routes"}
        if (not flags or not flags <= {"fallback", "household"} or fields.get("fallback", False) is not False
                or fields.get("household", True) is not True):
            raise ValueError(f'{task}: expected "routes" with "fallback": false, "household": true or both in place '
                             "of the list")
        if task not in TASKS:
            raise ValueError(f"{task}: only a text task can wait for its first route or be a household's")
        if "household" in flags and task in NEVER_HOUSEHOLD:
            raise ValueError(f"{task}.household: no household chooses the model for {task}")
        plain[task] = fields["routes"]
        waits |= {task} if "fallback" in flags else set()
        households |= {task} if "household" in flags else set()
    return plain, frozenset(waits), frozenset(households)


def _likened(tasks: dict[str, object]) -> dict[str, object]:
    """`tasks` with each `{"like": "<task>"}` entry replaced by the routes of the task it names, which lists its own
    routes (a list, or one in `"routes"`), so one list is kept in one place. Its flags are not taken."""
    resolved: dict[str, object] = {}
    for task, entry in tasks.items():
        fields = _object(entry)
        if fields is None or set(fields) != {"like"}:
            resolved[task] = entry
            continue
        like = fields["like"]
        listed = _listed(tasks.get(like)) if isinstance(like, str) else None
        if listed is None:
            raise ValueError(f"{task}.like: expected the name of a task that lists its own routes")
        resolved[task] = listed
    return resolved


def _listed(entry: object) -> object | None:
    """The route list an entry holds, itself or in `"routes"`; None when it holds none."""
    fields = _object(entry)
    inner = entry if fields is None else fields.get("routes")
    return inner if _is_list(inner) else None


def _routes_of(task: str, entries: object, providers: Mapping[str, Wired]) -> tuple[Route, ...]:
    items = _list(entries)
    if not items:
        raise ValueError(f"{task}: expected a non-empty list of routes")
    return tuple(_route(task, f"{task}[{i}]", item, providers) for i, item in enumerate(items))


def _route(task: str, where: str, entry: object, providers: Mapping[str, Wired]) -> Route:
    fields = _object(entry)
    if fields is None:
        raise ValueError(f"{where}: expected an object")
    unknown = sorted(set(fields) - _ROUTE_KEYS)
    absent = [k for k in _REQUIRED if k not in fields]
    if unknown or absent:
        raise ValueError(f"{where}: missing {absent}, unknown {unknown}")
    params = _object(fields.get("params", {}))
    if params is None:
        raise ValueError(f"{where}.params: expected an object")
    route = Route(
        provider=_text(f"{where}.provider", fields["provider"]),
        model=_text(f"{where}.model", fields["model"]),
        timeout_s=_positive(f"{where}.timeout_s", fields["timeout_s"]),
        variant=_text(f"{where}.variant", fields.get("variant", DEFAULT_VARIANT)),
        params=params,
    )
    provider = providers.get(route.provider)
    if provider is not None:
        try:
            _check_params(task, provider, params)
        except ValueError as e:
            raise ValueError(f"{where}.params: {e}") from e
    return route


def _check_params(task: str, provider: Wired, params: Mapping[str, object]) -> None:
    if task == "transcribe" and isinstance(provider, Transcriber):
        provider.check_transcribe_params(params)
    elif task == "speak" and isinstance(provider, Speaker):
        provider.check_speak_params(params)
    elif task == "embed" and isinstance(provider, Embedder):
        provider.check_embed_params(params)
    elif task == "voiceprint" and isinstance(provider, VoiceEmbedder):
        provider.check_voiceprint_params(params)
    elif task == "image" and isinstance(provider, ImageMaker):
        provider.check_image_params(params)
    elif (task not in SPEECH_TASKS and task not in EMBED_TASKS and task not in VOICEPRINT_TASKS
          and task not in IMAGE_TASKS and isinstance(provider, Provider)):
        provider.check_params(params)
    else:
        raise ValueError(f"provider {provider.name!r} cannot do task {task}")


def _object(value: object) -> dict[str, object] | None:
    raw: Any = value
    if not hasattr(raw, "keys") or not all(type(key) is str for key in raw.keys()):
        return None
    return dict[str, object](raw)


def _text(where: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: expected a non-empty string")
    return value


def _positive(where: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{where}: expected a finite number above 0")
    return float(value)


def _list(value: object) -> list[object]:
    """The items of a JSON array, empty when `value` is not one."""
    raw: Any = value
    return list[object](raw) if _is_list(value) else []


def _is_list(value: object) -> bool:
    return isinstance(value, list)
