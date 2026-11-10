"""The arguments of `bench_hand_off`, checked: one to `max_group` jobs, each a worker, a title, a brief and the pieces it
is given. Bounds are the parser's, not the schema's."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..errands.bench_jobs import WORKERS, Named, Worker
from ..errands.jobs_config import JobsConfig
from ..workshop.json_shape import list_of, object_of
from .bench_args import BadArguments

_KEYS = {"worker", "title", "brief", "pieces"}
_PIECE_KEYS = {"id", "run_files"}


@dataclass(frozen=True)
class Draft:
    worker: Worker
    title: str
    brief: str
    pieces: tuple[Named, ...]


def drafts(args: Mapping[str, object], config: JobsConfig, can_code: bool, title_max: int) -> tuple[Draft, ...]:
    """The jobs asked for. Raises BadArguments."""
    items = list_of(args.get("jobs"))
    if items is None:
        raise BadArguments("jobs is a list of jobs")
    if not 1 <= len(items) <= config.max_group:
        raise BadArguments(f"jobs is 1 to {config.max_group} jobs, not {len(items)}")
    return tuple(_draft(j, config, can_code, title_max) for j in items)


def _draft(raw: object, config: JobsConfig, can_code: bool, title_max: int) -> Draft:
    job = object_of(raw)
    if job is None:
        raise BadArguments("a job is an object of worker, title, brief and pieces")
    unknown = sorted(set(job) - _KEYS)
    if unknown:
        raise BadArguments(f"{unknown[0]} is not a field of a job")
    worker = _worker(job.get("worker"), can_code)
    title, brief = job.get("title"), job.get("brief")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= title_max:
        raise BadArguments(f"title is 1 to {title_max} characters")
    if not isinstance(brief, str) or not 1 <= len(brief.strip()) <= config.brief_chars:
        raise BadArguments(f"brief is 1 to {config.brief_chars} characters")
    return Draft(worker, title.strip(), brief.strip(), _pieces(job.get("pieces", [])))


def _worker(value: object, can_code: bool) -> Worker:
    allowed: Sequence[Worker] = WORKERS if can_code else ("agent",)
    for w in allowed:
        if value == w:
            return w
    raise BadArguments("worker is one of " + ", ".join(allowed))


def _pieces(raw: object) -> tuple[Named, ...]:
    listed = list_of(raw)
    if listed is None:
        raise BadArguments("pieces is a list of {id, run_files}")
    named: list[Named] = []
    for p in listed:
        piece = object_of(p)
        if piece is None:
            raise BadArguments("a piece is {id, run_files}")
        if set(piece) - _PIECE_KEYS or type(piece.get("id")) is not int or type(piece.get("run_files", False)) is not bool:
            raise BadArguments("a piece is {id: a whole number, run_files: true or false}")
        named.append(Named(int(str(piece["id"])), bool(piece.get("run_files", False))))
    if len({n.piece_id for n in named}) != len(named):
        raise BadArguments("a piece is named once")
    return tuple(named)
