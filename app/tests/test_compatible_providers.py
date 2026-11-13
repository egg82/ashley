"""OpenAI-compatible providers as connections, on a real database: a route naming a connection's label reaches that
connection's address with its key; its calls are priced as the catalogue provider the person picked, and one at a
custom address is unpriced even when its label is a catalogue provider's id; `LOCAL_LLM_URL` seeds the connection
labelled `local` once, by one of several pods seeding at once, never over a row and not when unset; the row then wins
over the env."""

import asyncio
from collections.abc import Mapping
from decimal import Decimal

import psycopg
import pytest
from ashley.connections.connections import NullConnections
from ashley.connections.kinds import FIRST_HOUSEHOLD
from ashley.inference import compatible
from ashley.inference.keyed import Built
from ashley.inference.keyed_providers import KeyedProviders
from ashley.inference.key_seed import Outcome, seed_compatible_from_env
from ashley.inference.model import Entry, Message, Prompt, SystemPrompt, ToolChoice, ToolSpec, Usage
from ashley.inference.provider import Completion, Provider, ToolUse
from ashley.inference.provider_keys import ConnectionProviderKeys, KeyInForce
from ashley.inference.router import RoutedInference
from ashley.inference.routes import TASKS, parse
from ashley.people import admin
from ashley.settings import Settings
from ashley.wiring_providers import env_compatible
from catalogue_support import flat, of
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar
from pydantic import BaseModel
from speech_support import MemoryLedger
from test_connections_postgres import connections_on

pytestmark = pytest.mark.usefixtures("connection_kinds_wired")

LOCAL_URL = "http://llm.home.test:11434/v1"


class Answer(BaseModel):
    text: str


class Reached(Provider):
    """Named by its connection's label; answers with the address and key it was built with."""

    def __init__(self, key: KeyInForce) -> None:
        self._key = key

    @property
    def name(self) -> str:
        return self._key.label

    def check_params(self, params: Mapping[str, object]) -> None:
        return None

    async def complete[O: BaseModel](self, model: str, params: Mapping[str, object], system: SystemPrompt,
                                      messages: tuple[Entry, ...], tools: tuple[ToolSpec, ...], tool_choice: ToolChoice,
                                      output: type[O], timeout_s: float) -> Completion[O] | ToolUse:
        return Completion(output.model_validate({"text": f"{self._key.base_url} {self._key.secret}"}),
                          Usage(1_000_000, 1_000_000))


def reached(key: KeyInForce) -> Built:
    async def close() -> None:
        return None
    return Built((Reached(key),), {}, close)


def first_household(url: str) -> int:
    """The first household with an admin in it; the admin's id."""
    with psycopg.connect(url) as conn:
        home = admin.add_household(conn, "home", "UTC")
        assert home == FIRST_HOUSEHOLD
        person = admin.add_person(conn, home, "Alana")
        conn.execute("UPDATE people SET admin = true WHERE id = %s", (person,))
        return person


def routed(keyed: KeyedProviders, ledger: MemoryLedger) -> RoutedInference:
    by_task: dict[str, object] = {t: [{"provider": "nobody-connected-this", "model": "m", "timeout_s": 5}]
                                  for t in TASKS}
    by_task["chat"] = [{"provider": "nobody-connected-this", "model": "m", "timeout_s": 5},
                       {"provider": "groq", "model": "llama-x", "timeout_s": 5}]
    by_task["command"] = [{"provider": "deepseek", "model": "deepseek-chat", "timeout_s": 5}]
    catalogue = of({"groq": {"llama-x": flat("1", "2", None, None)},
                    "deepseek": {"deepseek-chat": flat("5", "5", None, None)}})
    return RoutedInference(parse({"cooldown_s": 300, "tasks": by_task}, {}), [], ledger, catalogue, keyed=keyed)


PROMPT = Prompt({"default": SystemPrompt("s")}, (Message("person", "hi"),))


def test_a_route_naming_a_connection_reaches_it_priced_as_the_picked_provider_and_a_custom_one_is_unpriced(
        db_url: str) -> None:
    alana = first_household(db_url)
    ledger = MemoryLedger()

    async def scenario() -> tuple[str, str]:
        async with connections_on(db_url) as connections:
            await connections.add_catalogued(FIRST_HOUSEHOLD, compatible.NAME, "groq", "https://api.groq.test/openai/v1",
                                             "gsk-picked", alana, "groq")
            await connections.add_catalogued(FIRST_HOUSEHOLD, compatible.NAME, "deepseek", "http://box.test:8000/v1",
                                             "custom-key", alana, None)
            keys = ConnectionProviderKeys(lambda: connections, (), {}, compatible.NAME, {})
            inference = routed(KeyedProviders([], keys, {}, compatible=reached), ledger)
            chat = await inference.generate("chat", PROMPT, Answer)
            command = await inference.generate("command", PROMPT, Answer)
            return chat.text, command.text
    chat, command = asyncio.run(scenario())
    assert chat == "https://api.groq.test/openai/v1 gsk-picked"
    assert command == "http://box.test:8000/v1 custom-key"
    costs = {(c.provider, c.model): c.cost_usd for c in ledger.calls}
    assert costs == {("groq", "llama-x"): Decimal(3), ("deepseek", "deepseek-chat"): None}


def test_the_env_seeds_the_local_row_once_never_over_a_row_and_the_row_then_wins(db_url: str) -> None:
    alana = first_household(db_url)
    env = env_compatible(Settings(database_url="", build_version="t", local_llm_url=LOCAL_URL + "/", local_llm_api_key=""))

    async def scenario() -> tuple[list[dict[str, Outcome]], dict[str, Outcome], KeyInForce, KeyInForce]:
        async with connections_on(db_url) as connections:
            first = list(await asyncio.gather(*(seed_compatible_from_env(connections, env) for _ in range(6))))
            keys = ConnectionProviderKeys(lambda: connections, (), {}, compatible.NAME, env)
            seeded = (await keys.in_force())["local"]
            row = next(c for c in await connections.of_household(FIRST_HOUSEHOLD) if c.label == "local")
            await connections.replace_catalogued(row.id, FIRST_HOUSEHOLD, alana, "https://llm.test/v1", "rotated", None)
            again = await seed_compatible_from_env(connections, env)
            return first, again, seeded, (await keys.in_force())["local"]
    first, again, seeded, replaced = asyncio.run(scenario())
    assert sorted(o["local"] for o in first) == ["kept"] * 5 + ["seeded"] and again == {"local": "kept"}
    assert (seeded.base_url, seeded.secret, seeded.catalogue_provider) == (LOCAL_URL, "none", None)
    assert seeded.connection_id is not None
    assert (replaced.base_url, replaced.secret) == ("https://llm.test/v1", "rotated")
    assert scalar(db_url, "SELECT count(*) FROM connections WHERE kind = %s", (compatible.NAME,)) == 1


def test_another_label_does_not_stop_the_seed_and_a_person_s_local_row_does(db_url: str) -> None:
    alana = first_household(db_url)
    env = env_compatible(Settings(database_url="", build_version="t", local_llm_url=LOCAL_URL, local_llm_api_key="env-key"))

    async def scenario() -> tuple[dict[str, Outcome], dict[str, Outcome]]:
        async with connections_on(db_url) as connections:
            await connections.add_catalogued(FIRST_HOUSEHOLD, compatible.NAME, "groq", "https://api.groq.test/openai/v1",
                                             "gsk", alana, "groq")
            seeded = await seed_compatible_from_env(connections, env)
            row = next(c for c in await connections.of_household(FIRST_HOUSEHOLD) if c.label == "local")
            await connections.remove(row.id, FIRST_HOUSEHOLD, None)
            await connections.add_catalogued(FIRST_HOUSEHOLD, compatible.NAME, "local", "https://mine.test/v1",
                                             "mine", alana, None)
            return seeded, await seed_compatible_from_env(connections, env)
    seeded, kept = asyncio.run(scenario())
    assert seeded == {"local": "seeded"} and kept == {"local": "kept"}
    assert scalar(db_url, "SELECT base_url FROM connections WHERE label = 'local'") == "https://mine.test/v1"


def test_nothing_is_seeded_when_the_env_is_unset_the_address_is_not_one_or_there_is_no_key() -> None:
    assert env_compatible(Settings(database_url="", build_version="t", local_llm_url="  ", local_llm_api_key="k")) == {}
    bad = {"local": KeyInForce(compatible.NAME, "k", None, "ftp://llm.test", "local")}
    good = env_compatible(Settings(database_url="", build_version="t", local_llm_url=LOCAL_URL, local_llm_api_key="k"))
    assert asyncio.run(seed_compatible_from_env(NullConnections(), bad)) == {"local": "bad_address"}
    assert asyncio.run(seed_compatible_from_env(NullConnections(), good)) == {"local": "no_key"}
    keys = ConnectionProviderKeys(NullConnections, (), {}, compatible.NAME, good)
    assert asyncio.run(keys.in_force())["local"].secret == "k"
