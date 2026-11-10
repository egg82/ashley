"""`bench_look` refusals: what cannot be looked at, a browser, a store or a record that is down, and a bench that is not
the asker's are error results, never raises, and keep nothing."""

import dataclasses
import logging
import re

import pytest
from ashley import services
from ashley.files.intake import key_of as file_key
from ashley.inference.model import Image
from ashley.looks.looker import Looker, NullLooker, Target
from ashley.looks.looks import Looks
from bench_look_blind_support import (CONFIG, PDF, PNG, SHOT_BYTES, FailingLooks, FakeLooker, FakeStore, fields_of, go, scene, sha)

K8S_NAME = re.compile(r"^look-[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


def test_with_nothing_to_draw_with_a_note_is_an_error_result_and_keeps_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            services.register(Looker, NullLooker())
            bench = await s.bench(s.w.alana)
            piece = await s.note(s.w.alana, bench)
            conv, turn = await s.asked(s.w.alana)
            for args in ({"piece_id": piece}, {}):
                result = await s.look(s.w.alana, bench, conv, turn.id, **args)
                assert result.is_error and result.images == () and result.content
            assert s.store.held == {} and await s.looks.in_conversation(s.w.alana.household_id, conv) == []

    go(scenario())


def test_with_nothing_to_draw_with_an_image_piece_can_still_be_looked_at(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            services.register(Looker, NullLooker())
            bench = await s.bench(s.w.alana)
            piece = await s.image(s.w.alana, bench)
            conv, turn = await s.asked(s.w.alana)
            result = await s.look(s.w.alana, bench, conv, turn.id, piece_id=piece)
            assert not result.is_error and result.images[0].media_type == "image/jpeg"

    go(scenario())


def test_an_image_that_cannot_be_made_small_enough_is_an_error_and_is_never_drawn(db_url: str,
                                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ashley.tools.bench_look.CONFIG", dataclasses.replace(CONFIG, max_image_bytes=1))

    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            piece = await s.image(s.w.alana, bench)
            conv, turn = await s.asked(s.w.alana)
            result = await s.look(s.w.alana, bench, conv, turn.id, piece_id=piece)
            assert result.is_error and result.content.startswith("too_large:") and result.images == ()
            assert s.looker.asked == []

    go(scenario())


def test_a_browser_that_fails_is_an_error_result_and_keeps_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url, looker=FakeLooker(fail="no_picture")) as s:
            bench = await s.bench(s.w.alana)
            conv, turn = await s.asked(s.w.alana)
            result = await s.look(s.w.alana, bench, conv, turn.id)
            assert result.is_error and result.images == ()
            assert s.store.held == {} and await s.looks.in_conversation(s.w.alana.household_id, conv) == []
            assert await s.looks.taken(s.w.alana.household_id, turn.id, "x") == 0

    go(scenario())


def test_a_screenshot_over_the_size_limit_is_not_given(db_url: str) -> None:
    async def scenario() -> None:
        huge = bytes.fromhex("ffd8ff") + b"\x00" * CONFIG.max_image_bytes
        async with scene(db_url, looker=FakeLooker(shot=huge)) as s:
            bench = await s.bench(s.w.alana)
            conv, turn = await s.asked(s.w.alana)
            result = await s.look(s.w.alana, bench, conv, turn.id)
            assert result.is_error and result.images == ()
            assert await s.looks.in_conversation(s.w.alana.household_id, conv) == []

    go(scenario())


def test_a_store_that_is_down_is_an_error_result_not_a_raise(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url, store=FakeStore(fail=frozenset({"put"}))) as s:
            bench = await s.bench(s.w.alana)
            conv, turn = await s.asked(s.w.alana)
            result = await s.look(s.w.alana, bench, conv, turn.id)
            assert result.is_error and result.images == ()
            assert await s.looks.in_conversation(s.w.alana.household_id, conv) == []

    go(scenario())


@pytest.mark.parametrize("verb", ["keep", "taken"])
def test_a_record_that_is_down_is_an_error_result_not_a_raise(db_url: str, verb: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            services.register(Looks, FailingLooks(s.looks, frozenset({verb})))
            bench = await s.bench(s.w.alana)
            conv, turn = await s.asked(s.w.alana)
            result = await s.look(s.w.alana, bench, conv, turn.id)
            assert result.is_error and result.images == ()

    go(scenario())


@pytest.mark.parametrize("piece", ["x", 1.5, -4, 10**9, True, [1]])
def test_a_piece_id_that_is_not_a_piece_of_the_bench_is_an_error_result(db_url: str, piece: object) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            await s.note(s.w.alana, bench)
            conv, turn = await s.asked(s.w.alana)
            result = await s.look(s.w.alana, bench, conv, turn.id, piece_id=piece)
            assert result.is_error and result.images == () and s.looker.asked == []
            assert await s.looks.in_conversation(s.w.alana.household_id, conv) == []

    go(scenario())


def test_a_piece_of_another_bench_is_not_looked_at(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            mine = await s.bench(s.w.alana, "mine")
            other = await s.bench(s.w.alana, "other")
            elsewhere = await s.image(s.w.alana, other)
            conv, turn = await s.asked(s.w.alana)
            result = await s.look(s.w.alana, mine, conv, turn.id, piece_id=elsewhere)
            assert result.is_error and result.images == ()
            assert s.store.held.keys() <= {file_key(s.w.alana.household_id, sha(PNG))}
            assert await s.looks.in_conversation(s.w.alana.household_id, conv) == []

    go(scenario())


def test_a_bench_of_another_household_is_not_looked_at(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            piece = await s.image(s.w.alana, bench)
            conv, turn = await s.asked(s.w.zed)
            for args in ({"piece_id": piece}, {}):
                result = await s.look(s.w.zed, bench, conv, turn.id, **args)
                assert result.is_error and result.images == ()
            assert s.looker.asked == []
            assert [k for k in s.store.held if k.startswith("look/")] == []

    go(scenario())


def test_another_person_in_the_household_does_not_look_at_a_bench_that_is_not_theirs(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            conv, turn = await s.asked(s.w.sam)
            result = await s.look(s.w.sam, bench, conv, turn.id)
            assert result.is_error and s.looker.asked == []

    go(scenario())


def test_a_refused_look_is_still_logged_as_a_tool_call(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with scene(db_url, looker=FakeLooker(fail="boom")) as s:
            bench = await s.bench(s.w.alana)
            conv, turn = await s.asked(s.w.alana)
            with caplog.at_level(logging.DEBUG):
                await s.look(s.w.alana, bench, conv, turn.id)
            assert fields_of(caplog, "tools.call")

    go(scenario())


def test_a_pdf_piece_is_drawn_not_given_as_bytes(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            from ashley.workshop import rules
            from ashley.workshop.bench_file import add_file
            from bench_look_blind_support import by
            bench = await s.bench(s.w.alana)
            _, applied = await add_file(s.w.alana, bench, by(s.w.alana), PDF, "a.pdf", "", rules.load())
            conv, turn = await s.asked(s.w.alana)
            result = await s.look(s.w.alana, bench, conv, turn.id, piece_id=applied.piece_id)
            assert result.images == (Image("image/jpeg", SHOT_BYTES),) and len(s.looker.asked) == 1

    go(scenario())


def test_an_image_whose_bytes_the_store_lost_is_an_error_result(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            piece = await s.image(s.w.alana, bench)
            s.store.held.clear()
            conv, turn = await s.asked(s.w.alana)
            result = await s.look(s.w.alana, bench, conv, turn.id, piece_id=piece)
            assert result.is_error and result.images == ()
            assert await s.looks.in_conversation(s.w.alana.household_id, conv) == []

    go(scenario())


def test_the_null_objects_draw_and_keep_nothing() -> None:
    from ashley.looks.looker import Looker, LookUnavailable
    from ashley.looks.looks import Looks, LooksUnavailable

    async def scenario() -> None:
        looker = Looker.null()
        assert isinstance(looker, NullLooker) and not looker.renders()
        with pytest.raises(LookUnavailable):
            await looker.look("look-x", Target(1, 1, 1, None))
        assert isinstance(Looks.null(), type(Looks.null()))
        with pytest.raises(LooksUnavailable):
            await Looks.null().taken(1, 1, "x")

    go(scenario())


def test_a_call_to_another_tool_name_is_an_error_result(db_url: str) -> None:
    from ashley.inference.model import ToolCall

    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            conv, turn = await s.asked(s.w.alana)
            result = await s.tools(s.w.alana, bench, conv, turn.id).call(ToolCall("x1", "bench_nothing", {}))
            assert result.is_error and s.looker.asked == []

    go(scenario())


def test_an_argument_the_tool_does_not_take_is_an_error_result(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            conv, turn = await s.asked(s.w.alana)
            result = await s.look(s.w.alana, bench, conv, turn.id, url="http://elsewhere.test/")
            assert result.is_error and s.looker.asked == []

    go(scenario())
