"""What a household's saved settings do to its tools, through `Outside` over a turn's tools: a read of a list the
household writes stops tainting when a member lists it and starts again when it is removed; a new connection, another
household and an unreadable database are maximal taint; `reads`, `service_reads` and `consequential_entities` each decide
what their names say. Each `ask` is a new turn, so a saved change applies from the next."""

import psycopg
from ashley.home_assistant.homes import Home
from conn_settings_blind_support import People, ask, connect_ha, home_of, on_app_loop, write
from fastapi.testclient import TestClient

GET = "todo.get_items"


def read_taint(client: TestClient, household: int, *ids: str) -> str | None:
    async def go() -> str | None:
        home: Home = await home_of(household)
        return (await ask(home, GET, list(ids)))[0]

    return on_app_loop(client, go)


def test_a_new_connection_is_maximal_taint(client: TestClient, people: People) -> None:
    connect_ha(client)
    for entity in ("todo.inbox", "todo.family"):
        assert read_taint(client, people.home, entity) == "house_ask"


def test_listing_a_list_untaints_a_read_of_it_and_removing_it_taints_again(client: TestClient, people: People) -> None:
    cid = connect_ha(client)
    assert read_taint(client, people.home, "todo.family") == "house_ask"
    assert write(client, cid, {"household_reads": {GET: ["todo.family"]}}).status_code == 200
    assert read_taint(client, people.home, "todo.family") is None
    assert read_taint(client, people.home, "todo.inbox") == "house_ask"
    assert write(client, cid, {"household_reads": {GET: ["todo.inbox"]}}).status_code == 200
    assert read_taint(client, people.home, "todo.family") == "house_ask"
    assert write(client, cid, {}).status_code == 200
    assert read_taint(client, people.home, "todo.inbox") == "house_ask"


def test_one_list_unlisted_among_several_still_taints(client: TestClient, people: People) -> None:
    cid = connect_ha(client)
    write(client, cid, {"household_reads": {GET: ["todo.family", "todo.inbox"]}})
    assert read_taint(client, people.home, "todo.family", "todo.inbox") is None
    assert read_taint(client, people.home, "todo.family", "todo.to_do_list") == "house_ask"


def test_another_household_gets_none_of_it(client: TestClient, people: People) -> None:
    cid = connect_ha(client)
    write(client, cid, {"household_reads": {GET: ["todo.family"]}})
    assert read_taint(client, people.home, "todo.family") is None
    assert read_taint(client, people.other, "todo.family") == "house_ask"


def test_service_reads_untaints_a_read_whatever_it_names(client: TestClient, people: People) -> None:
    cid = connect_ha(client)

    async def where() -> tuple[str | None, str]:
        return await ask(await home_of(people.home), "script.where", [], tool="house_ask")

    assert on_app_loop(client, where)[0] == "house_ask"
    write(client, cid, {"reads": ["script.where"], "service_reads": ["script.where"]})
    assert on_app_loop(client, where)[0] is None


def test_reads_decides_which_scripts_house_ask_may_run(client: TestClient, people: People) -> None:
    cid = connect_ha(client)

    async def locate() -> str:
        return (await ask(await home_of(people.home), "script.find_person", [], tool="house_ask"))[1]

    assert "changes things" in on_app_loop(client, locate)
    write(client, cid, {"reads": ["script.find_person"]})
    assert "changes things" not in on_app_loop(client, locate)


def test_a_consequential_entity_is_held_in_a_tainted_turn_until_it_is_removed(client: TestClient, people: People) -> None:
    cid = connect_ha(client)

    async def lamp() -> str:
        return (await ask(await home_of(people.home), "switch.turn_on", ["switch.lamp"], tool="house_do",
                          tainted="look_up"))[1]

    assert "held" not in on_app_loop(client, lamp)
    write(client, cid, {"consequential_entities": ["switch.lamp"]})
    assert "held" in on_app_loop(client, lamp)
    write(client, cid, {})
    assert "held" not in on_app_loop(client, lamp)




def test_an_unreadable_settings_table_is_maximal_taint(client: TestClient, people: People, db_url: str) -> None:
    cid = connect_ha(client)
    write(client, cid, {"household_reads": {GET: ["todo.family"]}})
    assert read_taint(client, people.home, "todo.family") is None
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("ALTER TABLE connection_settings RENAME TO connection_settings_gone")
    assert read_taint(client, people.home, "todo.family") == "house_ask"
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("ALTER TABLE connection_settings_gone RENAME TO connection_settings")
    assert read_taint(client, people.home, "todo.family") is None
