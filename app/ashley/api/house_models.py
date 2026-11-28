"""The wire models of a person's house routes (`api.house`)."""

from pydantic import BaseModel


class HouseAttention(BaseModel):
    """What needs the person, each null when it cannot be read today and never false for that: `waiting_on_you` is how
    many of their open works only they can move (`GET /api/work`); `printer_faults` how many printers report a fault, null
    too when the household has no printing manager; `house_unreadable` whether the house did not answer, null when the
    household has no house."""

    waiting_on_you: int | None
    printer_faults: int | None
    house_unreadable: bool | None


class HouseGlance(BaseModel):
    """The house at a glance for a signed-in person. `home` is the first names of the household's people who are home:
    empty when everyone known is away, null when it cannot be known."""

    home: list[str] | None
    needs_attention: HouseAttention
