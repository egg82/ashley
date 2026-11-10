"""The open benches `move_page` lists in main chat (`Catalogue.now`): id, title and kind of each, the one changed most
recently first; nothing when none is open or the Workshop cannot be read."""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ashley import services
from ashley.tools.move_page import MovePageTools
from ashley.workshop.model import Bench, Owner
from ashley.workshop.workshop import Workshop, WorkshopUnavailable
from bench_tools_support import FakeWorkshop

OWNER = Owner(10, 1)
NOW = datetime(2026, 11, 8, tzinfo=UTC)


@dataclass
class Benches(FakeWorkshop):
    benches: list[Bench] = field(default_factory=list[Bench])

    async def open_benches(self, owner: Owner) -> list[Bench]:
        if self.raises is not None:
            raise self.raises
        return self.benches


def listed() -> str | None:
    return asyncio.run(MovePageTools(OWNER.household_id, OWNER.person_id).catalogue()).now


def test_main_chat_lists_each_open_bench_with_id_and_title_the_latest_change_first() -> None:
    old = Bench(4, 10, 1, "Holder", NOW - timedelta(days=3), None, last_changed_at=NOW - timedelta(days=2), work="3d")
    new = Bench(9, 10, 1, "Shelves", NOW - timedelta(days=2), None, last_changed_at=NOW - timedelta(hours=1))
    services.register(Workshop, Benches(benches=[old, new]))
    text = listed()
    assert text is not None and '"bench_id": 4' in text and "Holder" in text and '"kind": "3d"' in text
    assert text.index("Shelves") < text.index("Holder")


def test_no_open_bench_or_an_unavailable_workshop_gives_no_list() -> None:
    services.register(Workshop, Benches())
    assert listed() is None
    services.register(Workshop, Benches(raises=WorkshopUnavailable()))
    assert listed() is None

