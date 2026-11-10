"""The migration that makes her proposals one table, found by its name so a renumber changes nothing: the rows of
`deposit_proposals` and `house_proposals` come across as payloads of the right kind and topic, in their order, and
downgrading restores both tables with their rows."""

from datetime import UTC, datetime
from typing import Any

import psycopg
from alembic import command
from alembic.script import ScriptDirectory
from ashley.db.migrate import alembic_config
from ashley.home_assistant.change import Change
from ashley.senses.deposit_rule import DepositRule
from ashley.senses.proposal_payloads import HOUSE, REMINDERS, HouseChange, MoneyRule, ReminderChange, ReminderSchedule
from ashley.senses.repeat import Repeat
from ashley.senses.wakes import Reminder
from contract.conversations_support import scalar

RULE = DepositRule("acct-1", "Checking", 100_000, "Acme", "contains")
DUE = datetime(2030, 1, 7, 9, 30, 15, 250000, tzinfo=UTC)
CREATED = datetime(2026, 11, 3, 15, 0, tzinfo=UTC)
REPEAT = Repeat("weekly", 1, datetime(2030, 1, 7, 9, 0), (0,))


def revision_named(name: str) -> tuple[str, str]:
    script = ScriptDirectory.from_config(alembic_config(""))
    [found] = [r for r in script.walk_revisions() if r.path.endswith(f"_{name}.py")]
    assert isinstance(found.down_revision, str)
    return found.revision, found.down_revision


def seed(url: str) -> tuple[int, int, int]:
    home = int(scalar(url, "INSERT INTO households (name) VALUES ('Willow') RETURNING id"))
    alana = int(scalar(url, "INSERT INTO people (household_id, name) VALUES (%s, 'Alana') RETURNING id", (home,)))
    sam = int(scalar(url, "INSERT INTO people (household_id, name) VALUES (%s, 'Sam') RETURNING id", (home,)))
    insert = ("INSERT INTO deposit_proposals (household_id, person_id, made_by, conversation_id, turn_id, brief, rule, "
              "created_at, due_at, repeat, route, tools, target) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
              "RETURNING id")
    from psycopg.types.json import Jsonb
    from ashley.senses.deposit_rule import to_json
    from ashley.senses.repeat import to_json as repeat_json
    scalar(url, insert, (home, alana, alana, 1, 10, "money", Jsonb(to_json(RULE)), CREATED, CREATED, None, "phone", None, None))
    scalar(url, insert, (home, alana, alana, 2, 10, "turn the lamp on", None, CREATED, DUE, Jsonb(repeat_json(REPEAT)), "quiet",
                         ["lamp_on", "lamp_off"], None))
    scalar(url, insert, (home, sam, sam, 3, 11, "the edit", None, CREATED, DUE, None, "phone", None, 77))
    scalar(url, insert, (home, alana, alana, 4, 12, "an old one", None, CREATED, None, None, "phone", None, None))
    scalar(url, "INSERT INTO house_proposals (household_id, made_by, conversation_id, turn_id, change, summary, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
           (home, alana, 5, 13, Jsonb({"op": "perform", "kind": "action", "id": "homeassistant.stop", "data": {"n": [1, {"b": None}]},
                                      "ids": ["light.a", "light.b"]}), "stop the house", CREATED))
    return home, alana, sam


def stored(url: str) -> list[tuple[int, int, int, int, str, dict[str, Any], datetime]]:
    with psycopg.connect(url) as conn:
        return conn.execute("SELECT household_id, made_by, conversation_id, turn_id, topic, payload, created_at "
                            "FROM proposals ORDER BY id").fetchall()


def test_every_row_comes_across_as_a_payload_of_its_kind_and_the_old_tables_are_gone(empty_database: str) -> None:
    this, before = revision_named("one_proposals")
    command.upgrade(alembic_config(empty_database), before)
    home, alana, sam = seed(empty_database)
    command.upgrade(alembic_config(empty_database), this)
    rows = stored(empty_database)
    assert [(r[1], r[2], r[3], r[4], r[6]) for r in rows] == [
        (alana, 1, 10, "reminder", CREATED), (alana, 2, 10, "reminder", CREATED), (sam, 3, 11, "reminder", CREATED),
        (alana, 4, 12, "reminder", CREATED), (alana, 5, 13, "house", CREATED)]
    assert {r[0] for r in rows} == {home}
    decoded = [REMINDERS.decode(r[5]) for r in rows[:4]]
    assert decoded[0] == MoneyRule(Reminder(home, alana, alana, "money", CREATED, None), RULE)
    assert decoded[1] == ReminderSchedule(Reminder(home, alana, alana, "turn the lamp on", DUE, REPEAT, None, "quiet",
                                                   ("lamp_on", "lamp_off")))
    assert decoded[2] == ReminderChange(Reminder(home, sam, sam, "the edit", DUE, None), 77)
    assert decoded[3] == ReminderSchedule(Reminder(home, alana, alana, "an old one", CREATED, None))
    assert HOUSE.decode(rows[4][5]) == HouseChange(
        Change("perform", "action", "homeassistant.stop", {"n": [1, {"b": None}]}, ("light.a", "light.b")), "stop the house")
    for table in ("deposit_proposals", "house_proposals"):
        assert scalar(empty_database, f"SELECT to_regclass('{table}')::text") is None


def test_downgrading_restores_both_tables_with_their_rows(empty_database: str) -> None:
    this, before = revision_named("one_proposals")
    command.upgrade(alembic_config(empty_database), before)
    seed(empty_database)
    with psycopg.connect(empty_database) as conn:
        money = conn.execute("SELECT person_id, made_by, conversation_id, turn_id, brief, rule, created_at, due_at, repeat, "
                             "route, tools, target FROM deposit_proposals ORDER BY id").fetchall()
        house = conn.execute("SELECT made_by, conversation_id, turn_id, change, summary, created_at FROM house_proposals "
                             "ORDER BY id").fetchall()
    command.upgrade(alembic_config(empty_database), this)
    command.downgrade(alembic_config(empty_database), before)
    with psycopg.connect(empty_database) as conn:
        back = conn.execute("SELECT person_id, made_by, conversation_id, turn_id, brief, rule, created_at, due_at, repeat, "
                            "route, tools, target FROM deposit_proposals ORDER BY id").fetchall()
        again = conn.execute("SELECT made_by, conversation_id, turn_id, change, summary, created_at FROM house_proposals "
                             "ORDER BY id").fetchall()
    assert scalar(empty_database, "SELECT to_regclass('proposals')::text") is None
    assert [r[:7] + r[8:] for r in back] == [r[:7] + r[8:] for r in money]
    assert [r[7] for r in back] == [r[7] or r[6] for r in money]
    assert again == house
