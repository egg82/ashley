"""She reacts to a person's changes on a bench, over a real database: after their commands go quiet for the pause she
gets one turn on the bench's thread, handed the commands after the last she has seen (ids and kinds), once. Her
`worth_saying` decides whether anything is posted, a bench's reactions are rate capped, her own commands never wake
her, and a reaction killed part way is finished by the resumer as the same turn."""

import asyncio
from dataclasses import replace

import pytest
from ashley.channels import respond as respond_module
from ashley.channels import resume, unprompted
from ashley.channels.wake import bench_reacts
from ashley.channels.wake.bench_react_config import CONFIG, load
from ashley.channels.wake.bench_react_turn import NOTE
from ashley.conversations.conversations import Conversations
from ashley.inference.model import Prompt, ToolCall, ToolCalls
from ashley.workshop.commands import Add, Edit
from ashley.workshop.model import HER, By, Text
from bench_reacts_support import QUIETLY, SAYS, SECRET, has_aside, last_message, world
from contract.conversations_support import db_url as db_url, events, migrated_template as migrated_template
from contract.conversations_support import run, scalar
from ashley import logs
from ashley import services

VIDEO = '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
PAUSE = CONFIG.pause_s + 1


def test_the_pause_and_the_cap_are_data_in_the_json_config() -> None:
    assert load() == CONFIG and CONFIG.pause_s > 0 and CONFIG.max_reactions >= 1


def test_commands_still_within_the_pause_wake_nothing_and_after_it_one_turn_lists_them_by_id_and_kind(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            piece = await w.person_adds(bench)
            await w.person_edits(bench, piece, 1)
            w.model.script = [SAYS]
            reacts = bench_reacts.BenchReacts()
            assert await reacts.sweep() == 0 and w.turns() == []
            w.quiet_for(PAUSE)
            assert await reacts.sweep() == 1
            [prompt] = w.model.prompts
            said = last_message(prompt)
            assert f"#{piece} add document {piece}" in said and f"#{piece + 1} edit document {piece}" in said
            assert NOTE in said and SECRET not in said
            [(author, text, source), hers] = w.turns()
            assert author == "household" and source == f"bench_react:{bench}:{piece + 1}"
            assert hers == ("ashley", SAYS.text, None) and text.startswith("2 changes on the bench")
            assert w.mark(bench) == piece + 1
    run(go())


def test_a_reply_none_posts_nothing_to_the_talk_and_the_changes_are_still_marked_seen(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            await w.person_adds(bench)
            w.quiet_for(PAUSE)
            w.model.script = [QUIETLY]
            logs.setup()
            assert await bench_reacts.BenchReacts().sweep() == 1
            turns = await services.get(Conversations).on_thread(w.home, f"bench:{bench}")
            assert turns is not None and unprompted.shown(turns.turns) == []
            assert [t.text for t in turns.turns if t.author == "ashley"] == [unprompted.QUIET]
            assert w.mark(bench) == 1
    run(go())


def test_a_conversation_holding_only_a_quiet_reaction_is_not_listed_and_one_with_more_counts_what_shows(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            await w.person_adds(bench)
            w.quiet_for(PAUSE)
            w.model.script = [QUIETLY]
            await bench_reacts.BenchReacts().sweep()
            thread = f"bench:{bench}"
            page = await services.get(Conversations).of_person(w.home, w.elodie, 10, None, thread)
            assert page.items == ()
            scalar(db_url, "INSERT INTO turns (conversation_id, household_id, author, speaker_id, text) "
                           "SELECT conversation_id, household_id, 'person', %s, 'hello' FROM turns LIMIT 1 RETURNING id", (w.elodie,))
            page = await services.get(Conversations).of_person(w.home, w.elodie, 10, None, thread)
            assert [i.turns for i in page.items] == [1]
    run(go())


def test_the_log_says_the_bench_commands_handed_and_reply_or_none_never_a_piece(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            await w.person_adds(bench, title=SECRET)
            w.quiet_for(PAUSE)
            w.model.script = [QUIETLY]
            logs.setup()
            await bench_reacts.BenchReacts().sweep()
            seen = capsys.readouterr()
            [done] = events(seen.out + seen.err, "bench_reacts.done")
            assert done["bench"] == str(bench) and done["commands"] == "1" and done["outcome"] == "none"
            assert SECRET not in seen.out + seen.err
    run(go())


def test_the_next_reaction_is_handed_only_what_came_after_the_mark_and_never_the_same_change_twice(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            piece = await w.person_adds(bench)
            w.quiet_for(PAUSE)
            w.model.script = [SAYS, SAYS]
            reacts = bench_reacts.BenchReacts()
            assert await reacts.sweep() == 1
            assert await reacts.sweep() == 0 and len(w.model.prompts) == 1
            w.quiet_for(PAUSE)
            await w.person_edits(bench, piece, 1)
            w.quiet_for(PAUSE)
            assert await reacts.sweep() == 1
            second = last_message(w.model.prompts[1])
            assert f"#{piece + 1} edit document {piece}" in second and f"#{piece} add" not in second
    run(go())


def test_her_own_commands_never_wake_her_and_a_bench_with_only_hers_has_nothing_unseen(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            await w.she_adds(bench)
            w.quiet_for(PAUSE)
            assert await bench_reacts.BenchReacts().sweep() == 0 and w.model.prompts == []
            await w.person_adds(bench)
            w.quiet_for(PAUSE)
            w.model.script = [SAYS]
            assert await bench_reacts.BenchReacts().sweep() == 1
            assert "#1" not in last_message(w.model.prompts[0]) and "#2 add" in last_message(w.model.prompts[0])
    run(go())


def test_a_cue_is_no_activity_of_the_person_and_does_not_reset_the_pause(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            done = await w.workshop.apply(w.owner, bench, Add(By(w.elodie), "video", Text("v", VIDEO), "medium"))
            w.quiet_for(PAUSE)
            await w.video_cue(bench, HER, done.seq)
            await w.video_cue(bench, By(w.elodie), done.seq)
            w.model.script = [SAYS]
            assert await bench_reacts.BenchReacts().sweep() == 1
            assert "#1 add video" in last_message(w.model.prompts[0]) and "#2" not in last_message(w.model.prompts[0])
            assert w.mark(bench) == done.seq
            w.quiet_for(PAUSE)
            await w.video_cue(bench, HER, done.seq)
            w.quiet_for(PAUSE)
            assert await bench_reacts.BenchReacts().sweep() == 0 and len(w.model.prompts) == 1
    run(go())


def test_a_refused_command_and_a_closed_bench_wake_nothing(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            done = await w.bench()
            await w.person_adds(done)
            await w.workshop.close(w.owner, done)
            bench = await w.bench()
            refused = await w.workshop.apply(w.owner, bench, Edit(By(w.elodie), 99, 1, Text("x", "y")))
            assert refused.outcome != "accepted"
            w.quiet_for(PAUSE)
            assert await bench_reacts.BenchReacts().sweep() == 0 and w.model.prompts == []
    run(go())


def test_a_bench_that_reacted_the_most_times_in_the_window_waits_until_one_leaves_it(db_url: str,
                                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bench_reacts, "CONFIG", replace(CONFIG, max_reactions=1))

    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            piece = await w.person_adds(bench)
            w.quiet_for(PAUSE)
            w.model.script = [SAYS, SAYS]
            reacts = bench_reacts.BenchReacts()
            assert await reacts.sweep() == 1
            await w.person_edits(bench, piece, 1)
            w.quiet_for(PAUSE)
            assert await reacts.sweep() == 0 and len(w.model.prompts) == 1
            w.quiet_for(CONFIG.window_s)
            assert await reacts.sweep() == 1 and len(w.model.prompts) == 2
    run(go())


def test_records_past_their_keeping_go_but_the_newest_stays_as_the_mark(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            piece = await w.person_adds(bench)
            await w.workshop.reacted(w.home, bench, piece, 100.0)
            await w.person_edits(bench, piece, 1)
            await w.workshop.reacted(w.home, bench, piece + 1, 100.0)
            w.quiet_for(1000)
            await w.workshop.reacted(w.home, bench, piece + 1, 100.0)
            assert scalar(db_url, "SELECT count(*) FROM bench_reactions WHERE bench_id = %s", (bench,)) == 1
            assert w.mark(bench) == piece + 1
    run(go())


def test_a_reaction_killed_part_way_is_finished_by_the_resumer_and_handing_it_in_again_is_the_same_turn(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            await w.person_adds(bench)
            w.quiet_for(PAUSE)
            w.model.hang = True
            w.model.script = [ToolCalls((ToolCall("c1", "look", {}),))]
            sweeping = asyncio.create_task(bench_reacts.BenchReacts().sweep())
            await asyncio.wait_for(w.model.reached.wait(), 10)
            sweeping.cancel()
            with pytest.raises(asyncio.CancelledError):
                await sweeping
            assert w.mark(bench) == 0
            scalar(db_url, "WITH u AS (UPDATE turn_work SET claimed_until = clock_timestamp() - interval '1 second' "
                           "RETURNING 1) SELECT count(*) FROM u")
            w.model.hang = False
            w.model.script = [SAYS]
            assert await resume.sweep() == 1
            assert await bench_reacts.BenchReacts().sweep() == 1
            assert [t[0] for t in w.turns()] == ["household", "ashley"] and w.mark(bench) == 1
            assert scalar(db_url, "SELECT count(*) FROM turn_work") == 0
    run(go())


LOOKING = ToolCalls((ToolCall("c1", "look", {"aside": "I am reading the new files."}),))


@pytest.fixture
def holds_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    limits = respond_module.LIMITS
    monkeypatch.setitem(limits, "brainstorm", replace(limits["brainstorm"], hold_after_s=0.0))


def asides_offered(prompt: Prompt) -> bool:
    return bool(prompt.tools) and all(has_aside(t) for t in prompt.tools)


def test_a_reaction_that_works_past_the_hold_budget_says_her_aside_and_the_answer_follows(
        db_url: str, holds_at_once: None) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            await w.person_adds(bench)
            w.quiet_for(PAUSE)
            w.model.script = [LOOKING, SAYS]
            assert await bench_reacts.BenchReacts().sweep() == 1
            await w.until_hers(2)
            assert asides_offered(w.model.prompts[0])
            assert [(a, t) for a, t, _ in w.turns() if a == "ashley"] == [
                ("ashley", "I am reading the new files."), ("ashley", SAYS.text)]
    run(go())


def test_a_reaction_whose_answer_is_quiet_after_its_aside_keeps_the_aside_on_the_page_and_hides_the_rest(
        db_url: str, holds_at_once: None) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            await w.person_adds(bench)
            w.quiet_for(PAUSE)
            w.model.script = [LOOKING, QUIETLY]
            assert await bench_reacts.BenchReacts().sweep() == 1
            await w.until_hers(2)
            turns = await services.get(Conversations).on_thread(w.home, f"bench:{bench}")
            assert turns is not None
            assert [t.text for t in unprompted.shown(turns.turns)] == ["I am reading the new files."]
            assert [t.text for t in turns.turns if t.author == "ashley"] == [
                "I am reading the new files.", unprompted.QUIET]
            assert scalar(w.url, "SELECT count(*) FROM outbox") == 0
    run(go())
