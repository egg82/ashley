"""A queued print taken back out: `printing_cancel` through `PrintQueueTools` and the Bambuddy adapter against the fake
Bambuddy, and the board's Cancel, `POST /api/work/actions/{id}/undo` on a `print_cancel` action, through the real app and
database. A print nobody has started leaves the queue; one already started, cancelled or unknown is `gone` and nothing
changes; wrong arguments ask Bambuddy nothing; a key that may not change the queue is `refused`, and the board offers
the Cancel again."""

import asyncio
import json
from collections.abc import Generator, Iterator

import pytest
from ashley import services
from ashley.api.person import SESSION_COOKIE
from ashley.api.work_models import WorkItem, WorkResponse
from ashley.bambuddy.client import Bambuddy
from ashley.bambuddy.printing import BambuddyPrinting
from ashley.connections.connections import Connections
from ashley.inference.model import ToolCall, ToolResult
from ashley.main import create_app
from ashley.printing.printing import Printing
from ashley.settings import Settings
from ashley.tools import printing_config
from ashley.tools.printing_queue import PrintQueueTools
from ashley.tools.printing_queue_specs import CANCEL, QUEUE
from ashley.tools.undo_carry import Carried, carry
from ashley.undo import Undo
from bambuddy_support import BASE, KEY, KIND, FakeBambuddy
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template, scalar
from fastapi.testclient import TestClient
from money_support import HeldConnections
from test_work_undo import PUBLIC, World, world as world

HOME = 10
ASK: dict[str, object] = {"file_id": "2", "printer_id": "1"}


def connected(household: int) -> HeldConnections:
    found = HeldConnections()
    found.connect(household, BASE, KEY, KIND)
    return found


def wired(household: int) -> FakeBambuddy:
    fake = FakeBambuddy()
    services.register(Connections, connected(household))
    services.register(Bambuddy, fake.client())
    services.register(Printing, BambuddyPrinting())
    return fake


@pytest.fixture
def fake() -> Iterator[FakeBambuddy]:
    yield wired(HOME)


def called(name: str, household: int = HOME, **arguments: object) -> ToolResult:
    return given(name, arguments, household)


def given(name: str, arguments: dict[str, object], household: int = HOME) -> ToolResult:
    return asyncio.run(PrintQueueTools(household, printing_config.load()).call(ToolCall("c1", name, arguments)))


def outcome(result: ToolResult) -> object:
    assert not result.is_error, result.content
    return json.loads(result.content)["outcome"]


def queued(household: int = HOME) -> str:
    done = called(QUEUE, household, **ASK)
    assert done.undo is not None and done.undo.kind == "print_cancel"
    return done.undo.ref


def test_a_print_nobody_has_started_leaves_the_queue(fake: FakeBambuddy) -> None:
    item = queued()
    assert outcome(called(CANCEL, item_id=item)) == "cancelled"
    assert fake.states[int(item)] == "cancelled"
    assert fake.seen[-1][0] == f"/api/v1/queue/{item}/cancel"


@pytest.mark.parametrize("state", ["printing", "completed", "cancelled"])
def test_a_print_already_started_or_over_is_gone_and_unchanged(fake: FakeBambuddy, state: str) -> None:
    item = queued()
    fake.states[int(item)] = state
    assert outcome(called(CANCEL, item_id=item)) == "gone"
    assert fake.states[int(item)] == state


def test_an_entry_bambuddy_does_not_have_is_gone(fake: FakeBambuddy) -> None:
    assert outcome(called(CANCEL, item_id="999")) == "gone"


@pytest.mark.parametrize("arguments", [{}, {"item_id": 101}, {"item_id": "x1"}, {"item_id": ""}, {"item_id": "1" * 13}])
def test_wrong_arguments_ask_bambuddy_nothing(fake: FakeBambuddy, arguments: dict[str, object]) -> None:
    got = given(CANCEL, arguments)
    assert got.is_error and got.content.startswith("bad_arguments") and fake.seen == []


def test_a_key_that_may_not_change_the_queue_is_refused_and_a_household_with_none_is_not_connected(
        fake: FakeBambuddy) -> None:
    item = queued()
    fake.forbidden.add(f"/api/v1/queue/{item}/cancel")
    got = called(CANCEL, item_id=item)
    assert got.is_error and got.content.startswith("refused") and fake.states[int(item)] == "pending"
    assert called(CANCEL, HOME + 1, item_id=item).content.startswith("not_connected")


def test_its_undo_is_carried_out_through_printing_cancel(fake: FakeBambuddy) -> None:
    async def opened() -> tuple[int, int]:
        raise AssertionError("a cancel stores no turn")

    item = queued()
    assert asyncio.run(carry(Undo("print_cancel", item), HOME, 7, opened)) == Carried("undone")
    assert asyncio.run(carry(Undo("print_cancel", item), HOME, 7, opened)) == Carried("gone")


@pytest.fixture
def client(world: World) -> Generator[tuple[TestClient, FakeBambuddy]]:
    app = create_app(Settings(database_url=world.url, build_version="t", public_url=PUBLIC))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        fake = wired(world.home)
        c.cookies.set(SESSION_COOKIE, world.token, domain="ashley.test")
        yield c, fake


def did_print(w: World, item: str) -> int:
    return int(scalar(w.url, "INSERT INTO outside_actions (household_id, person_id, conversation_id, turn_id, tool, summary, "
                             "tier, decision, at, label, cause_kind, cause_id, undo_kind, undo_ref) VALUES "
                             "(%s, %s, 1, 1, 'printing_queue', 'Queued library file 2 on Shed X1C', 'runs', 'run', now(), "
                             "'Queued a print in Bambuddy', 'bench', 3, 'print_cancel', %s) RETURNING id",
                      (w.home, w.alana, item)))


def board_item(c: TestClient, action_id: int) -> WorkItem:
    entries = WorkResponse.model_validate(c.get("/api/work").json()).entries
    return next(i for i in entries if i.kind == "action" and i.id == action_id)


def test_the_board_cancels_a_print_she_queued_on_her_own(world: World, client: tuple[TestClient, FakeBambuddy]) -> None:
    c, fake = client
    item = queued(world.home)
    made = did_print(world, item)
    before = board_item(c, made)
    assert before.can_undo and before.undo is not None and before.undo.kind == "print_cancel"
    got = c.post(f"/api/work/actions/{made}/undo")
    assert (got.status_code, got.json()["how"]) == (200, "undone")
    assert fake.states[int(item)] == "cancelled"
    after = board_item(c, made)
    assert not after.can_undo and after.undone is not None and after.undone.how == "undone"


def test_a_print_started_before_cancel_is_gone_on_the_board(world: World, client: tuple[TestClient, FakeBambuddy]) -> None:
    c, fake = client
    item = queued(world.home)
    fake.states[int(item)] = "printing"
    got = c.post(f"/api/work/actions/{did_print(world, item)}/undo")
    assert (got.status_code, got.json()["how"]) == (200, "gone") and fake.states[int(item)] == "printing"


def test_a_refused_cancel_changes_nothing_and_is_offered_again(world: World,
                                                              client: tuple[TestClient, FakeBambuddy]) -> None:
    c, fake = client
    item = queued(world.home)
    fake.forbidden.add(f"/api/v1/queue/{item}/cancel")
    made = did_print(world, item)
    got = c.post(f"/api/work/actions/{made}/undo")
    assert (got.status_code, got.json()["code"]) == (409, "refused") and fake.states[int(item)] == "pending"
    assert board_item(c, made).can_undo
