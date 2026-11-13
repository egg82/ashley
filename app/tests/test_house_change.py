"""`house_change` and `house_confirm`: configuration changes she makes on her own, and the ones `irreversible.json` names
proposed instead, carried out only by `house_confirm`, offered from a later person turn of the same conversation, by the
person who proposed, once, before it expires. Turn ids decide, never words."""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import pytest
from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.home_assistant.client import HomeAssistant
from ashley.home_assistant.homes import Home, Homes
from ashley.home_assistant.house import Record
from ashley.inference.model import ToolCall, ToolResult
from ashley.senses.postgres_proposals import PostgresProposals
from ashley.senses.proposals import Proposals
from ashley.tools.house_change import CHANGE, CONFIRM, HouseChangeTools
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run, scalar
from house_double_support import MemoryHouse, state

import httpx2


class OneHome(Homes):
    def __init__(self, home: Home | None) -> None:
        self._home = home

    async def of(self, household_id: int) -> Home | None:
        return self._home

    async def check(self, base_url: str, token: str) -> None:
        raise NotImplementedError


@dataclass
class World:
    url: str
    home: int
    alana: int
    sam: int
    house: MemoryHouse

    def tools(self, who: int, conversation: int, turn: int, *, private: bool = True, ttl_s: float = 3600.0) -> HouseChangeTools:
        return HouseChangeTools(self.home, who, private=private, turn=(conversation, turn), ttl_s=ttl_s)

    async def ask(self, who: int, conversation: int, turn: int, tool: str, **arguments: Any) -> ToolResult:
        return await self.tools(who, conversation, turn).call(ToolCall("c", tool, arguments))

    async def offered(self, who: int, conversation: int, turn: int, **options: Any) -> list[str]:
        return [s.name for s in (await self.tools(who, conversation, turn, **options).catalogue()).specs]


@asynccontextmanager
async def world(url: str) -> AsyncGenerator[World]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    home = household(url)
    alana, sam = person(url, home, "Alana"), person(url, home, "Sam")
    house = MemoryHouse(things=[state("light.hall", "Hall", "off", "Hall")])
    house.configs_of = {"automation": {"arrive": {"alias": "Arrival"}}, "helper": {}, "script": {}}
    house.records_of = {"area": [Record("area", "attic", "Attic", {})]}
    client = HomeAssistant(httpx2.AsyncClient(base_url="http://ha.test:8123"))
    services.register(Homes, OneHome(Home(home, client, house)))
    services.register(Proposals, PostgresProposals(db))
    try:
        yield World(url, home, alana, sam, house)
    finally:
        for interface in (Homes, Proposals):
            services.unregister(interface)
        await client.http.aclose()
        await db.close()


def body(result: ToolResult) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(result.content)
    return loaded


DELETE: dict[str, Any] = {"op": "delete", "kind": "automation", "id": "arrive"}


def pending(url: str) -> int:
    return int(scalar(url, "SELECT count(*) FROM proposals"))


def test_a_configuration_change_is_made_at_once_without_asking(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            written = await w.ask(w.alana, 1, 5, CHANGE, op="write", kind="automation", id="porch",
                                  data={"alias": "Porch", "triggers": [], "actions": []})
            assert not written.is_error and body(written)["done"] is True
            assert w.house.configs_of["automation"]["porch"]["alias"] == "Porch"
            made = await w.ask(w.alana, 1, 5, CHANGE, op="create", kind="area", data={"name": "Garage"})
            assert body(made)["id"] == "area_new"
            await w.ask(w.alana, 1, 5, CHANGE, op="update", kind="entity", id="light.hall", data={"aliases": ["foyer"]})
            assert ("update", "entity", "light.hall", (), {"aliases": ["foyer"]}) in w.house.done
            assert pending(db_url) == 0
    run(go())


def test_a_delete_is_proposed_and_nothing_is_deleted(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            proposed = await w.ask(w.alana, 1, 5, CHANGE, **DELETE)
            got = body(proposed)
            assert not proposed.is_error and got["done"] is False and "Arrival (arrive)" in got["proposed"]
            assert "arrive" in w.house.configs_of["automation"] and w.house.done == [] and pending(db_url) == 1
    run(go())


def test_confirm_is_offered_only_from_a_later_turn_and_carries_out_what_was_proposed_once(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            assert await w.offered(w.alana, 1, 5) == [CHANGE]
            await w.ask(w.alana, 1, 5, CHANGE, **DELETE)
            assert await w.offered(w.alana, 1, 5) == [CHANGE], "the turn it was proposed in"
            assert await w.offered(w.alana, 1, 4) == [CHANGE]
            assert await w.offered(w.sam, 1, 6) == [CHANGE] and await w.offered(w.alana, 2, 6) == [CHANGE]
            assert await w.offered(w.alana, 1, 6, private=False) == [CHANGE]
            assert await w.offered(w.alana, 1, 6) == [CHANGE, CONFIRM]
            done = await w.ask(w.alana, 1, 6, CONFIRM)
            assert not done.is_error and body(done)["done"] is True and "Arrival" in body(done)["did"]
            assert "arrive" not in w.house.configs_of["automation"]
            again = await w.ask(w.alana, 1, 7, CONFIRM)
            assert again.is_error and again.content.startswith("there is no proposal")
            assert await w.offered(w.alana, 1, 7) == [CHANGE] and pending(db_url) == 0
    run(go())


@pytest.mark.parametrize(("who", "conversation", "turn", "says"), [
    ("alana", 1, 5, "has not answered"), ("alana", 1, 4, "has not answered"),
    ("alana", 2, 6, "no proposal"), ("sam", 1, 6, "no proposal")])
def test_confirm_refuses_the_same_turn_another_conversation_and_another_person(
        db_url: str, who: str, conversation: int, turn: int, says: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.ask(w.alana, 1, 5, CHANGE, **DELETE)
            refused = await w.ask(w.alana if who == "alana" else w.sam, conversation, turn, CONFIRM)
            assert refused.is_error and says in refused.content
            assert "arrive" in w.house.configs_of["automation"] and w.house.done == []
    run(go())


def test_the_latest_proposal_is_the_one_carried_out_and_an_expired_one_is_refused(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.ask(w.alana, 1, 5, CHANGE, **DELETE)
            await w.ask(w.alana, 1, 6, CHANGE, op="delete", kind="area", id="attic")
            await w.ask(w.alana, 1, 7, CONFIRM)
            assert w.house.done == [("delete", "area", "attic", (), {})] and "arrive" in w.house.configs_of["automation"]
            await w.ask(w.alana, 1, 8, CHANGE, **DELETE)
            late = await w.tools(w.alana, 1, 9, ttl_s=-1).call(ToolCall("c", CONFIRM, {}))
            assert late.is_error and "expired" in late.content
    run(go())


def test_an_irreversible_action_is_proposed_and_confirmed_like_a_delete(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            proposed = await w.ask(w.alana, 1, 5, CHANGE, op="perform", kind="action", id="homeassistant.restart")
            assert body(proposed)["done"] is False and w.house.done == []
            await w.ask(w.alana, 1, 6, CONFIRM)
            assert w.house.done == [("perform", "action", "homeassistant.restart", (), {})]
    run(go())


def test_an_action_that_needs_no_ok_is_not_run_through_house_change(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            got = await w.ask(w.alana, 1, 5, CHANGE, op="perform", kind="action", id="light.turn_on", name="hall")
            assert got.is_error and "house_do" in got.content and w.house.done == []
    run(go())


def test_where_the_reply_is_not_private_nothing_irreversible_is_proposed_and_the_rest_is_done(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            tools = w.tools(w.alana, 1, 5, private=False)
            refused = await tools.call(ToolCall("c", CHANGE, DELETE))
            assert refused.is_error and "private" in refused.content and pending(db_url) == 0
            made = await tools.call(ToolCall("c", CHANGE, {"op": "create", "kind": "label", "data": {"name": "Xmas"}}))
            assert not made.is_error
            assert (await tools.call(ToolCall("c", CONFIRM, {}))).is_error
    run(go())


@pytest.mark.parametrize("arguments", [
    {"op": "explode", "kind": "area"}, {"op": "delete", "kind": "sandwich", "id": "x"}, {"op": "delete", "kind": "area"},
    {"op": "write", "kind": "area", "id": "x"}, {"op": "update", "kind": "integration", "id": "x"},
    {"op": "create", "kind": "area", "colour": "red"}, {"kind": "area"}])
def test_a_malformed_change_is_an_error_naming_the_argument_and_changes_nothing(db_url: str, arguments: dict[str, Any]) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            got = await w.ask(w.alana, 1, 5, CHANGE, **arguments)
            assert got.is_error and w.house.done == [] and pending(db_url) == 0
    run(go())


def test_the_house_refusing_a_change_is_a_result_and_a_house_that_is_down_is_unavailable(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            w.house.refuse = "bad trigger"
            refused = await w.ask(w.alana, 1, 5, CHANGE, op="write", kind="automation", id="x", data={})
            assert refused.is_error and "bad trigger" in refused.content
            w.house.refuse, w.house.down = None, True
            assert (await w.ask(w.alana, 1, 5, CHANGE, op="create", kind="area", data={"name": "x"})).content == "the house did not answer"
    run(go())


def test_a_household_with_no_house_offers_no_change_tools(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            services.register(Homes, OneHome(None))
            assert await w.offered(w.alana, 1, 5) == []
            assert (await w.ask(w.alana, 1, 5, CHANGE, **DELETE)).is_error
    run(go())


def test_a_call_logs_op_and_kind_and_never_an_id_a_name_or_a_config(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            with caplog.at_level("INFO", logger="ashley.tools"):
                await w.ask(w.alana, 1, 5, CHANGE, **DELETE)
                await w.ask(w.alana, 1, 5, CHANGE, op="write", kind="automation", id="secretid", data={"alias": "Secret"})
    run(go())
    lines = [getattr(r, "fields") for r in caplog.records if r.getMessage() == "tools.call"]
    assert [(f["outcome"], f["op"], f["kind"]) for f in lines] == [("proposed", "delete", "automation"), ("ok", "write", "automation")]
    assert not any(w in str(lines) for w in ("arrive", "Arrival", "secretid", "Secret"))


def test_proposing_drops_what_is_older_than_the_limit_she_was_given_and_keeps_the_younger(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.ask(w.alana, 1, 5, CHANGE, **DELETE)
            await w.ask(w.alana, 2, 5, CHANGE, **DELETE)
            scalar(db_url, "WITH u AS (UPDATE proposals SET created_at = created_at - interval '90 minutes' "
                           "WHERE conversation_id = 1 RETURNING 1) SELECT count(*) FROM u")
            scalar(db_url, "WITH u AS (UPDATE proposals SET created_at = created_at - interval '30 minutes' "
                           "WHERE conversation_id = 2 RETURNING 1) SELECT count(*) FROM u")
            await w.ask(w.alana, 3, 5, CHANGE, **DELETE)
            assert scalar(db_url, "SELECT array_agg(conversation_id ORDER BY conversation_id) FROM proposals") == [2, 3]

    run(go())


def test_a_proposal_is_the_speakers_whatever_the_ids_of_the_household(db_url: str) -> None:
    async def go() -> None:
        household(db_url, "an earlier household")
        async with world(db_url) as w:
            assert w.alana != w.home
            await w.ask(w.alana, 1, 5, CHANGE, **DELETE)
            assert scalar(db_url, "SELECT json_build_array(made_by, household_id) FROM proposals") == [w.alana, w.home]
            assert CONFIRM in await w.offered(w.alana, 1, 6)
            assert not (await w.ask(w.alana, 1, 6, CONFIRM)).is_error

    run(go())
