"""A PUT of the Devices room whose read went stale between the read and the Command (another edit, or the piece's removal,
landed first) is refused 409 `stale` by the Workshop's decision, whatever the route saw."""

from ashley import services
from ashley.workshop.commands import Remove
from ashley.workshop.model import By
from ashley.workshop.workshop import Applied, NullWorkshop, ScreenCommand, ScreenView, Workshop
from conn_settings_blind_support import People
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from test_cs_device_controls import HALL, PORCH, client as client, device, people as people, put


class Behind(NullWorkshop):
    """The real Workshop, whose `screen` answers the view taken earlier."""

    def __init__(self, real: Workshop, seen: ScreenView) -> None:
        self.real, self.seen = real, seen

    async def screen(self, household_id: int, device_id: int) -> ScreenView:
        return self.seen

    async def apply_screen(self, household_id: int, device_id: int, command: ScreenCommand) -> Applied:
        return await self.real.apply_screen(household_id, device_id, command)


def seen_then(client: TestClient, people: People, mine: int, later: str) -> Workshop:
    """The Workshop wrapped to show the screen as it was before `later` happened to it."""
    real = services.get(Workshop)
    assert client.portal is not None
    before = client.portal.call(real.screen, people.home, mine)
    if later == "edit":
        assert put(client, mine, PORCH).status_code == 200
    else:
        removal = Remove(By(people.alana), next(p.id for p in before.pieces if p.kind == "controls"))
        assert client.portal.call(real.apply_screen, people.home, mine, removal).outcome == "accepted"
    services.register(Workshop, Behind(real, before))
    return real


def test_an_edit_decided_stale_by_the_workshop_is_409_stale(client: TestClient, db_url: str, people: People) -> None:
    mine = device(db_url, people.home, "tok-a")
    assert put(client, mine, HALL).status_code == 200
    real = seen_then(client, people, mine, "edit")
    try:
        got = put(client, mine, HALL, base=2)
    finally:
        services.register(Workshop, real)
    assert got.status_code == 409 and got.json()["code"] == "stale", got.text


def test_an_edit_of_a_piece_taken_off_meanwhile_is_409_stale(client: TestClient, db_url: str, people: People) -> None:
    mine = device(db_url, people.home, "tok-a")
    assert put(client, mine, HALL).status_code == 200
    real = seen_then(client, people, mine, "remove")
    try:
        got = put(client, mine, PORCH, base=2)
    finally:
        services.register(Workshop, real)
    assert got.status_code == 409 and got.json()["code"] == "stale", got.text
