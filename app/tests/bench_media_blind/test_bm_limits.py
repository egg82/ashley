"""The per-turn look limit (`max_looks_per_turn`) as `bench_frames` and `bench_look` share it: counted per person turn
from the kept rows, a call run again replaces its own row, and a refused call or a failed job uses none up."""

from ashley.tools.bench_look import BenchLookTools
from ashley.runs.media import MediaUnavailable
from bench_media_blind_support import JPEG, LOOKS, MP4, PNG, Scene, call, go, scene, sheet, take


async def clip_scene(s: Scene) -> int:
    return (await s.put(MP4, "v.mp4")).id


def test_a_turn_takes_at_most_the_limit_of_pictures(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await clip_scene(s)
            for i in range(LOOKS.max_looks_per_turn):
                s.media.sheet_to_give = sheet(1, JPEG + bytes([i]))
                assert not (await take(s, clip)).is_error
            jobs = s.media.jobs()
            refused = await take(s, clip)
            assert refused.is_error and refused.images == ()
            assert len(s.looks_of()) == LOOKS.max_looks_per_turn and s.media.jobs() == jobs

    go(scenario())


def test_the_limit_is_shared_with_bench_look(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await clip_scene(s)
            image = (await s.put(PNG, "p.png")).id
            looking = BenchLookTools(s.alana.household_id, s.alana.person_id, s.bench, s.conversation, s.turn)
            taken = LOOKS.max_looks_per_turn - 1
            for _ in range(taken):
                assert not (await looking.call(call("bench_look", piece_id=image))).is_error
            s.media.sheet_to_give = sheet(1, JPEG + b"last")
            assert not (await take(s, clip)).is_error
            assert (await take(s, clip)).is_error
            assert (await looking.call(call("bench_look", piece_id=image))).is_error
            assert len(s.looks_of()) == LOOKS.max_looks_per_turn

    go(scenario())


def test_frames_already_taken_count_against_bench_look(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await clip_scene(s)
            image = (await s.put(PNG, "p.png")).id
            for i in range(LOOKS.max_looks_per_turn):
                s.media.sheet_to_give = sheet(1, JPEG + bytes([i]))
                await take(s, clip)
            looking = BenchLookTools(s.alana.household_id, s.alana.person_id, s.bench, s.conversation, s.turn)
            assert (await looking.call(call("bench_look", piece_id=image))).is_error

    go(scenario())


def test_the_count_is_per_turn(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await clip_scene(s)
            for i in range(LOOKS.max_looks_per_turn):
                s.media.sheet_to_give = sheet(1, JPEG + bytes([i]))
                await take(s, clip)
            fresh = await s.new_turn()
            s.media.sheet_to_give = sheet(1, JPEG + b"fresh")
            assert not (await take(s, clip, fresh)).is_error
            assert len(s.looks_of(fresh)) == 1

    go(scenario())


def test_a_call_run_again_at_the_limit_replaces_itself_instead_of_being_refused(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await clip_scene(s)
            last = call("bench_frames", piece_id=clip, at=[1])
            for i in range(LOOKS.max_looks_per_turn - 1):
                s.media.sheet_to_give = sheet(1, JPEG + bytes([i]))
                await take(s, clip)
            s.media.sheet_to_give = sheet(1, JPEG + b"first")
            assert not (await take(s, clip, call_=last)).is_error
            s.media.sheet_to_give = sheet(1, JPEG + b"second")
            assert not (await take(s, clip, call_=last)).is_error
            assert len(s.looks_of()) == LOOKS.max_looks_per_turn

    go(scenario())


def test_a_refused_call_or_a_failed_job_does_not_use_up_a_look(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await clip_scene(s)
            s.media.sheet_to_give = MediaUnavailable("unreadable")
            for _ in range(LOOKS.max_looks_per_turn + 2):
                assert (await take(s, clip)).is_error
            for _ in range(LOOKS.max_looks_per_turn + 2):
                assert (await s.tools().call(call("bench_frames", piece_id=clip, at=[]))).is_error
            s.media.sheet_to_give = sheet()
            assert not (await take(s, clip)).is_error

    go(scenario())


