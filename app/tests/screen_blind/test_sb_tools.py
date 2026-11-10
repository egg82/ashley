"""Contract 12 and 20: what she may do to a screen with her tools, from which turns, and what each refusal is."""

import json
from itertools import count
from typing import Any

import pytest
from ashley import services
from ashley.channels.model import Inbound
from ashley.channels.screen_tools import ScreenTools
from ashley.channels.turn_tools import for_turn, sources
from ashley.inference.model import ToolCall, ToolResult
from ashley.workshop.json_shape import list_of, object_of
from ashley.workshop.model import HER
from ashley.workshop.screen_controls import decode
from ashley.workshop.workshop import ScreenView, Workshop
from contract.conversations_support import scalar
from sb_rig import HALL, PORCH, Rig
from sb_support import CONTROLS, CONVERSATION, benches_of, log_of

_ids = count(1)
TOOLS = ("screen_read", "screen_add", "screen_move", "screen_remove", "screen_buttons", "screen_undo")
GOOD = {"label": "Hall light", "action": "light.turn_on", "entity_id": "light.zq_hall"}


def use(app: Rig, tools: ScreenTools, name: str, **arguments: object) -> ToolResult:
    return app.on_loop(lambda: tools.call(ToolCall(f"c{next(_ids)}", name, arguments)))


def alana(app: Rig, device: int | None = None) -> ScreenTools:
    return ScreenTools(app.people.home, app.people.alana, device)


def on_tablet(app: Rig, device: int) -> ScreenTools:
    return ScreenTools(app.people.home, None, device)


def view(app: Rig, device: int) -> ScreenView:
    return app.on_loop(lambda: services.get(Workshop).screen(app.people.home, device))


def refused(got: ToolResult, why: str) -> None:
    assert got.is_error and why in got.content, got.content


def objects(node: object) -> list[dict[str, Any]]:
    mine, items = object_of(node), list_of(node)
    if mine is not None:
        return [dict(mine), *[o for v in mine.values() for o in objects(v)]]
    return [] if items is None else [o for v in items for o in objects(v)]


def pieces_in(got: ToolResult) -> list[dict[str, Any]]:
    return [o for o in objects(json.loads(got.content)) if {"id", "kind", "order", "size"} <= set(o)]


def inbound(person: int | None, device_id: int | None, household: int) -> Inbound:
    return Inbound(household_id=household, thread="t", text="hi", kind="chat", medium="text", audience="owner",
                   speaker_id=person, shared=False, place=None, channel="web", device_id=device_id)


def names_of(app: Rig, turn: Inbound) -> list[str]:
    return [s.name for s in app.on_loop(for_turn(turn).catalogue).specs]


def test_k12_an_entity_the_house_lacks_or_one_outside_the_actions_domain_is_unknown_entity_and_nothing_is_logged(app: Rig) -> None:
    device, _ = app.tablet()
    for bad in ({**GOOD, "entity_id": "light.zq_nowhere"}, {**GOOD, "entity_id": "scene.zq_night"},
                {**GOOD, "action": "scene.turn_on"}, {**GOOD, "entity_id": "lock.zq_front"}):
        refused(use(app, alana(app), "screen_buttons", device_id=device, piece_id=CONTROLS, base_version=1, buttons=[bad]),
                "unknown_entity")
        assert benches_of(app.url, device) == []
    assert app.put_controls(device, 0, HALL).status_code == 200
    seen = log_of(app.url, device)
    refused(use(app, alana(app), "screen_buttons", device_id=device, piece_id=CONTROLS, base_version=2,
                buttons=[{**GOOD, "entity_id": "light.zq_nowhere"}]), "unknown_entity")
    assert log_of(app.url, device) == seen


def test_k12_with_no_known_speaker_screen_buttons_is_needs_speaker_and_changes_nothing(app: Rig) -> None:
    device, _ = app.tablet()
    refused(use(app, on_tablet(app, device), "screen_buttons", piece_id=CONTROLS, base_version=1, buttons=[GOOD]),
            "needs_speaker")
    assert benches_of(app.url, device) == []


def test_k12_good_buttons_become_an_edit_of_hers_and_the_pieces_body(app: Rig) -> None:
    device, _ = app.tablet()
    got = use(app, alana(app), "screen_buttons", device_id=device, piece_id=CONTROLS, base_version=1,
              buttons=[GOOD, {"label": "Porch off", "action": "light.turn_off", "entity_id": "light.zq_porch"}])
    assert not got.is_error, got.content
    shown = view(app, device)
    controls = next(p for p in shown.pieces if p.id == CONTROLS)
    assert [(c.label, c.entity_id) for c in decode(controls.text.body)] == [("Hall light", "light.zq_hall"),
                                                                              ("Porch off", "light.zq_porch")]
    assert controls.version == 2 and len({c.id for c in decode(controls.text.body)}) == 2
    assert log_of(app.url, device)[-1][1].by == HER


def test_k12_a_stale_base_version_a_long_list_and_a_bad_label_are_refused_with_their_reason(app: Rig) -> None:
    device, _ = app.tablet()
    assert app.put_controls(device, 0, HALL).status_code == 200
    seen = log_of(app.url, device)
    many = [{**GOOD, "label": f"L{i}", "entity_id": "light.zq_hall"} for i in range(13)]
    cases = ((2, many, "too_many"), (2, [{**GOOD, "label": ""}], "bad_label"), (1, [GOOD], "stale_base"))
    for base, buttons, why in cases:
        refused(use(app, alana(app), "screen_buttons", device_id=device, piece_id=CONTROLS, base_version=base,
                    buttons=buttons), why)
        now = log_of(app.url, device)
        if why == "stale_base":
            assert now[:len(seen)] == seen and [o for _, _, o in now[len(seen):]] == ["stale_base"]
        else:
            assert now == seen


def test_k20_screen_tools_are_offered_with_a_known_speaker_or_on_a_screens_own_thread_and_not_otherwise(app: Rig) -> None:
    device, _ = app.tablet()
    home = app.people.home
    for turn in (inbound(app.people.alana, None, home), inbound(None, device, home), inbound(app.people.sam, device, home)):
        assert "screen" in sources(turn) and set(TOOLS) <= set(names_of(app, turn)), turn
    bare = inbound(None, None, home)
    assert "screen" not in sources(bare) and not set(TOOLS) & set(names_of(app, bare))


def test_k20_with_a_known_speaker_screen_read_lists_the_screens_when_there_are_several(app: Rig) -> None:
    one, _ = app.tablet()
    two, _ = app.tablet()
    sat = int(scalar(app.url, "INSERT INTO devices (household_id, name, place, audience, medium, kind, token_sha256, "
                     "esphome_host) VALUES (%s, 'sat', 'den', 'present', 'text', 'chat', sha256(gen_random_uuid()::text::bytea), 'h') "
                     "RETURNING id", (app.people.home,)))
    gone = int(scalar(app.url, "INSERT INTO devices (household_id, name, place, audience, medium, kind, token_sha256, "
                      "revoked_at) VALUES (%s, 'old', 'attic', 'present', 'text', 'chat', sha256(gen_random_uuid()::text::bytea), now()) "
                      "RETURNING id", (app.people.home,)))
    got = use(app, alana(app), "screen_read")
    assert not got.is_error and not pieces_in(got)
    listed = {o["device_id"] for o in objects(json.loads(got.content)) if {"device_id", "name", "place"} <= set(o)}
    assert listed == {one, two}
    for outside in (sat, gone, app.tablet(app.people.other)[0], 9_999_999):
        refused(use(app, alana(app), "screen_read", device_id=outside), "no_such_screen")
        refused(use(app, alana(app), "screen_add", device_id=outside, kind="clock", size="small"), "no_such_screen")
        refused(use(app, alana(app), "screen_move", device_id=outside, piece_id=1, order=0, size="small"), "no_such_screen")
        refused(use(app, alana(app), "screen_remove", device_id=outside, piece_id=1), "no_such_screen")
        refused(use(app, alana(app), "screen_undo", device_id=outside), "no_such_screen")
        assert benches_of(app.url, outside) == []


def test_k20_the_only_screen_in_scope_is_read_without_naming_it(app: Rig) -> None:
    device, _ = app.tablet()
    got = use(app, alana(app), "screen_read")
    assert [(p["id"], p["kind"], p["order"], p["size"]) for p in pieces_in(got)] == [
        (1, "clock", 0, "small"), (2, "home", 1, "small"), (3, "controls", 2, "medium"), (4, "conversation", 3, "full")]
    assert {p["last_changed_by"] for p in pieces_in(got)} == {"ashley"}
    assert benches_of(app.url, device) == []


def test_k20_on_a_screens_own_thread_with_no_speaker_only_that_screen_is_in_scope(app: Rig) -> None:
    mine, _ = app.tablet()
    other, _ = app.tablet()
    tools = on_tablet(app, mine)
    assert [p["id"] for p in pieces_in(use(app, tools, "screen_read"))] == [1, 2, 3, 4]
    refused(use(app, tools, "screen_read", device_id=other), "no_such_screen")
    refused(use(app, tools, "screen_remove", device_id=other, piece_id=1), "no_such_screen")
    assert not use(app, tools, "screen_remove", piece_id=1).is_error
    assert benches_of(app.url, other) == []


def test_k20_screen_read_shows_who_last_changed_a_piece_each_controls_piece_and_the_undo_to_come(app: Rig) -> None:
    device, _ = app.tablet()
    app.put_controls(device, 0, HALL, PORCH)
    got = use(app, alana(app), "screen_read")
    by = {p["kind"]: p for p in pieces_in(got)}
    assert by["controls"]["last_changed_by"] == "person" and by["clock"]["last_changed_by"] == "ashley"
    assert by["controls"]["version"] == view(app, device).pieces[2].version
    assert [b["id"] for b in by["controls"]["buttons"]] == ["hall-light", "porch-off"]
    assert [o["undo_next"] for o in objects(json.loads(got.content)) if "undo_next" in o] == [view(app, device).undo_next]


@pytest.mark.parametrize("kind", ["clock", "home", "controls"])
def test_k20_screen_add_puts_the_kind_last_with_its_label_as_title_and_an_empty_body(app: Rig, kind: str) -> None:
    device, _ = app.tablet()
    piece = {"clock": 1, "home": 2, "controls": 3}[kind]
    assert not use(app, alana(app), "screen_remove", device_id=device, piece_id=piece).is_error
    assert not use(app, alana(app), "screen_add", device_id=device, kind=kind, size="large").is_error
    last = view(app, device).pieces[-1]
    label = {"clock": "Clock", "home": "Who's home", "controls": "Controls"}[kind]
    assert (last.kind, last.place.size, last.place.order, last.text.title) == (kind, "large", 3, label)
    assert last.text.body == ("[]" if kind == "controls" else "") and log_of(app.url, device)[-1][1].by == HER


def test_k20_screen_add_of_a_held_kind_is_already_shown_and_the_conversation_is_required(app: Rig) -> None:
    device, _ = app.tablet()
    refused(use(app, alana(app), "screen_add", device_id=device, kind="clock", size="small"), "already_shown")
    refused(use(app, alana(app), "screen_remove", device_id=device, piece_id=CONVERSATION), "required")
    refused(use(app, alana(app), "screen_add", device_id=device, kind="note", size="small"), "unknown_kind")
    assert len(view(app, device).pieces) == 4


def test_k20_screen_move_and_undo_work_as_hers_and_undo_with_nothing_to_undo_changes_nothing(app: Rig) -> None:
    device, _ = app.tablet()
    refused(use(app, alana(app), "screen_undo", device_id=device), "nothing_to_undo")
    assert benches_of(app.url, device) == []
    assert not use(app, alana(app), "screen_move", device_id=device, piece_id=CONVERSATION, order=0, size="small").is_error
    assert view(app, device).pieces[0].id == CONVERSATION
    assert not use(app, alana(app), "screen_undo", device_id=device).is_error
    assert [p.id for p in view(app, device).pieces] == [1, 2, 3, 4]
    refused(use(app, alana(app), "screen_move", device_id=device, piece_id=1, order=9, size="small"), "bad_place")


def test_k20_an_argument_the_tool_does_not_define_or_a_missing_one_is_bad_arguments_and_changes_nothing(app: Rig) -> None:
    device, _ = app.tablet()
    refused(use(app, alana(app), "screen_add", device_id=device, kind="clock", size="small", colour="red"), "bad_arguments")
    refused(use(app, alana(app), "screen_add", device_id=device, size="small"), "bad_arguments")
    refused(use(app, alana(app), "screen_move", device_id=device, piece_id="x", order=0, size="small"), "bad_arguments")
    assert benches_of(app.url, device) == []
