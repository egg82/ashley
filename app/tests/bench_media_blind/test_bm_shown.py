"""What she saw in a frames call is shown under her final answer to the message that asked (`ashley.api.chat_looks`), as a
picture link of the picture kept for the call, with the bench and piece it was of."""

from ashley.api.chat_looks import under_answers
from ashley.conversations.model import NewTurn
from bench_media_blind_support import JPEG, MP4, call, go, scene, sheet

KEY = b"k" * 40


def test_the_frames_are_shown_under_her_answer_not_under_the_question(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await s.put(MP4, "v.mp4")
            s.media.sheet_to_give = sheet(2, JPEG + b"-shown")
            await s.tools().call(call("bench_frames", piece_id=clip.id, at=[1, 2]))
            answer = await s.conversations.add_turn(s.conversation, NewTurn("ashley", "here is what I saw", answers=s.turn))
            found = await s.conversations.get(s.conversation)
            assert found is not None
            looks = await s.looks.in_conversation(s.alana.household_id, s.conversation)
            shown = under_answers(found.turns, looks, KEY)
            assert list(shown) == [answer.id]
            (one,) = shown[answer.id]
            assert (one.bench_id, one.piece_id, one.media_type) == (s.bench, clip.id, "image/jpeg")
            assert one.url is not None and one.expires_at is not None

    go(scenario())


def test_a_look_whose_message_has_no_answer_yet_is_shown_under_none(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await s.put(MP4, "v.mp4")
            await s.tools().call(call("bench_frames", piece_id=clip.id, at=[1]))
            found = await s.conversations.get(s.conversation)
            assert found is not None
            assert under_answers(found.turns, await s.looks.in_conversation(s.alana.household_id, s.conversation), KEY) == {}

    go(scenario())
