"""Her read of the household's devices (`channels.devices_tool.DeviceTools`) over a real Devices table: she is told
each unrevoked device's name, place, form, audience, medium and kind, counted, so "how many Echos" is a lookup; a
revoked device and another household's are not there; no token, host or server id is; an unreadable table is an error
saying so; the tool is offered on every turn of a known speaker and is a read."""

import asyncio
import json

import psycopg
from ashley import services
from ashley.channels.devices import Devices, NullDevices
from ashley.channels.devices_tool import NAME, DeviceTools
from ashley.channels.postgres_devices import PostgresDevices
from ashley.db.pool import PoolDatabase
from ashley.inference.model import ToolCall
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, run, scalar


def add(url: str, home: int, name: str, place: str, **columns: object) -> int:
    fields = {"household_id": home, "name": name, "place": place, "token_sha256": name.encode().ljust(32, b"x"),
              "audience": "present", "medium": "spoken", "kind": "command", **columns}
    cols = ", ".join(fields)
    marks = ", ".join(["%s"] * len(fields))
    return int(scalar(url, f"INSERT INTO devices ({cols}) VALUES ({marks}) RETURNING id", tuple(fields.values())))


def test_she_counts_and_names_the_households_devices(db_url: str) -> None:
    home, other = household(db_url), household(db_url, "other")
    add(db_url, home, "Atom Echo kitchen", "kitchen", esphome_host="echo-kitchen.local")
    add(db_url, home, "Atom Echo hall", "hall", esphome_host="echo-hall.local")
    add(db_url, home, "Hallway tablet", "hall", audience="household", medium="text", kind="chat")
    gone = add(db_url, home, "Atom Echo shed", "shed", esphome_host="echo-shed.local")
    add(db_url, other, "Their Echo", "den", esphome_host="their-echo.local")
    with psycopg.connect(db_url) as conn:
        conn.execute("UPDATE devices SET revoked_at = now() WHERE id = %s", (gone,))

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        services.register(Devices, PostgresDevices(database))
        try:
            tools = DeviceTools(home)
            assert [s.name for s in (await tools.catalogue()).specs] == [NAME]
            assert (await tools.catalogue()).specs[0].reads
            got = await tools.call(ToolCall("c", NAME, {}))
            assert not got.is_error, got.content
            body = json.loads(got.content)
            assert body["count"] == 3
            echoes = [d for d in body["devices"] if d["form"] == "satellite"]
            assert sorted(d["name"] for d in echoes) == ["Atom Echo hall", "Atom Echo kitchen"]
            assert {d["name"]: (d["place"], d["audience"], d["medium"], d["kind"]) for d in body["devices"]}[
                "Hallway tablet"] == ("hall", "household", "text", "chat")
            assert "echo-" not in got.content and "token" not in got.content
            assert (await tools.call(ToolCall("c", NAME, {"x": 1}))).content.startswith("bad_arguments")
        finally:
            services.unregister(Devices)
            await database.close()

    run(scenario())


def test_an_unreadable_table_is_an_error_not_an_empty_list() -> None:
    services.register(Devices, NullDevices())
    try:
        got = asyncio.run(DeviceTools(1).call(ToolCall("c", NAME, {})))
        assert got.is_error and got.content.startswith("unavailable")
    finally:
        services.unregister(Devices)
