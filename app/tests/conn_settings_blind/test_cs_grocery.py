"""The grocery case after the migration: no list is seeded, so household 1's grocery list taints a turn that reads it
until a person lists it, as any other list does."""

import psycopg
from alembic import command
from ashley.db.migrate import alembic_config
from ashley.people import admin
from conn_settings_blind_support import People, app_client, ask, home_of, on_app_loop, session, the_house
from contract.conversations_support import scalar
from house_double_support import state
from test_cs_migration import before_settings

GET = "todo.get_items"


def test_household_ones_grocery_list_is_unseeded_so_reading_it_taints(empty_database: str) -> None:
    url = empty_database
    command.upgrade(alembic_config(url), before_settings())
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("INSERT INTO households (name, timezone) VALUES ('Moore', 'UTC')")
    scalar(url, "INSERT INTO connections (household_id, kind, base_url, secret) "
                "VALUES (1, 'home_assistant', 'http://ha.test:8123', '\\x00') RETURNING id")
    command.upgrade(alembic_config(url), "head")
    with psycopg.connect(url) as conn:
        person = admin.add_person(conn, 1, "P")
        people = People(person, person, person, 1, 1, {"p": session(conn, person, 1, "p")})
    house = the_house()
    house.things.append(state("todo.groceries", "Groceries", "1"))
    house.returns[GET]["todo.groceries"] = {"items": [{"summary": "milk"}]}
    with app_client(url, people, {1: house}) as client:
        async def read(list_id: str, tainted: str | None) -> tuple[str | None, str]:
            return await ask(await home_of(1), GET, [list_id], tainted=tainted)

        grocery, _ = on_app_loop(client, lambda: read("todo.groceries", None))
        assert grocery == "house_ask"
        kept, reply = on_app_loop(client, lambda: read("todo.groceries", "look_up"))
        assert kept == "look_up" and "done" in reply
        other, _ = on_app_loop(client, lambda: read("todo.to_do_list", None))
        assert other == "house_ask"
