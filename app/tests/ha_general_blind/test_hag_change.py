"""A change as data: its operation key, what `irreversible` covers (Alana's rule: configuration she changes on her own;
deletes, removals, restart and stop, recorder purge and disable, backups and hassio need his OK), `check`, `op_of`,
and `carry_out` over a House; and the turn gate (`senses.proposal_gate.gate`)."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import get_args

import pytest
from ashley.home_assistant import irreversible
from ashley.home_assistant.change import KINDS, OPS, Change, Op, carry_out, check, op_of
from ashley.home_assistant.house import CONFIG_KINDS, RECORD_KINDS, HouseRejected, HouseUnavailable
from ashley.senses.proposal_gate import gate
from contract.conversations_support import run
from hypothesis import given, settings
from hag_world_support import RecordingHouse
from hypothesis import strategies as st

RESTART_STOP_DESTROY = ("homeassistant.restart", "homeassistant.stop", "recorder.purge", "recorder.purge_entities",
                        "recorder.disable", "backup.create", "backup.create_automatic", "hassio.host_reboot",
                        "hassio.addon_stop", "hassio.backup_full")
EVERYDAY = ("light.turn_on", "light.turn_off", "climate.set_temperature", "homeassistant.reload_all",
            "homeassistant.turn_on", "homeassistant.update_entity", "recorder.enable", "todo.add_item", "script.goodnight",
            "automation.trigger", "calendar.get_events", "notify.mobile_app_phone", "switch.toggle")


def change_for(op: Op, kind: str | None = None, action: str | None = None, id: str | None = "x") -> Change:
    if op == "perform":
        return Change("perform", "action", action or "light.turn_on", ids=("light.a",))
    return Change(op, kind or "automation", id)


def test_the_key_of_every_change_is_the_ports_operation_key() -> None:
    for kind in CONFIG_KINDS:
        assert Change("write", kind, "x").key() == f"write:config:{kind}"
        assert Change("delete", kind, "x").key() == f"delete:config:{kind}"
    for kind in ("area", "floor", "label"):
        assert Change("create", kind).key() == f"create:record:{kind}"
    for kind in ("device", "entity", "area", "floor", "label"):
        assert Change("update", kind, "x", {"name": "n"}).key() == f"update:record:{kind}"
        assert Change("delete", kind, "x").key() == f"delete:record:{kind}"
    assert Change("delete", "integration", "x").key() == "remove:integration"
    assert Change("perform", "action", "light.turn_on", ids=("light.a",)).key() == "perform:light.turn_on"


@given(st.sampled_from(EVERYDAY + RESTART_STOP_DESTROY), st.dictionaries(st.text(max_size=6), st.text(max_size=6), max_size=3),
       st.lists(st.sampled_from(("light.a", "switch.b", "climate.c")), max_size=3))
@settings(max_examples=40, deadline=None)
def test_a_performed_actions_key_names_the_action_and_nothing_in_its_data(action: str, data: Mapping[str, str], ids: list[str]) -> None:
    assert Change("perform", "action", action, data, tuple(ids)).key() == f"perform:{action}"


@given(st.dictionaries(st.text(max_size=8), st.text(max_size=8), max_size=4), st.text(min_size=1, max_size=8))
@settings(max_examples=40, deadline=None)
def test_a_key_does_not_depend_on_the_data_or_the_id(data: Mapping[str, str], ident: str) -> None:
    assert Change("delete", "automation", ident, data).key() == Change("delete", "automation", "other").key()
    assert Change("write", "script", ident, data).key() == Change("write", "script", None).key()


def test_the_shipped_rule_covers_what_cannot_be_undone_and_nothing_he_lets_her_do_alone() -> None:
    rule = irreversible.load()
    for kind in CONFIG_KINDS:
        assert rule.covers(Change("delete", kind, "x").key())
        assert not rule.covers(Change("write", kind, "x").key())
    for kind in ("device", "entity", "area", "floor", "label"):
        assert rule.covers(Change("delete", kind, "x").key())
        assert not rule.covers(Change("update", kind, "x", {"name": "n"}).key())
    for kind in ("area", "floor", "label"):
        assert not rule.covers(Change("create", kind).key())
    assert rule.covers(Change("delete", "integration", "x").key())
    for action in RESTART_STOP_DESTROY:
        assert rule.covers(Change("perform", "action", action).key()), action
    for action in EVERYDAY:
        assert not rule.covers(Change("perform", "action", action).key()), action


OPERATIONS = st.one_of(
    st.tuples(st.sampled_from(("write", "create", "update")), st.sampled_from(KINDS)).map(lambda t: f"{t[0]}:{t[1]}"),
    st.sampled_from(EVERYDAY).map(lambda a: f"perform:{a}"),
    st.sampled_from(RESTART_STOP_DESTROY).map(lambda a: f"perform:{a}"),
    st.tuples(st.sampled_from(("delete", "remove")), st.text(alphabet="abcdefghijklmnopqrstuvwxyz:._", max_size=12)).map(
        lambda t: f"{t[0]}:{t[1]}"),
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz:._*?", max_size=20),
)


def alana(operation: str) -> bool:
    """Alana's rule over an operation key: a delete or a removal of anything, and the named actions."""
    verb, colon, rest = operation.partition(":")
    if not colon:
        return False
    if verb in ("delete", "remove"):
        return True
    return verb == "perform" and (rest in ("homeassistant.restart", "homeassistant.stop", "recorder.purge",
                                           "recorder.purge_entities", "recorder.disable")
                                  or rest.startswith(("backup.", "hassio.")))


@given(OPERATIONS)
@settings(max_examples=300, deadline=None)
def test_covers_follows_alanas_rule_over_any_operation_key(operation: str) -> None:
    assert irreversible.load().covers(operation) is alana(operation), operation


@given(st.sampled_from(("homeassistant.restart", "homeassistant.stop", "recorder.purge", "recorder.disable")),
       st.sampled_from(("x", "_all", "2", "ed")))
@settings(max_examples=30, deadline=None)
def test_an_action_that_only_resembles_a_named_one_is_not_covered(action: str, tail: str) -> None:
    assert not irreversible.load().covers(f"perform:{action}{tail}")


@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=12))
@settings(max_examples=40, deadline=None)
def test_any_backup_or_hassio_action_is_covered_and_a_lookalike_domain_is_not(name: str) -> None:
    rule = irreversible.load()
    assert rule.covers(f"perform:backup.{name}") and rule.covers(f"perform:hassio.{name}")
    assert not rule.covers(f"perform:backups.{name}") and not rule.covers(f"perform:xbackup.{name}")
    assert not rule.covers(f"write:backup.{name}")


def test_a_rule_is_judged_on_the_key_and_nowhere_else() -> None:
    rule = irreversible.load()
    assert not rule.covers(Change("write", "automation", "delete", {"alias": "delete everything", "actions": [
        {"action": "homeassistant.restart"}]}).key())
    assert not rule.covers(Change("update", "entity", "light.restart", {"name": "Stop"}).key())


def test_parse_takes_a_non_empty_list_of_non_empty_strings_under_operations_and_nothing_else() -> None:
    got = irreversible.parse({"operations": ["delete:*", "perform:x.y"]})
    assert got.operations == ("delete:*", "perform:x.y")
    assert got.covers("delete:record:area") and got.covers("perform:x.y") and not got.covers("perform:x.z")
    bads: list[object] = [None, [], "operations", {}, {"operations": []}, {"operations": ["a", ""]}, {"operations": "delete:*"},
                {"operations": [1]}, {"operations": ["a"], "other": 1}, {"operation": ["a"]}, {"operations": None}, 7,
                {"operations": ["a", None]}]
    for bad in bads:
        with pytest.raises(ValueError):
            irreversible.parse(bad)


@given(st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=5), st.lists(st.integers(), max_size=3),
                 st.dictionaries(st.text(max_size=4), st.integers(), max_size=3)))
@settings(max_examples=60, deadline=None)
def test_parse_refuses_anything_not_shaped_so(data: object) -> None:
    with pytest.raises(ValueError):
        irreversible.parse(data)


@given(st.lists(st.text(min_size=1, max_size=10, alphabet="abcdefghij:._"), min_size=1, max_size=5))
@settings(max_examples=40, deadline=None)
def test_parse_keeps_the_patterns_in_order_and_covers_each_literal_one(patterns: list[str]) -> None:
    got = irreversible.parse({"operations": patterns})
    assert list(got.operations) == patterns
    for p in patterns:
        assert got.covers(p)


def test_load_is_the_shipped_file() -> None:
    assert irreversible.load() == irreversible.parse(json.loads(irreversible.FILE.read_text()))
    assert irreversible.load().operations


def test_op_of_names_the_five_ops_and_nothing_else() -> None:
    assert OPS == get_args(Op) and set(OPS) == {"write", "create", "update", "delete", "perform"}
    for op in OPS:
        assert op_of(op) == op
    for bad in ("", "Write", "remove", "run", "delete ", "perform:x"):
        assert op_of(bad) is None


def test_kinds_are_the_config_and_record_kinds_and_action() -> None:
    assert set(KINDS) == set(CONFIG_KINDS) | set(RECORD_KINDS) | {"action"}


def test_a_well_formed_change_passes_check() -> None:
    for change in (Change("write", "automation", "a", {"alias": "x"}), Change("write", "helper", None, {"type": "counter"}),
                   Change("create", "area", None, {"name": "n"}), Change("update", "entity", "light.a", {"name": "n"}),
                   Change("delete", "automation", "a"), Change("delete", "integration", "e"), Change("delete", "area", "a"),
                   Change("perform", "action", "homeassistant.restart")):
        check(change)


def test_a_kind_that_does_not_suit_its_op_fails_check_naming_no_data() -> None:
    marker = {"alias": "marker-5531"}
    for change in (Change("write", "area", "a", marker), Change("write", "action", "a", marker),
                   Change("create", "automation", None, marker), Change("create", "device", None, marker),
                   Change("perform", "automation", "light.turn_on", marker), Change("perform", "area", "x", marker),
                   Change("delete", "action", "x", marker), Change("update", "automation", "a", marker)):
        with pytest.raises(ValueError) as raised:
            check(change)
        assert "marker-5531" not in str(raised.value), change


def test_carry_out_dispatches_each_op_to_the_port_and_names_what_it_did_not_what_it_carried() -> None:
    marker: dict[str, object] = {"alias": "marker-7710", "triggers": [], "actions": []}

    async def go() -> None:
        house = RecordingHouse()
        said = await carry_out(house, Change("write", "automation", "porch", marker))
        assert house.calls == [("write_config", ("automation", "porch", marker))]
        assert "marker-7710" not in said and said
        house.calls.clear()
        await carry_out(house, Change("write", "helper", None, {"type": "counter", "name": "Laps"}))
        assert house.calls == [("write_config", ("helper", None, {"type": "counter", "name": "Laps"}))]
        house.calls.clear()
        said = await carry_out(house, Change("create", "area", None, {"name": "Sauna-marker-7710"}))
        assert house.calls == [("create_record", ("area", {"name": "Sauna-marker-7710"}))]
        assert "marker-7710" not in said
        house.calls.clear()
        assert await carry_out(house, Change("delete", "area", "kitchen", {"note": "marker-3301"})) == "kitchen"
        assert await carry_out(house, Change("delete", "automation", "porch", {"note": "marker-3301"})) == "porch"
        house.calls.clear()
        await carry_out(house, Change("update", "entity", "light.a", {"name": "n"}))
        assert house.calls == [("update_record", ("entity", "light.a", {"name": "n"}))]
        house.calls.clear()
        await carry_out(house, Change("delete", "automation", "porch"))
        await carry_out(house, Change("delete", "area", "kitchen"))
        await carry_out(house, Change("delete", "integration", "entry_x"))
        assert house.calls == [("delete_config", ("automation", "porch")), ("delete_record", ("area", "kitchen")),
                               ("delete_record", ("integration", "entry_x"))]
        house.calls.clear()
        await carry_out(house, Change("perform", "action", "light.turn_on", {"brightness_pct": 5}, ("light.a", "light.b")))
        assert house.calls == [("perform", ("light.turn_on", ("light.a", "light.b"), {"brightness_pct": 5}))]
    run(go())


def test_carry_out_does_not_judge_what_needs_a_persons_ok_the_proposal_does() -> None:
    async def go() -> None:
        house = RecordingHouse()
        await carry_out(house, Change("perform", "action", "homeassistant.restart"))
        assert house.calls == [("perform", ("homeassistant.restart", (), {}))]
    run(go())


def test_deleting_a_config_that_is_not_there_is_rejected_as_having_nothing_to_change() -> None:
    async def go() -> None:
        with pytest.raises(HouseRejected):
            await carry_out(RecordingHouse(there=False), Change("delete", "automation", "gone"))
    run(go())


def test_the_houses_refusal_and_absence_pass_through_carry_out_unchanged() -> None:
    async def go() -> None:
        with pytest.raises(HouseRejected):
            await carry_out(RecordingHouse(refuse=True), Change("write", "script", "s", {"alias": "x"}))
        with pytest.raises(HouseUnavailable):
            await carry_out(RecordingHouse(down=True), Change("delete", "area", "a"))
        with pytest.raises(HouseUnavailable):
            await carry_out(RecordingHouse(down=True), Change("perform", "action", "light.turn_on", ids=("light.a",)))
    run(go())


NOW = datetime(2026, 11, 3, 15, tzinfo=UTC)


def test_a_proposal_is_taken_from_a_later_turn_within_its_time_only() -> None:
    soon, late = NOW + timedelta(hours=1), NOW + timedelta(hours=3)
    assert gate(10, NOW, 11, soon, 7200) is None
    assert gate(10, NOW, 10, soon, 7200) == "same_turn"
    assert gate(10, NOW, 9, soon, 7200) == "same_turn"
    assert gate(10, NOW, 11, late, 7200) == "expired"


@given(st.integers(0, 10**6), st.integers(1, 10**6), st.integers(0, 10**5), st.integers(1, 10**5))
@settings(max_examples=100, deadline=None)
def test_a_later_turn_inside_the_limit_is_always_allowed(proposed: int, gap: int, elapsed: int, extra: int) -> None:
    ttl = elapsed + extra
    assert gate(proposed, NOW, proposed + gap, NOW + timedelta(seconds=elapsed), ttl) is None


@given(st.integers(0, 10**6), st.integers(0, 10**6), st.integers(0, 10**5), st.integers(1, 10**5))
@settings(max_examples=100, deadline=None)
def test_a_turn_that_is_not_later_is_the_same_turn_however_soon_or_late(proposed: int, back: int, elapsed: int, ttl: int) -> None:
    got = gate(proposed, NOW, max(proposed - back, 0), NOW + timedelta(seconds=min(elapsed, ttl - 1)), ttl)
    assert got == "same_turn"


@given(st.integers(0, 10**6), st.integers(1, 10**6), st.integers(1, 10**5), st.integers(1, 10**5))
@settings(max_examples=100, deadline=None)
def test_a_later_turn_after_the_limit_is_expired(proposed: int, gap: int, ttl: int, over: int) -> None:
    assert gate(proposed, NOW, proposed + gap, NOW + timedelta(seconds=ttl + over), ttl) == "expired"


@given(st.integers(0, 10**6), st.integers(0, 10**6), st.integers(0, 10**5), st.integers(1, 10**5))
@settings(max_examples=100, deadline=None)
def test_a_turn_not_later_is_never_allowed_even_after_the_limit(proposed: int, turn: int, elapsed: int, ttl: int) -> None:
    if turn > proposed:
        return
    assert gate(proposed, NOW, turn, NOW + timedelta(seconds=elapsed), ttl) in ("same_turn", "expired")


def test_a_change_that_names_nothing_to_change_or_no_action_domain_is_not_well_formed() -> None:
    for change in (Change("update", "entity", None, {"name": "n"}), Change("delete", "area", None),
                   Change("delete", "automation", ""), Change("perform", "action", None),
                   Change("perform", "action", "nodomain")):
        with pytest.raises(ValueError):
            check(change)
