"""The code host tools' tests share these: the real database, connections, workshop and fake forges wired as one
rig, a person's tools, and one call as a result."""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from ashley import services
from ashley.codehost.config import CodeHostConfig
from ashley.codehost.host import CodeHost
from ashley.connections.connections import Connections
from ashley.connections.model import Kind
from ashley.connections.postgres import PostgresConnections
from ashley.db.pool import PoolDatabase
from ashley.files.store import ObjectStore
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.live.live import Live
from ashley.tools.code_host import CodeHostTools
from ashley.workshop import rules as workshop_rules
from ashley.workshop.model import Owner
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from live_support import FakeLive
from hos_support import RESULT_CHARS, FakeStore, SMALL, World, connect, sealer, world
from hos_forges_support import Forges, standard

PNG = bytes.fromhex("89504e470d0a1a0a") + b"\x00\x00\x00\rIHDRrest"
GIT_TOOLS = {"git_projects", "git_tree", "git_read_file"}


@dataclass
class Rig:
    w: World
    forges: Forges
    store: FakeStore
    workshop: Workshop
    connections: Connections
    config: CodeHostConfig

    def tools(self, household: int, person: int, bench: int | None = None) -> CodeHostTools:
        return CodeHostTools(household, person, bench, self.config, RESULT_CHARS)

    async def bench(self, household: int, person: int, title: str = "work") -> int:
        return (await self.workshop.open(Owner(household, person), title)).id

    async def pieces(self, household: int, person: int, bench: int) -> list[tuple[str, str]]:
        view = await self.workshop.read(Owner(household, person), bench)
        return [(p.kind, p.text.title) for p in view.pieces]

    async def hold(self, person: int, household: int, kind: Kind, token: str) -> None:
        await connect(self.connections, person, household, kind, token)


@asynccontextmanager
async def rig(url: str, forges: Forges | None = None, config: CodeHostConfig = SMALL,
              store: FakeStore | None = None) -> AsyncGenerator[Rig]:
    w, f, held = world(url), forges if forges is not None else standard(), store if store is not None else FakeStore()
    db = PoolDatabase(url)
    await db.open()
    conns = PostgresConnections(db, sealer())
    workshop = PostgresWorkshop(db, workshop_rules.load())
    services.register(Connections, conns)
    services.register(CodeHost, f.routed(config))
    services.register(Live, FakeLive())
    services.register(Workshop, workshop)
    services.register(ObjectStore, held)
    try:
        yield Rig(w, f, held, workshop, conns, config)
    finally:
        await db.close()


def asked(name: str, **args: object) -> ToolCall:
    return ToolCall("call-1", name, args)


async def use(tools: CodeHostTools, name: str, **args: object) -> ToolResult:
    got = await tools.call(asked(name, **args))
    assert got.call_id == "call-1"
    return got


def host_enum(spec: ToolSpec) -> list[str]:
    """The hosts a tool's schema offers, [] when it names none."""
    schema = json.loads(json.dumps(spec.parameters))
    return list(schema["properties"]["host"].get("enum", []))
