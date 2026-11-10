"""`bench_look` limits: a turn takes at most `max_looks_per_turn` pictures, counted from the record across tools, per turn,
per household, and a call run again replaces its own row."""

import re

from ashley.inference.model import Image
from ashley.looks.keys import key_of
from bench_look_blind_support import (CONFIG, PNG, SHOT_BYTES, FakeLooker, call, go, scene, sha)

K8S_NAME = re.compile(r"^look-[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


def test_a_turn_takes_at_most_the_configured_looks(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            conv, turn = await s.asked(s.w.alana)
            for _ in range(CONFIG.max_looks_per_turn):
                assert not (await s.look(s.w.alana, bench, conv, turn.id)).is_error
            drawn = len(s.looker.asked)
            over = await s.look(s.w.alana, bench, conv, turn.id)
            assert over.is_error and over.images == () and len(s.looker.asked) == drawn
            assert len(await s.looks.in_conversation(s.w.alana.household_id, conv)) == CONFIG.max_looks_per_turn

    go(scenario())


def test_the_limit_counts_image_pieces_looks_too(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            piece = await s.image(s.w.alana, bench)
            conv, turn = await s.asked(s.w.alana)
            for _ in range(CONFIG.max_looks_per_turn):
                assert not (await s.look(s.w.alana, bench, conv, turn.id, piece_id=piece)).is_error
            assert (await s.look(s.w.alana, bench, conv, turn.id, piece_id=piece)).is_error

    go(scenario())


def test_the_limit_is_per_turn(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            conv, first = await s.asked(s.w.alana)
            for _ in range(CONFIG.max_looks_per_turn):
                await s.look(s.w.alana, bench, conv, first.id)
            await s.answer(conv, first)
            _, second = await s.asked(s.w.alana, "again")
            assert not (await s.look(s.w.alana, bench, conv, second.id)).is_error

    go(scenario())


def test_a_call_run_again_at_the_limit_replaces_its_row_and_is_not_refused(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            conv, turn = await s.asked(s.w.alana)
            tools = s.tools(s.w.alana, bench, conv, turn.id)
            calls = [call() for _ in range(CONFIG.max_looks_per_turn)]
            for c in calls:
                assert not (await tools.call(c)).is_error
            assert not (await tools.call(calls[-1])).is_error
            assert len(await s.looks.in_conversation(s.w.alana.household_id, conv)) == CONFIG.max_looks_per_turn

    go(scenario())


def test_frames_kept_by_another_tool_count_against_the_turns_looks(db_url: str) -> None:
    from ashley.tools import bench_picture

    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            conv, turn = await s.asked(s.w.alana)
            hid = s.w.alana.household_id
            for i in range(CONFIG.max_looks_per_turn):
                assert await bench_picture.over_limit(hid, turn.id, f"f{i}", CONFIG.max_looks_per_turn) is None
                await bench_picture.keep(hid, (conv, turn.id), f"f{i}", bench, None, Image("image/jpeg", SHOT_BYTES + bytes([i])))
            assert await bench_picture.over_limit(hid, turn.id, "new", CONFIG.max_looks_per_turn) is not None
            assert await bench_picture.over_limit(hid, turn.id, "f0", CONFIG.max_looks_per_turn) is None
            assert (await s.look(s.w.alana, bench, conv, turn.id)).is_error
            assert s.looker.asked == []

    go(scenario())


def test_a_kept_picture_lives_under_the_look_prefix_and_names_its_row(db_url: str) -> None:
    from ashley.tools import bench_picture

    async def scenario() -> None:
        async with scene(db_url) as s:
            bench = await s.bench(s.w.alana)
            conv, turn = await s.asked(s.w.alana)
            hid = s.w.alana.household_id
            await bench_picture.keep(hid, (conv, turn.id), "f", bench, 7, Image("image/png", PNG))
            assert s.store.held == {key_of(hid, sha(PNG)): PNG}
            (look,) = await s.looks.in_conversation(hid, conv)
            assert (look.call_id, look.bench_id, look.piece_id, look.media_type, look.sha256, look.size) == (
                "f", bench, 7, "image/png", sha(PNG), len(PNG))

    go(scenario())


def test_a_look_that_fails_does_not_use_up_the_turns_looks(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url, looker=FakeLooker(fail="boom")) as s:
            bench = await s.bench(s.w.alana)
            conv, turn = await s.asked(s.w.alana)
            for _ in range(CONFIG.max_looks_per_turn + 2):
                await s.look(s.w.alana, bench, conv, turn.id)
            s.looker.fail = ""
            assert not (await s.look(s.w.alana, bench, conv, turn.id)).is_error

    go(scenario())


def test_the_limit_of_one_household_does_not_touch_anothers_turn(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            a_bench, z_bench = await s.bench(s.w.alana), await s.bench(s.w.zed)
            a_conv, a_turn = await s.asked(s.w.alana)
            z_conv, z_turn = await s.asked(s.w.zed)
            for _ in range(CONFIG.max_looks_per_turn):
                await s.look(s.w.alana, a_bench, a_conv, a_turn.id)
            assert (await s.look(s.w.alana, a_bench, a_conv, a_turn.id)).is_error
            assert not (await s.look(s.w.zed, z_bench, z_conv, z_turn.id)).is_error
            assert len(await s.looks.in_conversation(s.w.zed.household_id, z_conv)) == 1

    go(scenario())
