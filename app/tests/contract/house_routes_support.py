"""Fakes for the tests of a person's house routes: a catalogue per household, a real `HouseTools` over an in-memory house
per household (so a press meets the tool's own checks), a printing manager and the work list, on top of the `kiosk`
fixture's app, sessions and presence."""

from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any

import httpx2
import pytest
from ashley import services
from ashley.api import house_attention
from ashley.channels.kiosk import house_controls
from ashley.connections.model import CatalogueEntity
from ashley.home_assistant import irreversible
from ashley.home_assistant.client import HomeAssistant
from ashley.home_assistant.homes import Home, Homes, HomesUnavailable
from ashley.printing.model import Fault, NotConnected, Page, Printer
from ashley.printing.printing import NullPrinting, Printing
from ashley.senses.outside_record import NullOutsideRecord, OutsideRecord
from ashley.signin.model import SignedIn
from ashley.tools import house_look_config, house_state_config
from ashley.tools.everyday import Everyday
from ashley.tools.house_act import Rules
from ashley.tools.house_tools import HouseTools
from ashley.tools.tools import Tools
from house_double_support import MemoryHouse, state
from ashley.people.model import Person
from kiosk_support import HOME, Kiosk, kiosk as kiosk
from ashley.api.work_models import WorkItem

OTHER_HOME = 8
OTHER = Person(5, OTHER_HOME, "Other")
CATALOGUE = [CatalogueEntity("light.zq_hall", "Hall", "light", None), CatalogueEntity("light.zq_porch_lamp", "Porch", "light", None),
             CatalogueEntity("scene.zq_night", "Night", "scene", None), CatalogueEntity("switch.zq_oven", "Oven", "switch", None),
             CatalogueEntity("lock.zq_front", "Front", "lock", None), CatalogueEntity("climate.zq_heat", "Heat", "climate", None)]


def house_of(*ids: str) -> MemoryHouse:
    return MemoryHouse(things=[state(i, i.split(".")[1], "off") for i in ids])


@dataclass
class FakeHomes(Homes):
    houses: dict[int, MemoryHouse] = field(default_factory=dict[int, MemoryHouse])
    down: bool = False

    async def of(self, household_id: int) -> Home | None:
        if self.down:
            raise HomesUnavailable("down")
        house = self.houses.get(household_id)
        return None if house is None else Home(household_id, HomeAssistant(httpx2.AsyncClient()), house)

    async def check(self, base_url: str, token: str) -> None:
        raise AssertionError("not used")


@dataclass
class FakeEveryday(Everyday):
    """Each household's own `HouseTools` over its house, under `rules`."""

    homes: FakeHomes
    rules: Rules
    asked: list[int] = field(default_factory=list[int])

    async def of(self, household_id: int) -> Tools:
        self.asked.append(household_id)
        return HouseTools(self.homes.houses[household_id], self.rules, house_look_config.load(), house_state_config.load(), "",
                          household_id)


@dataclass
class FakePrinting(NullPrinting):
    """`printers` answers `rows` (of a backend holding `total`), or raises `error`."""

    rows: tuple[Printer, ...] = ()
    total: int | None = None
    error: Exception | None = NotConnected()

    async def printers(self, household_id: int, limit: int) -> Page[Printer]:
        if self.error is not None:
            raise self.error
        return Page(self.rows, len(self.rows) if self.total is None else self.total)


def printer(name: str, *faults: str) -> Printer:
    return Printer(name, name, None, True, None, None, None, None, None, None, tuple(Fault(f, None) for f in faults), ())


class NeverRecorded(NullOutsideRecord):
    """A person's own press is nothing she did unasked: any record of an outside action is a failure."""

    async def done(self, action: Any) -> None:
        raise AssertionError("a person's press was recorded as an outside action")


@dataclass
class World:
    kiosk: Kiosk
    homes: FakeHomes
    everyday: FakeEveryday
    printing: FakePrinting
    catalogues: dict[int, list[CatalogueEntity]]
    waiting: list[WorkItem] | Exception
    patch: pytest.MonkeyPatch

    def get(self, path: str, person: int = 1, headers: dict[str, str] | None = None) -> Any:
        return self.kiosk.app.get(path, headers={"cookie": f"__Host-ashley_session=t-{person}", **(headers or {})})

    def post(self, path: str, person: int = 1, headers: dict[str, str] | None = None, body: Any = None) -> Any:
        from web_chat_support import JSON
        return self.kiosk.app.post(path, json={} if body is None else body, headers={
            **JSON, "cookie": f"__Host-ashley_session=t-{person}", **(headers or {})})

    def signed_in(self, person: Person) -> None:
        self.kiosk.sessions.by_token[f"t-{person.id}"] = SignedIn(100 + person.id, person)


def work_item(state_: str) -> WorkItem:
    return WorkItem.model_validate({"kind": "errand", "id": 1, "title": "t", "state": state_, "at": "2026-11-01T00:00:00Z"})


@pytest.fixture
def world(kiosk: Kiosk, monkeypatch: pytest.MonkeyPatch) -> Generator[World]:
    homes = FakeHomes({HOME: house_of("light.zq_hall", "light.zq_porch_lamp", "scene.zq_night", "switch.zq_oven"),
                       OTHER_HOME: house_of("light.zq_hall", "light.zq_other")})
    rules = Rules((), (), irreversible.load())
    everyday = FakeEveryday(homes, rules)
    catalogues = {HOME: list(CATALOGUE), OTHER_HOME: [CatalogueEntity("light.zq_hall", "Their hall", "light", None),
                                                      CatalogueEntity("light.zq_other", "Other", "light", None)]}
    printing = FakePrinting()
    w = World(kiosk, homes, everyday, printing, catalogues, [], monkeypatch)

    async def entities(household_id: int, person_id: int) -> list[CatalogueEntity]:
        return w.catalogues[household_id]

    async def open_work(owner: Any) -> list[WorkItem]:
        if isinstance(w.waiting, Exception):
            raise w.waiting
        return w.waiting

    monkeypatch.setattr(house_controls, "entities", entities)
    monkeypatch.setattr(house_attention, "open_work", open_work)
    w.signed_in(OTHER)
    for service, fake in ((Homes, homes), (Everyday, everyday), (Printing, printing), (OutsideRecord, NeverRecorded())):
        services.register(service, fake)
    try:
        yield w
    finally:
        for service in (Homes, Printing, OutsideRecord):
            services.unregister(service)
