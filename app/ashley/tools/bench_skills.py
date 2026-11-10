"""Her skill tools on one bench, for one turn of its talk (`channels.turn_tools`): set the bench's kind of work, read,
edit and roll back the household's skill for a kind (`skills.skills.Skills`). The skill of the bench's kind is part of
this source's instructions, so it sits beside the bench tools' own in the stable part of the prompt. It is read when
the turn's catalogue is built, so a kind she sets or an edit she makes reaches the prompt of the person's next message;
within the turn, setting a kind gives her the skill as the tool's result. Arguments, bodies and notes are never logged;
the kind, version and status are."""

import logging
import time
from collections.abc import Mapping

from .. import logs, services
from ..inference.model import ToolCall, ToolResult
from ..skills.skills import Skill, SkillRefused, Skills, SkillsUnavailable, Version
from ..workshop.model import Owner
from ..workshop.workshop import BenchNotFound, Workshop, WorkshopUnavailable
from . import bench_results
from .bench_args import BadArguments, check_names
from .bench_skill_specs import EDIT, NONE, READ, WORK, guidance, specs
from .tools import Catalogue, Tools

log = logging.getLogger("ashley.skills")

HINTS: Mapping[str, str] = {
    "unknown_kind": "that is not a kind of this household's; bench_work with a label starts one",
    "bad_kind": "a kind is a short lowercase name of letters, digits and hyphens, and its label a short name",
    "bad_body": "a skill body is not empty and not longer than the skills allow",
    "bad_note": "what and why are each a short line, not empty",
    "unchanged": "that is the text the skill has now",
    "stale": "the skill changed since you read it: skill_read it again and redo the edit on what is there now",
    "no_such_version": "no live version with that number (0 is the seed, when the kind has one)",
    "not_proposed": "that version is not waiting for approval",
}


def _text(args: Mapping[str, object], name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str):
        raise BadArguments(f"{name} is a string")
    return value


def _number(args: Mapping[str, object], name: str) -> int:
    value = args.get(name)
    if type(value) is not int:
        raise BadArguments(f"{name} is a whole number")
    return value


class BenchSkillTools(Tools):
    def __init__(self, household_id: int, person_id: int, bench_id: int) -> None:
        self._owner = Owner(household_id, person_id)
        self._bench = bench_id
        self._specs = specs()

    async def catalogue(self) -> Catalogue:
        """The tools, and their guidance followed by the bench's skill when it has a kind of work with a skill. When
        the bench or the skills cannot be read, the guidance alone, logged `skills.unavailable`."""
        try:
            skills = services.get(Skills)
            labels = {k.kind: k.label for k in await skills.kinds(self._owner.household_id)}
            text = guidance(labels)
            kind = (await services.get(Workshop).read(self._owner, self._bench)).bench.work
            skill = None if kind is None else await skills.current(self._owner.household_id, kind)
        except (WorkshopUnavailable, SkillsUnavailable, BenchNotFound, SkillRefused):
            logs.warning(log, "skills.unavailable", bench=self._bench)
            return Catalogue(self._specs, guidance({}))
        if kind is not None and skill is not None and skill.body:
            logs.info(log, "skills.loaded", bench=self._bench, kind=kind, version=skill.version, chars=len(skill.body))
            text = f"{text}\n\n{self._loaded(skill, labels.get(kind, kind))}"
        return Catalogue(self._specs, text)

    def _loaded(self, skill: Skill, label: str) -> str:
        head = f"# Method for {label} work (skill {skill.kind}, version {skill.version})"
        waiting = skill.proposal
        note = "" if waiting is None else f"\nYour version {waiting.version} of it waits for the person's approval."
        return f"{head}{note}\n\n{skill.body}"

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises for what the bench, the skills or the model did: each is an error result, logged `tools.call`."""
        started = time.monotonic()
        spec = next((s for s in self._specs if s.name == call.name), None)
        if spec is None:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        try:
            check_names(call.arguments, spec)
            return await self._run(call, started)
        except BadArguments as e:
            return bench_results.failed(call, started, "bad_arguments", str(e), bench=self._bench)
        except SkillRefused as e:
            return bench_results.failed(call, started, e.reason, HINTS[e.reason], bench=self._bench)
        except ValueError:
            return bench_results.failed(call, started, "bad_text", bench_results.BAD_TEXT_HINT, bench=self._bench)
        except BenchNotFound:
            return bench_results.failed(call, started, "not_found", "this bench is gone", bench=self._bench)
        except (WorkshopUnavailable, SkillsUnavailable):
            return bench_results.failed(call, started, "unavailable", "the skills cannot be reached right now; "
                                        "nothing changed", bench=self._bench)

    async def _run(self, call: ToolCall, started: float) -> ToolResult:
        if call.name == WORK:
            return await self._work(call, started)
        kind = await self._kind(call.arguments)
        if call.name == READ:
            return await self._read(call, started, kind)
        if call.name == EDIT:
            return await self._edit(call, started, kind)
        return await self._rollback(call, started, kind)

    async def _kind(self, args: Mapping[str, object]) -> str:
        """The `kind` argument, else the bench's kind of work."""
        if "kind" in args:
            return _text(args, "kind")
        work = (await services.get(Workshop).read(self._owner, self._bench)).bench.work
        if work is None:
            raise BadArguments("kind is a kind of work; this bench has none, so name one")
        return work

    async def _work(self, call: ToolCall, started: float) -> ToolResult:
        work = _text(call.arguments, "work")
        kind = None if work == NONE else work
        if kind is not None:
            await self._start(kind, call.arguments.get("label"))
        await services.get(Workshop).set_work(self._owner, self._bench, kind)
        skill = await self._method(kind)
        body: dict[str, object] = {"work": kind}
        if skill is not None:
            body["method"] = {"version": skill.version, "text": skill.body}
        return bench_results.ok(call, started, body, bench=self._bench, kind=work,
                                version=None if skill is None else skill.version)

    async def _start(self, kind: str, label: object) -> None:
        """Makes `kind` one of the household's when it is not: `label` names it. Raises BadArguments without one."""
        skills = services.get(Skills)
        if kind in {k.kind for k in await skills.kinds(self._owner.household_id)}:
            return
        if not isinstance(label, str):
            raise BadArguments("work is not a kind of this household's; label names a new one")
        await skills.add_kind(self._owner.household_id, kind, label)

    async def _method(self, kind: str | None) -> Skill | None:
        """The skill of `kind` for the result of setting it; None when there is none or it cannot be read now."""
        try:
            return None if kind is None else await services.get(Skills).current(self._owner.household_id, kind)
        except SkillsUnavailable:
            return None

    async def _read(self, call: ToolCall, started: float, kind: str) -> ToolResult:
        skills = services.get(Skills)
        skill = await skills.current(self._owner.household_id, kind)
        changelog = await skills.changelog(self._owner.household_id, kind)
        body: dict[str, object] = {
            "kind": kind, "version": 0 if skill is None else skill.version, "edits": 0 if skill is None else skill.edits,
            "pinned": skill is not None and skill.pinned, "seeded_from": None if skill is None else skill.seeded_from,
            "body": None if skill is None else skill.body, "changelog": [_entry(v) for v in changelog]}
        return bench_results.ok(call, started, body, bench=self._bench, kind=kind, count=len(changelog))

    async def _edit(self, call: ToolCall, started: float, kind: str) -> ToolResult:
        args = call.arguments
        made = await services.get(Skills).edit(
            self._owner.household_id, kind, _text(args, "body"), _text(args, "what"), _text(args, "why"),
            _number(args, "base_version"), self._bench, None)
        body: dict[str, object] = {"kind": kind, "version": made.version, "status": made.status}
        if made.status == "proposed":
            body["waiting_on"] = "the person's approval: the skill is pinned"
        return bench_results.ok(call, started, body, bench=self._bench, kind=kind, version=made.version,
                                status=made.status)

    async def _rollback(self, call: ToolCall, started: float, kind: str) -> ToolResult:
        made = await services.get(Skills).rollback(
            self._owner.household_id, kind, _number(call.arguments, "to_version"), _text(call.arguments, "why"),
            self._bench, None)
        body: dict[str, object] = {"kind": kind, "version": made.version, "status": made.status}
        if made.status == "proposed":
            body["waiting_on"] = "the person's approval: the skill is pinned"
        return bench_results.ok(call, started, body, bench=self._bench, kind=kind, version=made.version,
                                status=made.status)


def _entry(v: Version) -> Mapping[str, object]:
    return {"version": v.version, "status": v.status, "what": v.what, "why": v.why,
            "by": "ashley" if v.person_id is None else "person", "restored_from": v.restored_from}
