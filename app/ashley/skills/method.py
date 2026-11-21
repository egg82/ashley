"""A standing errand's method (`decisions.md`, "A standing errand is a repeating reminder that names her method"): the
household's kind of work a reminder follows, from whoever sets it, her `remind` tool or a person on the web."""

from .. import services
from .skills import SkillRefused, Skills


class NotAMethod(Exception):
    """The kind named is none of the household's with a method written; the message names the household's kinds."""

    def __init__(self, kinds: tuple[str, ...]) -> None:
        super().__init__("method is the name of one of the household's kinds of work that has a method: " + ", ".join(kinds))


async def named(household_id: int, raw: object) -> str | None:
    """The household's kind of work `raw` names, for a standing errand's method, when it has a method to follow; None
    when `raw` is None. Raises NotAMethod for anything else; SkillsUnavailable when the skills cannot be read."""
    if raw is None:
        return None
    skills = services.get(Skills)
    try:
        skill = await skills.current(household_id, raw) if isinstance(raw, str) else None
    except SkillRefused:
        skill = None
    if skill is not None and skill.body.strip():
        return skill.kind
    raise NotAMethod(tuple(k.kind for k in await skills.kinds(household_id)))
