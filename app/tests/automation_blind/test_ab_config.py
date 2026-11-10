"""An automation piece's body as Home Assistant's config: which texts are configs, which can be installed, what a config
read from the house becomes as a body, and which proposal each piece is waiting on."""

import json
from typing import Any

from ab_support import CONFIG, add, body, bench_with_piece, crowd, edit, installed, propose
from ashley import services
from ashley.workshop import automation_config as ac
from ashley.workshop.commands import Installed, Proposed
from ashley.workshop.proposals import pending
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, run
from hypothesis import given
from hypothesis import strategies as st


def test_a_full_config_is_well_formed_complete_and_read_back_whole() -> None:
    assert ac.well_formed(body()) and ac.complete(body())
    assert ac.config_of(body()) == CONFIG


def test_an_empty_body_is_a_draft_well_formed_but_neither_a_config_nor_complete() -> None:
    for empty in ("", "   ", "\n"):
        assert ac.well_formed(empty) and not ac.complete(empty) and ac.config_of(empty) is None


def test_texts_that_are_not_a_json_object_of_the_shape_are_not_well_formed() -> None:
    for text in ("nope", "[]", "1", "null", '"alias"', "{", body(id="x"), body(bogus=1), body(triggers={}),
                 body(triggers=[1]), body(actions=["x"]), body(conditions=[list[int]()]), body(alias=3), body(mode=list[int]()),
                 body(description=5)):
        assert not ac.well_formed(text), text
        assert ac.config_of(text) is None, text
        assert not ac.complete(text), text


def test_the_optional_fields_home_assistant_takes_are_allowed() -> None:
    text = body(max=5, max_exceeded="silent", variables={"a": 1}, trigger_variables={"b": 2})
    assert ac.well_formed(text) and ac.complete(text)


def test_complete_needs_a_non_blank_alias_a_trigger_and_an_action() -> None:
    for changes in (dict(alias=""), dict(alias=" \t"), dict(triggers=[]), dict(actions=[])):
        assert ac.well_formed(body(**changes)) and not ac.complete(body(**changes)), changes
    for missing in ("alias", "triggers", "actions"):
        config = dict(CONFIG)
        del config[missing]
        assert not ac.complete(json.dumps(config)), missing


def test_conditions_and_description_are_not_needed_to_install() -> None:
    config = {k: v for k, v in CONFIG.items() if k not in ("conditions", "description", "mode")}
    assert ac.complete(json.dumps(config))


def test_a_config_read_from_the_house_becomes_a_body_without_its_id() -> None:
    from_house: dict[str, Any] = {"id": "1234", **CONFIG}
    got = ac.body_of(from_house)
    assert ac.config_of(got) == CONFIG and ac.complete(got) and "1234" not in got


def test_older_singular_names_become_the_plural_ones() -> None:
    old = {"id": "1", "alias": "a", "trigger": [{"platform": "time", "at": "01:00:00"}],
           "condition": [{"condition": "state", "entity_id": "x", "state": "on"}],
           "action": [{"service": "light.turn_on"}]}
    got = ac.config_of(ac.body_of(old))
    assert got is not None
    assert got["triggers"] == old["trigger"] and got["conditions"] == old["condition"] and got["actions"] == old["action"]
    assert not {"trigger", "condition", "action", "id"} & set(got)
    assert ac.complete(ac.body_of(old))


@given(st.dictionaries(st.text(max_size=6), st.integers() | st.text(max_size=5) | st.none(), max_size=4))
def test_a_body_that_is_complete_is_well_formed_and_read_back_by_config_of(config: dict[str, Any]) -> None:
    text = json.dumps(config)
    if ac.complete(text):
        assert ac.well_formed(text) and ac.config_of(text) == config
    if not ac.well_formed(text):
        assert ac.config_of(text) is None and not ac.complete(text)


def test_pending_names_the_newest_proposal_of_each_piece_not_yet_installed_at_its_current_version(db_url: str) -> None:
    async def scenario() -> None:
        async with crowd(db_url) as (_, c):
            shop = services.get(Workshop)
            bench, one = await bench_with_piece(c.alana)
            two = (await shop.apply(c.alana, bench, add(c.alana, body(alias="b")))).piece_id
            assert two is not None
            first = await shop.apply(c.alana, bench, propose(one, 1, False))
            second = await shop.apply(c.alana, bench, propose(one, 1, True, "automation.x"))
            view = await shop.read(c.alana, bench)
            assert set(view.proposals) == {one}
            assert view.proposals[one].seq == second.seq
            assert view.proposals[one].proposed == Proposed(one, 1, True, "automation.x")
            await shop.apply(c.alana, bench, propose(two, 1, False))
            assert set((await shop.read(c.alana, bench)).proposals) == {one, two}
            assert first.seq < second.seq

    run(scenario())


def test_a_proposal_stops_pending_when_installed_when_the_piece_changes_and_when_it_was_refused(db_url: str) -> None:
    async def scenario() -> None:
        async with crowd(db_url) as (_, c):
            shop = services.get(Workshop)
            bench, piece = await bench_with_piece(c.alana)
            assert (await shop.read(c.alana, bench)).proposals == {}
            await shop.apply(c.alana, bench, propose(piece, 9))
            assert (await shop.read(c.alana, bench)).proposals == {}
            await installed(c.alana, bench, piece)
            assert (await shop.read(c.alana, bench)).proposals == {}
            await shop.apply(c.alana, bench, propose(piece, 1))
            assert set((await shop.read(c.alana, bench)).proposals) == {piece}
            await shop.apply(c.alana, bench, edit(c.alana, piece, 1, alias="v2"))
            assert (await shop.read(c.alana, bench)).proposals == {}
            await shop.apply(c.alana, bench, propose(piece, 2))
            view = await shop.read(c.alana, bench)
            assert view.proposals[piece].proposed.version == 2

    run(scenario())


def test_pending_of_pieces_and_effects_is_read_without_the_database(db_url: str) -> None:
    async def scenario() -> None:
        async with crowd(db_url) as (_, c):
            shop = services.get(Workshop)
            bench, piece = await bench_with_piece(c.alana)
            view = await shop.read(c.alana, bench)
            proposed = Proposed(piece, 1, True, None)
            got = pending(view.pieces, {2: proposed})
            assert got[piece].seq == 2 and got[piece].proposed == proposed
            assert pending(view.pieces, {2: proposed, 3: Installed(piece, 1, "x", True, None, 2)}) == {}
            assert pending(view.pieces, {2: Proposed(piece, 7, True, None)}) == {}
            assert pending((), {2: proposed}) == {}
            assert pending(view.pieces, {}) == {}
            newer = Proposed(piece, 1, False, None)
            assert pending(view.pieces, {2: proposed, 5: newer})[piece].seq == 5

    run(scenario())


def test_modes_are_the_four_home_assistant_has_and_max_is_a_positive_whole_number() -> None:
    for mode in ("single", "restart", "queued", "parallel"):
        assert ac.well_formed(body(mode=mode)), mode
    for bad in (dict(mode="bogus"), dict(max=0), dict(max=1.5), dict(max="3"), dict(max=True)):
        assert not ac.well_formed(body(**bad)), bad
    assert ac.well_formed(body(max=1, mode="queued"))
