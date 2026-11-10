"""`bench_look` over the real Workshop, Postgres Looks and an in-memory store, with a fake browser: an image piece is
given as its own bytes and drawn by no browser; any other piece or the whole bench is a screenshot, kept in the store;
each look is recorded against the person turn, bounded per turn, and replaced when the same call runs again; what
cannot be drawn is an error and keeps nothing; the log names ids, bytes and how, never the picture or the page."""

import dataclasses
import hashlib
import io
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
from PIL import Image as PilImage
from files_support import GIF, sync
from look_pictures_support import noise
from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.files.intake import key_of as file_key
from ashley.looks.keys import key_of as look_key
from ashley.files.memory import MemoryStore
from ashley.files.store import NullStore, ObjectStore
from ashley.inference.model import Image, ToolCall, ToolResult
from ashley.live.live import Live
from ashley.looks.looker import Looker, LookUnavailable, Shot, Target
from ashley.looks.looks import Looks, NewLook
from ashley.looks.postgres import PostgresLooks
from ashley.tools import bench_look
from ashley.tools.bench_look import BenchLookTools
from ashley.workshop import rules as workshop_rules
from ashley.workshop.bench_file import add_file
from ashley.workshop.commands import Add
from ashley.workshop.model import HER, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, scalar
from live_support import FakeLive

RULES = workshop_rules.load()
PNG = noise((64, 48))
SHOT = b"\xff\xd8\xff\xe0" + b"s" * 20


@dataclass
class Browser(Looker):
    can: bool = True
    broken: bool = False
    looked: list[tuple[str, Target]] = field(default_factory=lambda: list[tuple[str, Target]]())

    def renders(self) -> bool:
        return self.can

    async def look(self, name: str, target: Target) -> Shot:
        self.looked.append((name, target))
        if self.broken:
            raise LookUnavailable("not_ready")
        return Shot(SHOT)


@dataclass
class World:
    url: str
    home: int
    owner: Owner
    bench: int
    conversation: int
    turn: int
    store: MemoryStore
    browser: Browser
    image_piece: int
    note_piece: int

    def tools(self, turn: int | None = None) -> BenchLookTools:
        return BenchLookTools(self.home, self.owner.person_id, self.bench, self.conversation, turn or self.turn)

    async def look(self, call_id: str = "c1", turn: int | None = None, **args: object) -> ToolResult:
        return await self.tools(turn).call(ToolCall(call_id, "bench_look", args))

    def rows(self) -> list[tuple[str, int | None, str, int]]:
        found: list[list[Any]] | None = scalar(
            self.url, "SELECT json_agg(json_build_array(call_id, piece_id, sha256, size) ORDER BY id) FROM bench_looks")
        return [(r[0], r[1], r[2], r[3]) for r in (found or [])]


@asynccontextmanager
async def world(url: str, browser: Browser | None = None) -> AsyncGenerator[World]:
    home = household(url)
    owner = Owner(home, person(url, home))
    conversation = int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                              (home,)))
    turn = int(scalar(url, "INSERT INTO turns (conversation_id, household_id, author, text) "
                           "VALUES (%s, %s, 'person', 'look') RETURNING id", (conversation, home)))
    database = PoolDatabase(url)
    await database.open()
    made = MemoryStore()
    chosen = browser or Browser()
    services.register(Live, FakeLive())
    services.register(Workshop, PostgresWorkshop(database, RULES))
    services.register(ObjectStore, made)
    services.register(Looks, PostgresLooks(database))
    services.register(Looker, chosen)
    try:
        shop = services.get(Workshop)
        bench = await shop.open(owner, "shed")
        _, image = await add_file(owner, bench.id, HER, PNG, "plan.png", "image/png", RULES)
        note = await shop.apply(owner, bench.id, Add(HER, "note", Text("memo", "hello"), "medium"))
        assert image.piece_id is not None and note.piece_id is not None
        yield World(url, home, owner, bench.id, conversation, turn, made, chosen, image.piece_id, note.piece_id)
    finally:
        for interface in (Live, Workshop, ObjectStore, Looks, Looker):
            services.unregister(interface)
        await database.close()


def seen(result: ToolResult) -> dict[str, object]:
    loaded: dict[str, object] = json.loads(result.content)
    return loaded


@sync
async def test_an_image_piece_is_given_as_its_own_bytes_and_no_browser_is_asked(db_url: str) -> None:
    async with world(db_url) as w:
        got = await w.look(piece_id=w.image_piece)
        assert not got.is_error, got.content
        (shown,) = got.images
        assert shown.media_type == "image/jpeg" and PilImage.open(io.BytesIO(shown.data)).size == (64, 48)
        assert seen(got)["how"] == "piece" and w.browser.looked == []
        sha = hashlib.sha256(shown.data).hexdigest()
        assert w.rows() == [("c1", w.image_piece, sha, len(shown.data))]
        assert w.store.objects[look_key(w.home, sha)] == shown.data


@sync
async def test_a_note_is_a_screenshot_kept_in_the_store_and_recorded(db_url: str) -> None:
    async with world(db_url) as w:
        got = await w.look(piece_id=w.note_piece)
        assert got.images == (Image("image/jpeg", SHOT),) and seen(got)["how"] == "screenshot"
        name, target = w.browser.looked[0]
        assert name.startswith("look-") and target == Target(w.home, w.owner.person_id, w.bench, w.note_piece)
        sha = hashlib.sha256(SHOT).hexdigest()
        assert w.store.objects[look_key(w.home, sha)] == SHOT
        assert w.rows() == [("c1", w.note_piece, sha, len(SHOT))]


@sync
async def test_the_whole_bench_is_a_screenshot_of_no_piece(db_url: str) -> None:
    async with world(db_url) as w:
        got = await w.look()
        assert got.images == (Image("image/jpeg", SHOT),) and seen(got)["of"] == "the whole bench"
        assert w.browser.looked[0][1].piece_id is None and w.rows()[0][1] is None


@sync
async def test_an_image_over_the_limit_is_made_to_fit_and_never_drawn(db_url: str,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bench_look, "CONFIG", dataclasses.replace(bench_look.CONFIG, max_image_bytes=len(PNG) - 1))
    async with world(db_url) as w:
        got = await w.look(piece_id=w.image_piece)
        assert seen(got)["how"] == "piece" and len(got.images[0].data) < len(PNG) and w.browser.looked == []


@sync
async def test_a_screenshot_over_the_limit_is_refused_and_kept_nowhere(db_url: str,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bench_look, "CONFIG", dataclasses.replace(bench_look.CONFIG, max_image_bytes=len(SHOT) - 1))
    async with world(db_url) as w:
        got = await w.look()
        assert got.is_error and got.content.startswith("too_large:") and got.images == ()
        assert w.rows() == [] and not [k for k in w.store.objects if k.startswith("look/")]


@sync
async def test_a_turn_takes_only_its_limit_of_looks_but_a_call_run_again_is_not_a_new_one(db_url: str,
                                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bench_look, "CONFIG", dataclasses.replace(bench_look.CONFIG, max_looks_per_turn=2))
    async with world(db_url) as w:
        assert not (await w.look("a")).is_error and not (await w.look("b")).is_error
        again = await w.look("b")
        assert not again.is_error and len(w.rows()) == 2
        over = await w.look("c")
        assert over.is_error and over.content.startswith("limit:") and len(w.browser.looked) == 3
        other = int(scalar(db_url, "INSERT INTO turns (conversation_id, household_id, author, text) "
                                   "VALUES (%s, %s, 'person', 'more') RETURNING id", (w.conversation, w.home)))
        assert not (await w.look("d", turn=other)).is_error


@sync
async def test_without_a_browser_only_an_image_piece_can_be_looked_at(db_url: str) -> None:
    async with world(db_url, Browser(can=False)) as w:
        assert not (await w.look(piece_id=w.image_piece)).is_error
        bad = await w.look("c2", piece_id=w.note_piece)
        assert bad.is_error and bad.content.startswith("no_browser:") and bad.images == ()
        assert len(w.rows()) == 1
        catalogue = await w.tools().catalogue()
        assert catalogue.instructions is not None and "Only an image piece" in catalogue.instructions


@sync
async def test_a_browser_that_fails_is_an_error_and_keeps_nothing(db_url: str) -> None:
    async with world(db_url, Browser(broken=True)) as w:
        bad = await w.look()
        assert bad.is_error and bad.content.startswith("unavailable:") and "not_ready" in bad.content
        assert w.rows() == [] and w.store.objects.keys() == {file_key(w.home, hashlib.sha256(PNG).hexdigest())}


@sync
async def test_a_store_that_cannot_keep_the_picture_is_an_error_and_she_is_given_nothing(db_url: str) -> None:
    async with world(db_url) as w:
        w.store.down = True
        bad = await w.look(piece_id=w.note_piece)
        assert bad.is_error and bad.images == () and w.rows() == []


@sync
async def test_a_piece_not_on_the_layout_and_bad_arguments_are_errors(db_url: str) -> None:
    async with world(db_url) as w:
        assert (await w.look(piece_id=999)).content.startswith("no_such_piece:")
        assert (await w.look(piece_id="x")).content.startswith("bad_arguments:")
        assert (await w.look(size=3)).content.startswith("bad_arguments:")
        wrong = await w.tools().call(ToolCall("c", "bench_read", {}))
        assert wrong.is_error and wrong.content.startswith("unknown_tool:")
        assert w.rows() == [] and w.browser.looked == []


@sync
async def test_another_persons_bench_is_not_found(db_url: str) -> None:
    async with world(db_url) as w:
        stranger = BenchLookTools(w.home, person(db_url, w.home, "other"), w.bench, w.conversation, w.turn)
        got = await stranger.call(ToolCall("c", "bench_look", {}))
        assert got.is_error and got.content.startswith("not_found:") and w.browser.looked == []


@sync
async def test_the_tool_is_offered_only_with_an_object_store(db_url: str) -> None:
    async with world(db_url) as w:
        assert [s.name for s in (await w.tools().catalogue()).specs] == ["bench_look"]
        services.register(ObjectStore, NullStore())
        assert (await w.tools().catalogue()).specs == ()


@sync
async def test_looks_are_read_back_by_conversation_household_and_a_second_for_a_call_replaces_the_first(db_url: str) -> None:
    async with world(db_url) as w:
        await w.look("a", piece_id=w.note_piece)
        own = (await w.look("b", piece_id=w.image_piece)).images[0]
        looks = await services.get(Looks).in_conversation(w.home, w.conversation)
        assert [(x.call_id, x.piece_id, x.media_type) for x in looks] == [("a", w.note_piece, "image/jpeg"),
                                                                           ("b", w.image_piece, "image/jpeg")]
        assert await services.get(Looks).in_conversation(w.home + 1000, w.conversation) == []
        sha = "f" * 64
        await services.get(Looks).keep(NewLook(w.home, w.conversation, w.turn, "a", w.bench, None, sha, "image/jpeg", 9))
        again = await services.get(Looks).in_conversation(w.home, w.conversation)
        assert [(x.call_id, x.sha256) for x in again] == [("a", sha), ("b", hashlib.sha256(own.data).hexdigest())]
        assert await services.get(Looks).taken(w.home, w.turn, "a") == 1


@sync
async def test_a_look_goes_when_its_turn_goes(db_url: str) -> None:
    async with world(db_url) as w:
        await w.look()
        scalar(db_url, "DELETE FROM turns WHERE id = %s RETURNING id", (w.turn,))
        assert w.rows() == []


@sync
async def test_the_log_names_ids_bytes_and_how_and_never_the_picture_or_the_page(db_url: str,
                                                                                caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    async with world(db_url) as w:
        await w.look(piece_id=w.note_piece)
    lines = [f"{r.getMessage()} {getattr(r, 'fields', {})}" for r in caplog.records if r.getMessage() == "tools.call"]
    assert len(lines) == 1
    assert "'how': 'screenshot'" in lines[0] and f"'bytes': {len(SHOT)}" in lines[0] and "'piece'" in lines[0]
    assert "hello" not in lines[0] and "memo" not in lines[0] and GIF.decode("latin-1") not in lines[0]
