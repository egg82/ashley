"""The Looks record as frames use it (`ashley.looks.looks.Looks`): one row per turn and call, a second keep of the same call
replaces the first, `taken` counts a turn's other calls, `in_conversation` is the household's, oldest first."""

from ashley.looks.looks import NewLook
from bench_media_blind_support import Scene, go, scene

H = "a" * 64


def new(s: Scene, call_id: str, sha: str = H, turn: int | None = None, size: int = 10, household: int | None = None) -> NewLook:
    return NewLook(s.alana.household_id if household is None else household, s.conversation, s.turn if turn is None else turn,
                   call_id, s.bench, 1, sha, "image/jpeg", size)


def test_a_kept_look_is_read_back_whole(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            made = await s.looks.keep(new(s, "c1", "b" * 64, size=77))
            (look,) = await s.looks.in_conversation(s.alana.household_id, s.conversation)
            assert (look.id, look.household_id, look.conversation_id, look.turn_id, look.call_id) == (made, s.alana.household_id, s.conversation, s.turn, "c1")
            assert (look.bench_id, look.piece_id, look.sha256, look.media_type, look.size) == (s.bench, 1, "b" * 64, "image/jpeg", 77)
            assert look.looked_at.tzinfo is not None

    go(scenario())


def test_the_same_call_kept_again_replaces_its_row(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            first = await s.looks.keep(new(s, "c1", "a" * 64, size=5))
            second = await s.looks.keep(new(s, "c1", "c" * 64, size=9))
            (look,) = await s.looks.in_conversation(s.alana.household_id, s.conversation)
            assert first == second == look.id and (look.sha256, look.size) == ("c" * 64, 9)

    go(scenario())


def test_taken_counts_the_turns_other_calls(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            other = await s.new_turn()
            for call_id in ("c1", "c2", "c3"):
                await s.looks.keep(new(s, call_id))
            await s.looks.keep(new(s, "c1", turn=other))
            assert await s.looks.taken(s.alana.household_id, s.turn, "c9") == 3
            assert await s.looks.taken(s.alana.household_id, s.turn, "c2") == 2
            assert await s.looks.taken(s.alana.household_id, other, "c1") == 0
            assert await s.looks.taken(s.other.household_id + 100, s.turn, "c9") == 0

    go(scenario())


def test_a_conversations_looks_come_oldest_first_and_only_to_its_household(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            ids = [await s.looks.keep(new(s, c, sha=ch * 64)) for c, ch in (("c3", "3"), ("c1", "1"), ("c2", "2"))]
            got = await s.looks.in_conversation(s.alana.household_id, s.conversation)
            assert [look.id for look in got] == ids == sorted(ids)
            assert await s.looks.in_conversation(s.alana.household_id + 100, s.conversation) == []
            assert await s.looks.in_conversation(s.alana.household_id, s.conversation + 100) == []

    go(scenario())
