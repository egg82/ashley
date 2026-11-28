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


class HousePrinter(BaseModel):
    """One of the household's printers as its card shows it. `printer_id` is the printing manager's id for it (what
    `BroughtUp.ref` names), `name` what the household calls it, `printer_model` its model when known, `online` whether
    the manager can reach it. `state` is the printer's own word for what it is doing (`RUNNING`, `IDLE`, `PAUSE`,
    `FINISH`, `FAILED`), null when it says nothing, which is never idle. `print_name` is the print it is on, `percent` how
    far along (0 to 100), `minutes_left`, `layer` and `layers` where it is in it, each null with no print or when the
    printer does not say. `problems` are the faults it reports now, each its text or else its code."""

    printer_id: str
    name: str
    printer_model: str | None
    online: bool
    state: str | None
    print_name: str | None
    percent: float | None
    minutes_left: int | None
    layer: int | None
    layers: int | None
    problems: list[str]


class HousePrinters(BaseModel):
    """The household's printers for a signed-in person: empty when it has no printing manager, null when they cannot be
    read now (or there are more than one read holds), so a printer missing from them is unknown, never gone."""

    printers: list[HousePrinter] | None
