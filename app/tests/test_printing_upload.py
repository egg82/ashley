"""`printing_upload` over the real Workshop and an in-memory object store, against a fake Bambuddy built from its OpenAPI
document: a bench's STL or 3MF file piece is read from the store and sent as the multipart `file`; Bambuddy's answer is
the library id `printing_queue` takes, or the earlier file when the library already held the same bytes; a piece that is
not an STL or 3MF, a piece that is not there, bytes the store lost and what Bambuddy turns away each come back as a typed
outcome; it is a `judged` change that returns no outside text."""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from ashley import services
from ashley.bambuddy.client import Bambuddy
from ashley.bambuddy.printing import BambuddyPrinting
from ashley.connections.connections import Connections
from ashley.db.pool import PoolDatabase
from ashley.files.intake import key_of
from ashley.files.memory import MemoryStore
from ashley.files.store import NullStore, ObjectStore
from ashley.inference.model import ToolCall
from ashley.live.live import Live
from ashley.printing.printing import Printing
from ashley.tools.printing_queue_specs import UPLOAD
from ashley.tools.printing_upload import PrintUploadTools
from ashley.workshop import rules as workshop_rules
from ashley.workshop.bench_file import add_file
from ashley.workshop.model import By, Owner
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from bambuddy_support import FakeBambuddy, held
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run
from files_support import PDF
from live_support import FakeLive

RULES = workshop_rules.load()
MODELS = Path(__file__).parent / "cad_models"
STL, THREEMF, STEP = "featuretype.STL", "featuretype.3MF", "featuretype.STEP"


@dataclass
class Bench:
    tools: PrintUploadTools
    fake: FakeBambuddy
    store: MemoryStore
    home: int
    pieces: dict[str, int]
    owner: Owner

    async def say(self, **arguments: object) -> tuple[str, dict[str, object]]:
        got = await self.tools.call(ToolCall("c", UPLOAD, arguments))
        return (got.content.split(":", 1)[0], {}) if got.is_error else ("ok", json.loads(got.content))


@asynccontextmanager
async def bench(url: str) -> AsyncGenerator[Bench]:
    home = household(url)
    owner = Owner(home, person(url, home))
    database = PoolDatabase(url)
    await database.open()
    fake, store = FakeBambuddy(), MemoryStore()
    services.register(Live, FakeLive())
    services.register(Workshop, PostgresWorkshop(database, RULES))
    services.register(ObjectStore, store)
    services.register(Connections, held(home))
    services.register(Bambuddy, fake.client())
    services.register(Printing, BambuddyPrinting())
    try:
        made = await services.get(Workshop).open(owner, "shed")
        pieces: dict[str, int] = {}
        for name, data in ((STL, (MODELS / STL).read_bytes()), (THREEMF, (MODELS / THREEMF).read_bytes()),
                           (STEP, (MODELS / STEP).read_bytes()), ("sheet.pdf", PDF)):
            _, applied = await add_file(owner, made.id, By(owner.person_id), data, name, "", RULES)
            assert applied.piece_id is not None
            pieces[name] = applied.piece_id
        yield Bench(PrintUploadTools(home, owner.person_id, made.id), fake, store, home, pieces, owner)
    finally:
        await database.close()


def test_a_stl_and_a_3mf_go_to_the_library_as_the_bytes_the_bench_holds(db_url: str) -> None:
    async def go() -> None:
        async with bench(db_url) as b:
            assert await b.say(piece=b.pieces[STL]) == ("ok", {"outcome": "uploaded", "file_id": "501"})
            assert await b.say(piece=b.pieces[THREEMF]) == ("ok", {"outcome": "uploaded", "file_id": "502"})
            assert b.fake.uploaded == [(STL, (MODELS / STL).read_bytes()), (THREEMF, (MODELS / THREEMF).read_bytes())]
    run(go())


def test_the_same_bytes_again_answer_with_the_file_the_library_already_holds(db_url: str) -> None:
    async def go() -> None:
        async with bench(db_url) as b:
            await b.say(piece=b.pieces[STL])
            assert await b.say(piece=b.pieces[STL]) == ("ok", {"outcome": "uploaded", "file_id": "501",
                                                              "already_there": True})
    run(go())


def test_what_is_not_an_stl_or_3mf_file_piece_is_not_sent(db_url: str) -> None:
    async def go() -> None:
        async with bench(db_url) as b:
            assert (await b.say(piece=b.pieces[STEP]))[0] == "not_a_model"
            assert (await b.say(piece=b.pieces["sheet.pdf"]))[0] == "not_a_model"
            assert (await b.say(piece=9999))[0] == "no_such_piece"
            assert b.fake.uploaded == [] and b.fake.seen == []
    run(go())


def test_bytes_the_store_lost_are_gone_and_nothing_is_sent(db_url: str) -> None:
    async def go() -> None:
        async with bench(db_url) as b:
            await b.store.delete(key_of(b.home, sha256((MODELS / STL).read_bytes()).hexdigest()))
            assert (await b.say(piece=b.pieces[STL]))[0] == "gone" and b.fake.uploaded == []
    run(go())


def test_what_bambuddy_turns_away_is_rejected_and_a_key_that_may_not_manage_the_library_is_refused(db_url: str) -> None:
    async def go() -> None:
        async with bench(db_url) as b:
            b.fake.refused_types = (".stl",)
            assert await b.say(piece=b.pieces[STL]) == ("ok", {"outcome": "rejected"})
            b.fake.forbidden.add("/api/v1/library/files")
            assert (await b.say(piece=b.pieces[THREEMF]))[0] == "refused"
            b.fake.forbidden.clear()
            b.fake.status = 503
            assert (await b.say(piece=b.pieces[THREEMF]))[0] == "unreachable"
    run(go())


def test_wrong_arguments_touch_neither_the_bench_nor_bambuddy(db_url: str) -> None:
    async def go() -> None:
        async with bench(db_url) as b:
            for arguments in ({}, {"piece": "1"}, {"piece": True}, {"piece": 0}):
                assert (await b.say(**arguments))[0] == "bad_arguments"
            assert b.fake.seen == []
    run(go())


def test_it_is_judged_returns_no_outside_text_and_is_offered_only_with_a_manager_and_a_store(db_url: str) -> None:
    async def go() -> None:
        async with bench(db_url) as b:
            (spec,) = (await b.tools.catalogue()).specs
            assert (spec.name, spec.reads, spec.outside, spec.tier) == (UPLOAD, False, False, "judged")
            other = PrintUploadTools(b.home + 1, b.owner.person_id, 1)
            assert (await other.catalogue()).specs == ()
            services.register(ObjectStore, NullStore())
            assert (await PrintUploadTools(b.home, b.owner.person_id, 1).catalogue()).specs == ()
    run(go())
