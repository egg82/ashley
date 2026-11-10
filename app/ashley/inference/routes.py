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


@dataclass(frozen=True)
class Routes:
    """Every text task has at least one route; a speech, embed or voiceprint task has routes when `routes.json` lists
    it, so a process that never speaks needs none. A provider that failed `unavailable` rests for `cooldown_s` (> 0)."""

    by_task: Mapping[Task, tuple[Route, ...]]
    cooldown_s: float
    speech: Mapping[SpeechTask, tuple[Route, ...]] = field(default_factory=dict[SpeechTask, tuple[Route, ...]])
    embed: Mapping[EmbedTask, tuple[Route, ...]] = field(default_factory=dict[EmbedTask, tuple[Route, ...]])
    voiceprint: Mapping[VoiceprintTask, tuple[Route, ...]] = field(
        default_factory=dict[VoiceprintTask, tuple[Route, ...]])
    image: Mapping[ImageTask, tuple[Route, ...]] = field(default_factory=dict[ImageTask, tuple[Route, ...]])

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


def first_only(routes: Routes, task: Task) -> Routes:
    """`routes` with `task` narrowed to its first route, for a task that waits for its preferred model rather than
    take the fallback; other tasks untouched."""
    return replace(routes, by_task={**routes.by_task, task: routes.by_task[task][:1]})


def load(providers: Mapping[str, Wired]) -> Routes:
    """The routes shipped in `routes.json` beside this module, checked against `providers` (`parse`)."""
    return parse(json.loads(resources.files("ashley.inference").joinpath("routes.json").read_text()), providers)


def parse(data: object, providers: Mapping[str, Wired]) -> Routes:
    """Routes from JSON already parsed:
    `{"cooldown_s": n, "tasks": {"<task>": [{"provider": s, "model": s, "timeout_s": n, "variant"?: s,
    "params"?: {...}}, ...]}}`, one entry per text task (`{"like": "<task>"}` in place of the list takes that task's
    routes, which must be a list), optionally one per speech task and one each for `embed`, `voiceprint` and `image`, and no others,
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
    missing = [k for k in TASKS if k not in tasks]
    extra = sorted(set(tasks) - set(TASKS) - set(SPEECH_TASKS) - set(EMBED_TASKS) - set(VOICEPRINT_TASKS) - set(IMAGE_TASKS))
    if missing or extra:
        raise ValueError(f"routes tasks: missing {missing}, unknown {extra}")
    return Routes({task: _routes_of(task, tasks[task], providers) for task in TASKS}, cooldown,
                  {task: _routes_of(task, tasks[task], providers) for task in SPEECH_TASKS if task in tasks},
                  {task: _routes_of(task, tasks[task], providers) for task in EMBED_TASKS if task in tasks},
                  {task: _routes_of(task, tasks[task], providers) for task in VOICEPRINT_TASKS if task in tasks},
                  {task: _routes_of(task, tasks[task], providers) for task in IMAGE_TASKS if task in tasks})


def _likened(tasks: dict[str, object]) -> dict[str, object]:
    """`tasks` with each `{"like": "<task>"}` entry replaced by the routes of the task it names, which is a list of
    routes itself, so one list is kept in one place."""
    resolved: dict[str, object] = {}
    for task, entry in tasks.items():
        fields = _object(entry)
        if fields is None or set(fields) != {"like"}:
            resolved[task] = entry
            continue
        like = fields["like"]
        if not isinstance(like, str) or not isinstance(tasks.get(like), list):
            raise ValueError(f"{task}.like: expected the name of a task that lists its own routes")
        resolved[task] = tasks[like]
    return resolved


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
