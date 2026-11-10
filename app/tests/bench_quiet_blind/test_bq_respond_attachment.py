"""`respond(inbound)` with an `attachment`: the paste is stored on the person's turn as `Turn.attachment`, read by her in full in
her turn and in later turns that carry it, and logged `respond.attached` by ids and length only."""

import asyncio
from dataclasses import replace

import pytest
from ashley.channels.respond import respond
from ashley.api.chat_models import ATTACHMENT_MAX_CHARS
from ashley.conversations.model import Attachment, Hearer, NewTurn
from bq_support import SECRET, capture, inbound, logged, read_by_her, real, reply, world_on
from contract.conversations_support import run, service
from respond_support import Fakes

TYPED = "can you tidy this up for me"
PASTE = "\n".join(f"line {i} {SECRET}" for i in range(40))


def test_the_paste_is_stored_on_the_persons_turn_and_the_text_stays_what_was_typed(wired: Fakes) -> None:
    wired.inference.script = [reply(20)]
    asyncio.run(respond(replace(inbound("chat", TYPED), attachment=Attachment("Notes", PASTE))))
    person, hers = wired.conversations.added
    assert (person.author, person.text, person.attachment) == ("person", TYPED, Attachment("Notes", PASTE))
    assert hers.author == "ashley" and hers.attachment is None


def test_no_paste_means_no_attachment_and_no_log(wired: Fakes, caplog: pytest.LogCaptureFixture) -> None:
    capture(caplog)
    wired.inference.script = [reply(20)]
    asyncio.run(respond(inbound("chat", TYPED)))
    assert wired.conversations.added[0].attachment is None
    assert logged(caplog, "respond.attached") == []


@pytest.mark.parametrize("size", [1, ATTACHMENT_MAX_CHARS - 1, ATTACHMENT_MAX_CHARS])
def test_she_reads_the_paste_in_full_up_to_the_maximum(wired: Fakes, size: int) -> None:
    text = "z" * (size - 1) + "E"
    wired.inference.script = [reply(20)]
    asyncio.run(respond(replace(inbound("chat", TYPED), attachment=Attachment(None, text))))
    seen = read_by_her(wired.inference.prompts[0])
    assert text in seen and TYPED in seen
    assert seen.count("z") == size - 1


def test_a_later_message_carries_the_earlier_paste_whole(wired: Fakes) -> None:
    wired.inference.script = [reply(20), reply(20)]
    asyncio.run(respond(replace(inbound("chat", TYPED), attachment=Attachment("Notes", PASTE))))
    asyncio.run(respond(inbound("chat", "and now shorter")))
    assert PASTE in read_by_her(wired.inference.prompts[1])


def test_the_log_has_ids_and_the_length_and_none_of_the_words(wired: Fakes, caplog: pytest.LogCaptureFixture) -> None:
    capture(caplog)
    wired.inference.script = [reply(20)]
    asyncio.run(respond(replace(inbound("chat", TYPED), attachment=Attachment("Secret title " + SECRET, PASTE))))
    lines = logged(caplog, "respond.attached")
    assert len(lines) == 1
    assert str(len(PASTE)) in lines[0].values()
    assert all(len(v) < 40 for v in lines[0].values())
    assert SECRET not in caplog.text and TYPED not in caplog.text


def test_the_paste_is_never_stored_on_her_turn_or_read_by_the_next_speaker(db_url: str, wired: Fakes) -> None:
    async def scenario() -> None:
        async with real(db_url, wired) as r:
            w = r.world
            wired.inference.script = [reply(20)] * 5
            alana = inbound("chat", TYPED, speaker_id=w.alana, household_id=w.home, thread="person:a:web")
            await respond(replace(alana, attachment=Attachment("T", PASTE)))
            sam = inbound("chat", "line 3 violet armadillo notes tidy", speaker_id=w.sam, household_id=w.home,
                          thread="person:s:web")
            await respond(sam)
            assert SECRET not in repr(wired.inference.prompts[1])
            assert TYPED not in read_by_her(wired.inference.prompts[1])
            assert not any(TYPED in line for line in wired.contexts[-1].said_before)
            again = await respond(inbound("chat", "again", speaker_id=w.alana, household_id=w.home,
                                          thread="person:a:web"))
            assert PASTE in read_by_her(wired.inference.prompts[2])
            await respond(inbound("chat", "tidy this up for me", speaker_id=w.alana, household_id=w.home,
                                  thread="person:a:phone"))
            assert PASTE in read_by_her(wired.inference.prompts[-1])
            conv = await r.conversations.get(again.conversation_id)
            assert conv is not None
            by_author = {t.author: t.attachment for t in conv.turns}
            assert by_author["ashley"] is None
            assert [t.attachment for t in conv.turns if t.author == "person"] == [Attachment("T", PASTE), None]

    run(scenario())


def test_another_person_never_carries_the_paste_by_any_hearer(db_url: str) -> None:
    async def scenario() -> None:
        async with service(db_url) as conversations:
            w = world_on(db_url)
            mine = await conversations.for_thread(w.home, "t-a", "chat", [w.alana], channel="web")
            await conversations.add_turn(mine.id, NewTurn("person", "typed words", w.alana, heard="private",
                                                          owner_id=w.alana, attachment=Attachment("T", PASTE)))
            sams = await conversations.for_thread(w.home, "t-s", "chat", [w.sam], channel="web")
            zeds = await conversations.for_thread(w.next_door, "t-z", "chat", [w.zed], channel="web")
            big = 10**9
            hearers = (("alana", Hearer(w.home, w.alana, True), mine.id), ("sam", Hearer(w.home, w.sam, True), sams.id),
                       ("sam shared", Hearer(w.home, w.sam, False), sams.id),
                       ("nobody", Hearer(w.home, None, False), sams.id), ("zed", Hearer(w.next_door, w.zed, True), zeds.id))
            got: dict[str, list[Attachment | None]] = {}
            for name, hearer, cid in hearers:
                carried = await conversations.carried(hearer, cid, big, "typed words attachment", 20, 20)
                got[name] = [t.attachment for t in (*carried.recent, *carried.relevant)]
            assert got["alana"] == [Attachment("T", PASTE)]
            assert all(v == [] for k, v in got.items() if k != "alana"), got

    run(scenario())


def test_only_a_persons_turn_may_carry_a_paste_and_a_blank_paste_is_refused(db_url: str) -> None:
    async def scenario() -> None:
        async with service(db_url) as conversations:
            w = world_on(db_url)
            conv = await conversations.for_thread(w.home, "t", "chat", [w.alana], channel="web")
            for turn in (NewTurn("ashley", "hers", attachment=Attachment("T", PASTE)),
                         NewTurn("person", "mine", w.alana, attachment=Attachment("T", " \n "))):
                with pytest.raises(ValueError):
                    await conversations.add_turn(conv.id, turn)
            read = await conversations.get(conv.id)
            assert read is not None and read.turns == ()

    run(scenario())


def test_a_paste_round_trips_through_the_database_exactly(db_url: str) -> None:
    async def scenario() -> None:
        async with service(db_url) as conversations:
            w = world_on(db_url)
            conv = await conversations.for_thread(w.home, "t", "chat", [w.alana], channel="web")
            pastes = (Attachment(None, "  lead\n\ttab é中\n"), Attachment("T" * 120, "m" * ATTACHMENT_MAX_CHARS))
            for paste in pastes:
                await conversations.add_turn(conv.id, NewTurn("person", "typed", w.alana, attachment=paste))
            await conversations.add_turn(conv.id, NewTurn("person", "plain", w.alana))
            read = await conversations.get(conv.id)
            assert read is not None
            assert [t.attachment for t in read.turns] == [*pastes, None]
            assert [t.text for t in read.turns] == ["typed", "typed", "plain"]

    run(scenario())
