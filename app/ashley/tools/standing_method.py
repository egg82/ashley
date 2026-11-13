"""A standing errand's method on its turn (`channels.turn_tools`, for a turn whose `Inbound.method` is set): the
household's skill for that kind (`ashley.skills.skills.Skills.current`), read when the turn's catalogue is built and
placed in this source's instructions, beside the turn's tools' own in the stable part of the prompt, as a bench's skill
is (`bench_skills`). It offers no tool. When the skill cannot be read or has no body, the instructions say to carry
out nothing this time. `named` checks the kind a `remind` call names for a new standing errand. Logs `skills.loaded`
with the kind, version and length, or `skills.unavailable` with the kind; never the body."""

import logging

from .. import logs, services
from ..inference.model import ToolCall, ToolResult
from ..skills.skills import SkillRefused, Skills, SkillsUnavailable
from .bench_args import BadArguments
from .tools import Catalogue, Tools, ToolsUnavailable

log = logging.getLogger("ashley.skills")

UNREAD = ("This errand's method could not be read now. Carry out nothing for it this time, and set `says` to none.")


async def named(household_id: int, raw: object) -> str | None:
    """The household's kind of work `raw` names, for a standing errand's method, when it has a method to follow; None
    when `raw` is None. Raises BadArguments for anything else, naming the household's kinds; ToolsUnavailable when
    the skills cannot be read."""
    if raw is None:
        return None
    skills = services.get(Skills)
    try:
        try:
            skill = await skills.current(household_id, raw) if isinstance(raw, str) else None
        except SkillRefused:
            skill = None
        if skill is not None and skill.body.strip():
            return skill.kind
        kinds = await skills.kinds(household_id)
    except SkillsUnavailable as e:
        raise ToolsUnavailable("skills unavailable") from e
    raise BadArguments("method is the name of one of the household's kinds of work that has a method: "
                       + ", ".join(k.kind for k in kinds))


class StandingMethodTools(Tools):
    def __init__(self, household_id: int, kind: str) -> None:
        """For a turn of the household's standing errand whose method is the skill of `kind`."""
        self._household_id, self._kind = household_id, kind

    async def catalogue(self) -> Catalogue:
        try:
            skill = await services.get(Skills).current(self._household_id, self._kind)
        except (SkillsUnavailable, SkillRefused):
            skill = None
        if skill is None or not skill.body.strip():
            logs.warning(log, "skills.unavailable", kind=self._kind)
            return Catalogue((), UNREAD)
        logs.info(log, "skills.loaded", kind=self._kind, version=skill.version, chars=len(skill.body))
        return Catalogue((), f"# Method for this standing errand (skill {self._kind}, version {skill.version})\n\n"
                             f"{skill.body}")

    async def call(self, call: ToolCall) -> ToolResult:
        return ToolResult(call.id, f"no tool named {call.name}", is_error=True)
