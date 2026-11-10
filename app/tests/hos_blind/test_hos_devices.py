"""`household_devices` on a real database: the household's own unrevoked devices with what a person needs to count and
name them, none of another household's, and no token, host or server id."""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from ashley import services
from ashley.channels.devices import Devices
from ashley.channels.devices_tool import DeviceTools
from ashley.channels.model import Audience, Listed, Medium
from ashley.channels.postgres_devices import PostgresDevices
from ashley.db.pool import PoolDatabase
from ashley.inference.model import ToolCall, ToolResult
from hos_support import World, all_logs, go, log_text, world

NAME = "household_devices"
HOST, GUILD, SPEAKER = "esphome-secret-host.lan", 918273645546372819, "media_player.kitchen_secret"


@dataclass
class Rig:
    w: World
    devices: PostgresDevices
    tokens: list[str]


@asynccontextmanager
async def rig(url: str) -> AsyncGenerator[Rig]:
    w = world(url)
    db = PoolDatabase(url)
    await db.open()
    devices = PostgresDevices(db)
    services.register(Devices, devices)
    try:
        yield Rig(w, devices, [])
    finally:
        await db.close()


async def add(r: Rig, household: int, name: str, place: str, audience: Audience = "present",
              medium: Medium = "spoken") -> int:
    device, token = await r.devices.add(household, name, place, audience, medium, "chat")
    r.tokens.append(token)
    return device.id


async def ask(household: int, **arguments: object) -> ToolResult:
    return await DeviceTools(household).call(ToolCall("c1", NAME, arguments))


def listed(got: ToolResult) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = json.loads(got.content)["devices"]
    return rows


def test_it_is_one_read_tool() -> None:
    async def scenario() -> None:
        cat = await DeviceTools(1).catalogue()
        assert [s.name for s in cat.specs] == [NAME] and cat.specs[0].reads is True

    go(scenario())


def test_it_lists_the_households_devices_with_their_names_places_audience_and_medium(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            a = await add(r, r.w.home, "Kitchen Echo", "kitchen", "present", "spoken")
            b = await add(r, r.w.home, "Hall Tablet", "hallway", "household", "text")
            got = await ask(r.w.home)
            assert not got.is_error and got.call_id == "c1"
            rows = {row["name"]: row for row in listed(got)}
            assert set(rows) == {"Kitchen Echo", "Hall Tablet"}
            assert (rows["Kitchen Echo"]["id"], rows["Kitchen Echo"]["place"]) == (a, "kitchen")
            assert (rows["Kitchen Echo"]["audience"], rows["Kitchen Echo"]["medium"]) == ("present", "spoken")
            assert (rows["Hall Tablet"]["id"], rows["Hall Tablet"]["place"]) == (b, "hallway")
            assert (rows["Hall Tablet"]["audience"], rows["Hall Tablet"]["medium"]) == ("household", "text")
            assert json.loads(got.content)["count"] == 2

    go(scenario())


def test_what_each_device_is_comes_from_how_it_is_wired_and_never_its_name(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            sat = await add(r, r.w.home, "Discord Server", "porch")
            guild = await add(r, r.w.home, "Plain Satellite", "den")
            house = await add(r, r.w.home, "Tablet", "hall")
            await r.devices.set_satellite(sat, HOST, SPEAKER)
            await r.devices.set_discord_server(guild, GUILD, GUILD + 1)
            await r.devices.set_house(house)
            by_id = {int(str(row["id"])): row for row in listed(await ask(r.w.home))}
            forms = {i: by_id[i].get("form") for i in (sat, guild, house)}
            assert forms == {sat: "satellite", guild: "discord_server", house: "house"}

    go(scenario())


def test_it_names_no_token_host_or_server_id_and_logs_none(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    all_logs(caplog)

    async def scenario() -> None:
        async with rig(db_url) as r:
            sat = await add(r, r.w.home, "Sat", "den")
            guild = await add(r, r.w.home, "Guild", "porch")
            await r.devices.set_satellite(sat, HOST, SPEAKER)
            await r.devices.set_discord_server(guild, GUILD, GUILD + 1)
            got = await ask(r.w.home)
            shown = got.content + log_text(caplog)
            for secret in (*r.tokens, HOST, str(GUILD), str(GUILD + 1), SPEAKER):
                assert secret not in shown, secret

    go(scenario())


def test_another_households_devices_are_not_listed(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await add(r, r.w.home, "Ours", "kitchen")
            await add(r, r.w.other, "Theirs", "garage")
            ours, theirs = await ask(r.w.home), await ask(r.w.other)
            assert [row["name"] for row in listed(ours)] == ["Ours"] and "Theirs" not in ours.content
            assert [row["name"] for row in listed(theirs)] == ["Theirs"] and "Ours" not in theirs.content
            assert listed(await ask(r.w.other + 1000)) == []

    go(scenario())


def test_a_revoked_device_is_not_listed_and_a_household_with_none_gets_an_empty_list(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            gone = await add(r, r.w.home, "Gone", "attic")
            await add(r, r.w.home, "Kept", "kitchen")
            assert await r.devices.revoke(gone)
            assert [row["name"] for row in listed(await ask(r.w.home))] == ["Kept"]
            empty = await ask(r.w.other)
            assert not empty.is_error and listed(empty) == [] and json.loads(empty.content)["count"] == 0

    go(scenario())


def test_devices_that_cannot_be_read_are_an_error_result_and_an_unknown_tool_too(db_url: str) -> None:
    async def scenario() -> None:
        services.unregister(Devices)
        got = await ask(1)
        assert got.is_error and got.call_id == "c1"
        assert (await DeviceTools(1).call(ToolCall("c2", "household_device", {}))).is_error
        assert (await DeviceTools(1).call(ToolCall("c3", "git_projects", {}))).is_error

    go(scenario())


def test_the_listed_type_is_what_the_service_gives(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await add(r, r.w.home, "One", "kitchen")
            found = await r.devices.of_household(r.w.home)
            assert len(found) == 1 and isinstance(found[0], Listed)

    go(scenario())
