"""A job piece's body (kind `job`, format `job`): what the person sees of a bench job, written by code alone
(`ashley.channels.bench_job`). One JSON object of exactly `job` (the job's id, None until it is stored), `worker`,
`title`, `state`, `started`, `deadline` and `finished` (ISO times or None), `outputs` (the ids of the pieces it made
that are worth a look), `files_refused` (a count) and `reason` (a slug or None)."""

import json
from dataclasses import dataclass

from .automation_config import object_of
from .json_shape import list_of

_FIELDS = frozenset(("job", "worker", "title", "state", "started", "deadline", "finished", "outputs", "files_refused",
                     "reason"))
_TIMES = ("started", "deadline", "finished")


@dataclass(frozen=True)
class JobBody:
    job: int | None
    worker: str
    title: str
    state: str
    started: str | None
    deadline: str | None
    finished: str | None
    outputs: tuple[int, ...]
    files_refused: int
    reason: str | None


def body_of(body: JobBody) -> str:
    return json.dumps({"job": body.job, "worker": body.worker, "title": body.title, "state": body.state,
                       "started": body.started, "deadline": body.deadline, "finished": body.finished,
                       "outputs": list(body.outputs), "files_refused": body.files_refused, "reason": body.reason},
                      ensure_ascii=False, separators=(",", ":"))


def well_formed(body: str) -> bool:
    """Whether `body` is a job body of the shape above."""
    try:
        raw = object_of(json.loads(body))
    except ValueError:
        return False
    if raw is None or frozenset(raw) != _FIELDS:
        return False
    outputs, refused = list_of(raw["outputs"]), raw["files_refused"]
    return (_int_or_none(raw["job"]) and all(isinstance(raw[k], str) for k in ("worker", "title", "state"))
            and all(raw[k] is None or isinstance(raw[k], str) for k in (*_TIMES, "reason"))
            and outputs is not None and all(type(o) is int for o in outputs)
            and type(refused) is int and refused >= 0)


def _int_or_none(value: object) -> bool:
    return value is None or type(value) is int
