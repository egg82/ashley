"""`POST /api/work/actions/{id}/undo` through the real app and database: each kind of undo goes through her own tool
for that change. A delete of what she created is proposed for the person's yes and never made; a reminder is
cancelled; a to-do change is the service call that takes it back. A target already gone is `gone`; an undo is taken
once; only the person the action was for, in their household, can take it; a refused undo is offered again; and
`/api/work` says whether Undo is offered and how a taken one stands."""

import hashlib
import secrets
from collections.abc import Generator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from ashley import logs, services
from ashley.db.pool import PoolDatabase
from ashley.api.person import SESSION_COOKIE
from ashley.api.work_models import WorkItem, WorkResponse
from ashley.channels.undo_action import CONFIG
from ashley.connections.connections import Connections
from ashley.connections.model import Port
from ashley.connections.settings import SettingValues
from ashley.connections.settings_read import NullSettingsReader, SettingsReader
from ashley.home_assistant.homes import Homes
from ashley.home_assistant.todos import NAME, HaTodos
from ashley.inference.model import ToolCall
from ashley.main import create_app
from ashley.people import admin
from ashley.senses.postgres_proposals import PostgresProposals
from ashley.senses.proposals import Proposals
from ashley.settings import Settings
from ashley.todos.routed import RoutedTodos
from ashley.todos.todos import Todos
from ashley.tools.house_change import CONFIRM, HouseChangeTools
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template, run, scalar
from fastapi.testclient import TestClient
from homes_support import AnyHousehold
from house_double_support import MemoryHouse, state
from money_support import HeldConnections

PUBLIC = "https://ashley.test"
GROCERY = "todo.zq_grocery"
SUMMARY = "Made the automation Porch at dusk"


@dataclass(frozen=True)
class World:
    url: str
    home: int
    alana: int
    sam: int
    other: int
    pat: int
    token: str


class Settled(NullSettingsReader):
    async def of(self, household_id: int, port: Port) -> SettingValues:
        return {}

    async def ports_off(self, household_id: int) -> Mapping[int, frozenset[str]]:
        return {}


class NoWrites(AnyHousehold):
    async def writes_automations(self, household_id: int) -> bool:
        return False


@pytest.fixture
def world(db_url: str) -> World:
    with psycopg.connect(db_url) as conn:
        home, other = admin.add_household(conn, "home", "UTC"), admin.add_household(conn, "away", "UTC")
        alana, sam, pat = (admin.add_person(conn, home, "Alana"), admin.add_person(conn, home, "Sam"),
                           admin.add_person(conn, other, "Pat"))
        account = admin.add_account(conn, alana, "oidc", "sub-alana")
        token = secrets.token_urlsafe(16)
        conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                     "VALUES (%s, %s, %s, now() + interval '1 day')",
                     (hashlib.sha256(token.encode()).digest(), account, home))
    return World(db_url, home, alana, sam, other, pat, token)


@pytest.fixture
def house() -> MemoryHouse:
    made = MemoryHouse(things=[state(GROCERY, "Grocery", "2")])
    made.configs_of = {"automation": {"porch": {"alias": "Porch at dusk"}}, "script": {}, "helper": {}}
    made.returns["todo.get_items"] = {GROCERY: {"items": [
        {"summary": "Oat milk", "uid": "u1", "status": "needs_action"},
        {"summary": "Rye bread", "uid": "u2", "status": "completed"}]}}
    return made


@pytest.fixture
def client(world: World, house: MemoryHouse) -> Generator[TestClient]:
    app = create_app(Settings(database_url=world.url, build_version="t", public_url=PUBLIC))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        held = HeldConnections()
        held.connect(world.home, "http://ha.test", "k", NAME)
        services.register(Connections, held)
        services.register(Homes, AnyHousehold(house))
        services.register(Todos, RoutedTodos({NAME: HaTodos()}))
        services.register(SettingsReader, Settled())
        c.cookies.set(SESSION_COOKIE, world.token, domain="ashley.test")
        yield c


def did(w: World, kind: str | None, ref: str = "porch", within: str | None = "automation", person: int | None = None,
        home: int | None = None) -> int:
    return int(scalar(w.url, "INSERT INTO outside_actions (household_id, person_id, conversation_id, turn_id, tool, summary, "
                             "tier, decision, at, label, cause_kind, cause_id, undo_kind, undo_ref, undo_within) VALUES "
                             "(%s, %s, 1, 1, 'house_change', %s, 'runs', 'run', now(), 'Changed the house', 'wake', 9, "
                             "%s, %s, %s) RETURNING id",
                      (w.home if home is None else home, w.alana if person is None else person, SUMMARY, kind,
                       None if kind is None else ref, None if kind is None else within)))


def reminder(w: World) -> int:
    due = datetime.now(UTC) + timedelta(days=1)
    return int(scalar(w.url, "INSERT INTO wakes (household_id, kind, event_id, event, at, due_at, person_id, made_by, brief) "
                             "VALUES (%s, 'reminder', %s, 'reminder', %s, %s, %s, %s, 'Water the ferns') RETURNING id",
                      (w.home, secrets.token_hex(8), due, due, w.alana, w.alana)))


def undo(client: TestClient, action: int) -> tuple[int, dict[str, object]]:
    got = client.post(f"/api/work/actions/{action}/undo")
    return got.status_code, got.json()


def action(client: TestClient, action_id: int) -> WorkItem:
    entries = WorkResponse.model_validate(client.get("/api/work").json()).entries
    return next(i for i in entries if i.kind == "action" and i.id == action_id)


def changes(house: MemoryHouse) -> list[tuple[str, str, str]]:
    """What reached the house other than reads of a list."""
    return [d[:3] for d in house.done if d[2] != "todo.get_items"]


def test_undoing_a_thing_she_made_proposes_its_delete_for_their_yes_and_never_deletes_it(
        world: World, client: TestClient, house: MemoryHouse) -> None:
    made = did(world, "house_delete")
    status, body = undo(client, made)
    assert status == 200 and body["how"] == "waiting_on_you"
    assert changes(house) == [] and "porch" in house.configs_of["automation"]
    conversation = body["conversation_id"]
    assert isinstance(conversation, int)
    row = scalar(world.url, "SELECT payload->'change'->>'op' || ':' || (payload->'change'->>'id') FROM proposals "
                            "WHERE made_by = %s AND conversation_id = %s AND topic = 'house'", (world.alana, conversation))
    assert row == "delete:porch"
    said = scalar(world.url, "SELECT json_agg(json_build_array(author, speaker_id, text, visibility, owner_id)) FROM turns "
                             "WHERE conversation_id = %s", (conversation,))
    assert said == [["household", None, f"{CONFIG.turn} {SUMMARY}", "private", world.alana]], "never words of the person's"
    item = action(client, made)
    assert not item.can_undo and item.undone is not None and item.undone.how == "waiting_on_you"
    waiting = [i for i in WorkResponse.model_validate(client.get("/api/work").json()).entries if i.kind == "proposal"]
    assert [(i.lane, i.conversation_id) for i in waiting] == [("waiting", conversation)]


def test_a_thing_she_made_that_is_already_gone_is_gone_and_nothing_is_proposed(
        world: World, client: TestClient, house: MemoryHouse) -> None:
    made = did(world, "house_delete", ref="vanished")
    assert undo(client, made) == (200, {"id": made, "how": "gone", "conversation_id": None})
    assert scalar(world.url, "SELECT count(*) FROM proposals") == 0 and changes(house) == []
    assert action(client, made).undone is not None


def test_a_reminder_she_set_is_cancelled_and_one_already_over_is_gone(world: World, client: TestClient) -> None:
    ferns, over = reminder(world), reminder(world)
    scalar(world.url, "UPDATE wakes SET settled_at = now(), outcome = 'cancelled' WHERE id = %s RETURNING id", (over,))
    assert undo(client, did(world, "reminder_cancel", str(ferns), None))[1]["how"] == "undone"
    assert scalar(world.url, "SELECT outcome FROM wakes WHERE id = %s", (ferns,)) == "cancelled"
    assert undo(client, did(world, "reminder_cancel", str(over), None))[1]["how"] == "gone"


@pytest.mark.parametrize("kind, ref, call", [
    ("todo_remove", "Oat milk", ("perform", "action", "todo.remove_item")),
    ("todo_reopen", "u2", ("perform", "action", "todo.update_item")),
    ("todo_done", "u1", ("perform", "action", "todo.update_item"))])
def test_each_list_change_is_taken_back_by_the_call_that_reverses_it(world: World, client: TestClient, house: MemoryHouse,
                                                                    kind: str, ref: str, call: tuple[str, str, str]) -> None:
    assert undo(client, did(world, kind, ref, GROCERY))[1]["how"] == "undone"
    assert changes(house) == [call]
    item, status = {"todo_remove": (["u1"], None), "todo_reopen": ("u2", "needs_action"), "todo_done": ("u1", "completed")}[kind]
    sent = house.done[-1][4]
    assert sent["item"] == item and sent.get("status") == status


@pytest.mark.parametrize("kind, ref, within", [
    ("todo_reopen", "u1", GROCERY), ("todo_done", "u2", GROCERY), ("todo_remove", "Lemons", GROCERY),
    ("todo_remove", "Oat milk", "todo.zq_gone")])
def test_a_list_item_no_longer_as_she_left_it_is_gone(world: World, client: TestClient, house: MemoryHouse, kind: str,
                                                     ref: str, within: str) -> None:
    assert undo(client, did(world, kind, ref, within))[1]["how"] == "gone"
    assert changes(house) == []


def test_an_undo_is_taken_once(world: World, client: TestClient, house: MemoryHouse) -> None:
    made = did(world, "todo_remove", "Oat milk", GROCERY)
    assert undo(client, made)[0] == 200
    assert undo(client, made) == (409, {"code": "already_undone", "detail": "that was already undone, or is being undone now"})
    assert len(changes(house)) == 1


def test_an_action_with_no_undo_is_refused(world: World, client: TestClient) -> None:
    made = did(world, None)
    assert undo(client, made)[1]["code"] == "no_undo"
    assert not action(client, made).can_undo


def test_a_refused_undo_changes_nothing_and_is_offered_again(world: World, client: TestClient, house: MemoryHouse) -> None:
    services.register(Homes, NoWrites(house))
    made = did(world, "house_delete")
    assert undo(client, made)[1]["code"] == "refused"
    assert scalar(world.url, "SELECT count(*) FROM proposals") == 0
    item = action(client, made)
    assert item.can_undo and item.undone is None


def test_only_the_person_it_was_done_for_in_their_household_can_undo_it(world: World, client: TestClient) -> None:
    sams = did(world, "todo_remove", "Oat milk", GROCERY, person=world.sam)
    elsewhere = did(world, "todo_remove", "Oat milk", GROCERY, person=world.alana, home=world.other)
    for target in (sams, elsewhere, 999999):
        assert undo(client, target)[0] == 404
    assert scalar(world.url, "SELECT count(*) FROM outside_actions WHERE undone_at IS NOT NULL") == 0


def test_signed_out_is_401_and_from_another_site_is_403(world: World, client: TestClient) -> None:
    made = did(world, "todo_remove", "Oat milk", GROCERY)
    assert client.post(f"/api/work/actions/{made}/undo", headers={"origin": "https://elsewhere.test"}).status_code == 403
    client.cookies.clear()
    assert client.post(f"/api/work/actions/{made}/undo").status_code == 401
    assert scalar(world.url, "SELECT count(*) FROM outside_actions WHERE undone_at IS NOT NULL") == 0


def test_the_board_offers_undo_until_it_is_taken_and_then_shows_how_it_stands(world: World, client: TestClient) -> None:
    made = did(world, "todo_remove", "Oat milk", GROCERY)
    before = action(client, made)
    assert before.can_undo and before.undone is None
    undo(client, made)
    after = action(client, made)
    assert not after.can_undo and after.undone is not None and after.undone.how == "undone"


def test_one_log_line_per_undo_names_ids_kinds_and_outcome_never_the_item(
        world: World, client: TestClient, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    made = did(world, "todo_remove", "Oat milk", GROCERY)
    undo(client, made)
    undo(client, made)
    lines = [line for line in capsys.readouterr().out.splitlines() if "event=undo.done" in line]
    assert len(lines) == 2
    assert f"action={made}" in lines[0] and "kind=todo_remove" in lines[0] and "outcome=undone" in lines[0]
    assert "outcome=already_undone" in lines[1]
    assert not any("Oat" in line or "Porch" in line for line in lines)


def test_an_unreachable_house_is_503_and_the_undo_is_offered_again(world: World, client: TestClient,
                                                                   house: MemoryHouse) -> None:
    house.down = True
    made = did(world, "house_delete")
    assert undo(client, made)[0] == 503
    house.down = False
    assert action(client, made).can_undo


def test_their_yes_after_the_household_s_line_carries_the_delete_out_through_house_confirm(
        world: World, client: TestClient, house: MemoryHouse) -> None:
    made = did(world, "house_delete")
    conversation = undo(client, made)[1]["conversation_id"]
    assert isinstance(conversation, int)
    proposed = int(scalar(world.url, "SELECT turn_id FROM proposals WHERE conversation_id = %s", (conversation,)))
    assert scalar(world.url, "SELECT author FROM turns WHERE id = %s", (proposed,)) == "household"
    yes = int(scalar(world.url, "INSERT INTO turns (conversation_id, household_id, author, speaker_id, text, visibility, "
                                "owner_id) VALUES (%s, %s, 'person', %s, 'yes, delete it', 'private', %s) RETURNING id",
                     (conversation, world.home, world.alana, world.alana)))

    async def go() -> None:
        db = PoolDatabase(world.url, connect_timeout_s=5.0)
        await db.open()
        services.register(Proposals, PostgresProposals(db))
        try:
            assert CONFIRM not in [s.name for s in (await HouseChangeTools(
                world.home, world.alana, private=True, turn=(conversation, proposed)).catalogue()).specs]
            sams = HouseChangeTools(world.home, world.sam, private=True, turn=(conversation, yes))
            assert CONFIRM not in [s.name for s in (await sams.catalogue()).specs], "the proposal is the person's"
            theirs = HouseChangeTools(world.home, world.alana, private=True, turn=(conversation, yes))
            assert CONFIRM in [s.name for s in (await theirs.catalogue()).specs]
            got = await theirs.call(ToolCall("c", CONFIRM, {}))
            assert not got.is_error, got.content
        finally:
            await db.close()

    run(go())
    assert changes(house) == [("delete", "automation", "porch")] and "porch" not in house.configs_of["automation"]
