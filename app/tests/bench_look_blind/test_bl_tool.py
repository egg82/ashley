"""`bench_look`: an image piece's own bytes, or a headless browser's screenshot of a piece or the whole bench, kept
under the look prefix and recorded against the turn."""

import dataclasses
import io
import logging
import re
from typing import Any

import pytest
from PIL import Image as PilImage
from ashley import services
from ashley.files.intake import key_of as file_key
from ashley.files.store import NullStore, ObjectStore
from ashley.inference.model import Image
from ashley.looks.keys import key_of
from ashley.looks.looker import Target
from bench_look_blind_support import (CONFIG, PNG, SHOT_BYTES, FakeLooker, call, fields_of, go, log_text, picture, scene, sha)

K8S_NAME = re.compile(r"^look-[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


def test_the_tool_is_offered_only_while_a_store_is_wired(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            conv, turn = await s.asked(s.w.alana)
            offered = (await s.tools(s.w.alana, bench, conv, turn.id).catalogue()).specs
            assert [spec.name for spec in offered] == ["bench_look"] and offered[0].reads
            services.register(ObjectStore, NullStore())
            assert (await s.tools(s.w.alana, bench, conv, turn.id).catalogue()).specs == ()

    go(scenario())


def test_the_spec_takes_an_optional_integer_piece_id(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            conv, turn = await s.asked(s.w.alana)
            (spec,) = (await s.tools(s.w.alana, 1, conv, turn.id).catalogue()).specs
            properties: Any = spec.parameters["properties"]
            assert properties["piece_id"] == {"type": "integer"} and set(properties) == {"piece_id", "region", "view"}
            assert not spec.parameters.get("required")

    go(scenario())


def test_the_instructions_say_only_an_image_piece_can_be_looked_at_while_nothing_draws(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url, looker=FakeLooker(draws=False)) as s:
            conv, turn = await s.asked(s.w.alana)
            without = (await s.tools(s.w.alana, 1, conv, turn.id).catalogue()).instructions or ""
            s.looker.draws = True
            drawing = (await s.tools(s.w.alana, 1, conv, turn.id).catalogue()).instructions or ""
            assert "Only an image piece" in without and "Only an image piece" not in drawing

    go(scenario())


def test_an_image_piece_is_given_as_its_own_bytes_without_a_browser(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            piece = await s.image(s.w.alana, bench)
            conv, turn = await s.asked(s.w.alana)
            result = await s.look(s.w.alana, bench, conv, turn.id, piece_id=piece)
            assert not result.is_error
            (shown,) = result.images
            assert shown.media_type == "image/jpeg" and PilImage.open(io.BytesIO(shown.data)).size == (64, 48)
            assert s.looker.asked == []

    go(scenario())


def test_an_image_pieces_own_bytes_are_copied_under_the_look_prefix(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            piece = await s.image(s.w.alana, bench)
            conv, turn = await s.asked(s.w.alana)
            (shown,) = (await s.look(s.w.alana, bench, conv, turn.id, piece_id=piece)).images
            hid = s.w.alana.household_id
            assert s.store.held[key_of(hid, sha(shown.data))] == shown.data
            assert s.store.held[file_key(hid, sha(PNG))] == PNG
            assert key_of(hid, sha(shown.data)) != file_key(hid, sha(PNG))

    go(scenario())


def test_an_image_piece_look_is_recorded_against_the_turn(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            piece = await s.image(s.w.alana, bench)
            conv, turn = await s.asked(s.w.alana)
            c = call(piece_id=piece)
            (shown,) = (await s.tools(s.w.alana, bench, conv, turn.id).call(c)).images
            (look,) = await s.looks.in_conversation(s.w.alana.household_id, conv)
            assert (look.turn_id, look.call_id, look.bench_id, look.piece_id) == (turn.id, c.id, bench, piece)
            assert (look.sha256, look.media_type, look.size) == (sha(shown.data), "image/jpeg", len(shown.data))

    go(scenario())


def test_an_image_piece_over_the_limit_is_made_to_fit_not_drawn(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ashley.tools.bench_look.CONFIG", dataclasses.replace(CONFIG, max_image_bytes=len(PNG) - 1))

    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            piece = await s.image(s.w.alana, bench)
            conv, turn = await s.asked(s.w.alana)
            result = await s.look(s.w.alana, bench, conv, turn.id, piece_id=piece)
            assert not result.is_error and len(result.images[0].data) < len(PNG)
            assert s.looker.asked == []

    go(scenario())


def test_a_note_piece_is_a_screenshot_narrowed_to_the_piece(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            piece = await s.note(s.w.alana, bench)
            conv, turn = await s.asked(s.w.alana)
            result = await s.look(s.w.alana, bench, conv, turn.id, piece_id=piece)
            assert not result.is_error and result.images == (Image("image/jpeg", SHOT_BYTES),)
            ((_, target),) = s.looker.asked
            assert target == Target(s.w.alana.household_id, s.w.alana.person_id, bench, piece)

    go(scenario())


def test_no_piece_is_the_whole_bench_as_the_person_sees_it(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            await s.note(s.w.alana, bench)
            conv, turn = await s.asked(s.w.alana)
            result = await s.look(s.w.alana, bench, conv, turn.id)
            assert not result.is_error and len(result.images) == 1
            ((_, target),) = s.looker.asked
            assert target == Target(s.w.alana.household_id, s.w.alana.person_id, bench, None)

    go(scenario())


def test_a_screenshot_is_kept_under_the_look_prefix_and_recorded(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            conv, turn = await s.asked(s.w.alana)
            c = call()
            await s.tools(s.w.alana, bench, conv, turn.id).call(c)
            hid = s.w.alana.household_id
            assert s.store.held == {key_of(hid, sha(SHOT_BYTES)): SHOT_BYTES}
            (look,) = await s.looks.in_conversation(hid, conv)
            assert (look.call_id, look.bench_id, look.piece_id, look.media_type, look.sha256, look.size) == (
                c.id, bench, None, "image/jpeg", sha(SHOT_BYTES), len(SHOT_BYTES))

    go(scenario())


def test_each_look_is_named_uniquely_and_safe_as_a_kubernetes_name(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            conv, turn = await s.asked(s.w.alana)
            for _ in range(3):
                await s.look(s.w.alana, bench, conv, turn.id)
            names = [name for name, _ in s.looker.asked]
            assert len(set(names)) == 3
            assert all(K8S_NAME.match(n) and len(n) <= 63 for n in names), names

    go(scenario())


def test_a_look_logs_its_bench_how_and_bytes_never_the_picture(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            piece = await s.image(s.w.alana, bench)
            conv, turn = await s.asked(s.w.alana)
            with caplog.at_level(logging.DEBUG):
                first = await s.look(s.w.alana, bench, conv, turn.id, piece_id=piece)
                await s.look(s.w.alana, bench, conv, turn.id)
            own, drawn = [f for f in fields_of(caplog, "tools.call") if "how" in f]
            assert (own["how"], own["bytes"]) == ("piece", len(first.images[0].data))
            assert (drawn["how"], drawn["bytes"]) == ("screenshot", len(SHOT_BYTES))
            assert bench in own.values() and piece in own.values()
            assert bench in drawn.values()
            assert "JFIF" not in log_text(caplog) and sha(SHOT_BYTES) not in log_text(caplog)

    go(scenario())


@pytest.mark.parametrize(("media", "data"), [
    ("image/jpeg", picture("JPEG")),
    ("image/gif", picture("GIF")),
    ("image/webp", picture("WEBP")),
])
def test_every_picture_type_the_providers_take_is_given_from_its_own_bytes(db_url: str, media: str, data: bytes) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            piece = await s.image(s.w.alana, bench, data, "p.bin")
            conv, turn = await s.asked(s.w.alana)
            result = await s.look(s.w.alana, bench, conv, turn.id, piece_id=piece)
            assert len(result.images) == 1 and result.images[0].media_type == "image/jpeg"
            assert PilImage.open(io.BytesIO(result.images[0].data)).size == (64, 48) and s.looker.asked == []
            (look,) = await s.looks.in_conversation(s.w.alana.household_id, conv)
            assert look.media_type == "image/jpeg"

    go(scenario())


def test_a_note_that_only_reads_like_a_stored_image_is_drawn_not_read_as_one(db_url: str) -> None:
    from ashley.files.intake import key_of as file_key_of
    from ashley.workshop.stored_file import StoredFile, body_of

    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            s.store.held[file_key_of(s.w.alana.household_id, sha(PNG))] = PNG
            body = body_of(StoredFile(sha(PNG), len(PNG), "image/png", "x.png"))
            piece = await s.note(s.w.alana, bench, "n", body)
            conv, turn = await s.asked(s.w.alana)
            result = await s.look(s.w.alana, bench, conv, turn.id, piece_id=piece)
            assert result.images == (Image("image/jpeg", SHOT_BYTES),) and len(s.looker.asked) == 1

    go(scenario())
