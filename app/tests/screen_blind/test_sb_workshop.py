"""Contract 7 to 11 through `apply_screen` on a real database: what `decide` refuses is logged as the next seq, changes
nothing and is what `screen` then reads; a limit built into the rules holds across commands."""

import json

from ashley.workshop.commands import Edit, Remove, Undo
from ashley.workshop.model import By, Text
from ashley.workshop.screen_controls import encode
from contract.conversations_support import run
from sb_support import (CLOCK, CONTROLS, CONVERSATION, HALL, NIGHT, PORCH, add, benches_of, buttons_of, env, log_of, mv,
                        replayed, wide_rules)


def test_k07_undo_of_a_remove_after_the_kind_was_re_added_is_refused_and_one_clock_remains(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            w, me = e.world, By(e.world.alana.person_id)
            gone = await e.workshop.apply_screen(w.home, w.tablet, Remove(me, CLOCK))
            await e.workshop.apply_screen(w.home, w.tablet, add(w.alana, "clock", "Clock"))
            undone = await e.workshop.apply_screen(w.home, w.tablet, Undo(me, gone.seq))
            assert undone.outcome in ("changed_since", "already_shown")
            view = await e.workshop.screen(w.home, w.tablet)
            assert [p.kind for p in view.pieces].count("clock") == 1 and view.seq == undone.seq
            assert replayed(db_url, w.tablet)[0] == view.pieces

    run(scenario())


def test_k07_an_add_of_a_held_kind_is_logged_refused_and_changes_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            w = e.world
            before = (await e.workshop.screen(w.home, w.tablet)).pieces
            got = await e.workshop.apply_screen(w.home, w.tablet, add(w.alana, "home", "Who's home"))
            assert (got.seq, got.outcome, got.piece_id) == (5, "already_shown", None)
            after = await e.workshop.screen(w.home, w.tablet)
            assert after.pieces == before and after.seq == 5 and after.laid_out
            assert [o for _, _, o in log_of(db_url, w.tablet)][-1] == "already_shown"

    run(scenario())


def test_k08_the_conversation_cannot_be_removed_even_as_the_first_command_and_the_bench_is_still_made(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            w = e.world
            got = await e.workshop.apply_screen(w.home, w.tablet, Remove(By(w.alana.person_id), CONVERSATION))
            assert (got.seq, got.outcome) == (5, "required")
            view = await e.workshop.screen(w.home, w.tablet)
            assert view.laid_out and len(view.pieces) == 4 and benches_of(db_url, w.tablet) != []

    run(scenario())


def test_k08_an_undo_of_the_conversations_add_is_required_through_the_workshop(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            w = e.world
            got = await e.workshop.apply_screen(w.home, w.tablet, Undo(By(w.alana.person_id), 4))
            assert got.outcome == "required"
            assert any(p.kind == "conversation" for p in (await e.workshop.screen(w.home, w.tablet)).pieces)

    run(scenario())


def test_k09_the_ninth_piece_is_full_under_rules_built_here(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url, wide_rules(9, 8)) as e:
            w = e.world
            outcomes = [(await e.workshop.apply_screen(w.home, w.tablet, add(w.alana, f"k{i}", f"K{i}"))).outcome
                        for i in range(1, 6)]
            assert outcomes == ["accepted"] * 4 + ["full"]
            assert len((await e.workshop.screen(w.home, w.tablet)).pieces) == 8

    run(scenario())


def test_k10_move_through_the_workshop_keeps_orders_contiguous_and_past_the_end_is_bad_place(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            w = e.world
            moved = await e.workshop.apply_screen(w.home, w.tablet, mv(w.alana, CONVERSATION, 0, "large"))
            assert (moved.outcome, moved.piece_id) == ("accepted", CONVERSATION)
            view = await e.workshop.screen(w.home, w.tablet)
            assert [(p.id, p.place.order, p.place.size) for p in view.pieces] == [
                (4, 0, "large"), (1, 1, "small"), (2, 2, "small"), (3, 3, "medium")]
            assert view.pieces[0].changed_by == moved.seq
            refused = await e.workshop.apply_screen(w.home, w.tablet, mv(w.sam, CLOCK, 4))
            assert refused.outcome == "bad_place"
            assert (await e.workshop.screen(w.home, w.tablet)).pieces == view.pieces

    run(scenario())


def test_k11_a_controls_edit_is_bad_controls_when_malformed_stale_when_old_and_bumps_the_version_when_good(
        db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            w, me = e.world, By(e.world.alana.person_id)
            too_many = json.dumps([{"id": f"b{i}", "label": "B", "action": "light.turn_on", "entity_id": f"light.z{i}"}
                                   for i in range(13)])
            bad = await e.workshop.apply_screen(w.home, w.tablet, Edit(me, CONTROLS, 1, Text("Controls", too_many)))
            assert bad.outcome == "bad_controls"
            good = await e.workshop.apply_screen(w.home, w.tablet,
                                                 Edit(me, CONTROLS, 1, Text("Controls", encode((PORCH, HALL)))))
            assert good.outcome == "accepted"
            stale = await e.workshop.apply_screen(w.home, w.tablet, Edit(me, CONTROLS, 1, Text("Controls", encode((NIGHT,)))))
            assert stale.outcome == "stale_base"
            view = await e.workshop.screen(w.home, w.tablet)
            controls = next(p for p in view.pieces if p.id == CONTROLS)
            assert controls.version == 2 and buttons_of(view) == (PORCH, HALL)
            assert view.undo_next == good.seq

    run(scenario())
