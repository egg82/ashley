"""The kinds of action a person may let her just do (`ashley.trust.kinds`): which kind a call belongs to, what a person's
choice stores and what is in force, and that each `floor` in `kinds.json` is the code's own floor: every tool of an
`asks` kind waits in every turn, every change an `irreversible` kind names is one `irreversible.json` covers, and no kind
left open is one the code already holds."""

from collections.abc import Mapping

import pytest
from ashley.home_assistant import irreversible
from ashley.home_assistant.change import KINDS as HOUSE_KINDS, Change, check, op_of
from ashley.inference.model import ToolSpec
from ashley.tools import mail_change_specs, money_specs, reminder_specs, todo_specs
from ashley.tools.house_change import CHANGE_SPEC
from ashley.tools.money_config import load as money_config
from ashley.trust.kinds import Covered, Kind, Kinds, TrustRefused, Value, load, parse

KINDS = load()


def her_specs() -> Mapping[str, ToolSpec]:
    """The specs of every tool she has that a kind could name: each source's own, as it builds them."""
    found = (CHANGE_SPEC, reminder_specs.remind(()), reminder_specs.change_reminder(), reminder_specs.CANCEL_SPEC,
             *todo_specs.specs(), *mail_change_specs.specs(False), *money_specs.specs(money_config()))
    return {s.name: s for s in found}


def test_a_house_delete_is_a_removal_and_any_other_house_change_is_setup() -> None:
    assert KINDS.of("house_change", {"op": "delete", "kind": "automation"}) == KINDS.kinds[0]
    assert KINDS.of("house_change", {"op": "DELETE"}) == KINDS.kinds[0], "values compare in lower case"
    setup = KINDS.of("house_change", {"op": "write", "kind": "automation"})
    assert setup is not None and setup.kind == "house_setup"
    assert KINDS.of("house_change", {}) == setup, "a call without the argument is not the narrower kind"


def test_each_tool_named_belongs_to_its_kind_and_others_to_none() -> None:
    got = {t: (k.kind if (k := KINDS.of(t, {})) else None)
           for t in ("remind", "change_reminder", "cancel_reminder", "todo_change", "mail_send", "money_note",
                     "house_do", "mail_draft", "remind_on_money")}
    assert got == {"remind": "reminders", "change_reminder": "reminders", "cancel_reminder": "reminders",
                   "todo_change": "lists", "mail_send": "messages", "money_note": "money", "house_do": None,
                   "mail_draft": None, "remind_on_money": None}


def test_unset_is_act_where_she_acts_today_and_offer_where_the_code_locks_it() -> None:
    got = KINDS.effective({})
    assert got == {"house_removals": "offer", "house_setup": "act", "reminders": "act", "lists": "act",
                   "messages": "act", "money": "offer"}


def test_a_stored_act_on_a_locked_kind_is_still_offer() -> None:
    got = KINDS.effective({"money": "act", "house_removals": "act", "lists": "offer"})
    assert (got["money"], got["house_removals"], got["lists"]) == ("offer", "offer", "offer")


def test_a_choice_stores_only_what_differs_from_unset() -> None:
    assert KINDS.checked({"lists": "offer", "reminders": "act", "money": "offer"}) == {"lists": "offer"}
    assert KINDS.checked({}) == {}


@pytest.mark.parametrize(("chosen", "kind", "reason"), [
    ({"money": "act"}, "money", "locked"),
    ({"house_removals": "act"}, "house_removals", "locked"),
    ({"lists": "offer", "purchases": "offer"}, "purchases", "unknown_kind"),
])
def test_a_choice_that_would_loosen_the_floor_or_names_no_kind_is_refused(chosen: Mapping[str, Value], kind: str,
                                                                            reason: str) -> None:
    with pytest.raises(TrustRefused) as e:
        KINDS.checked(chosen)
    assert (e.value.kind, e.value.reason) == (kind, reason)


MALFORMED: list[object] = [
    {}, {"kinds": []}, {"kinds": [{"kind": "a", "label": "A", "calls": []}]},
    {"kinds": [{"kind": "a", "label": "A", "calls": [{"tool": "t"}]}, {"kind": "a", "label": "B", "calls": [{"tool": "u"}]}]},
    {"kinds": [{"kind": "a", "label": "A", "calls": [{"tool": "t"}], "floor": "never"}]},
    {"kinds": [{"kind": "a", "label": "A", "calls": [{"tool": "t", "values": ["x"]}]}]},
    {"kinds": [{"kind": "a", "label": "", "calls": [{"tool": "t"}]}]},
    {"kinds": [{"kind": "a", "label": "A", "calls": [{"tool": "t"}], "extra": 1}]},
]


@pytest.mark.parametrize("raw", MALFORMED)
def test_a_malformed_kinds_file_is_refused(raw: object) -> None:
    with pytest.raises(ValueError):
        parse(raw)


def test_a_well_formed_kinds_file_parses_as_written() -> None:
    got = parse({"kinds": [{"kind": "a", "label": "A", "calls": [{"tool": "t", "argument": "op", "values": ["X"]}],
                            "floor": "asks"}]})
    assert got == Kinds((Kind("a", "A", (Covered("t", "op", ("x",)),), "asks"),))


def test_every_tool_a_kind_names_is_one_she_has() -> None:
    specs = her_specs()
    named = {c.tool for k in KINDS.kinds for c in k.calls}
    assert named and named <= set(specs), sorted(named - set(specs))


def test_an_asks_floor_is_a_kind_whose_every_tool_waits_and_no_open_kind_is_one() -> None:
    specs = her_specs()
    floors = {k.kind: k.floor for k in KINDS.kinds}
    waits = {k.kind for k in KINDS.kinds if all(specs[c.tool].tier == "asks" for c in k.calls)}
    assert waits, "the gate must see a kind the code holds"
    assert waits == {k for k, f in floors.items() if f == "asks"}


def _changes(kind: Kind) -> list[Change]:
    """Every well-formed house change a kind's calls name."""
    out: list[Change] = []
    for c in kind.calls:
        assert c.tool == "house_change" and c.argument == "op" and c.values, f"{kind.kind} names house changes by op"
        for value in c.values:
            op = op_of(value)
            assert op is not None, value
            for k in HOUSE_KINDS:
                change = Change(op, k, "x")
                try:
                    check(change)
                except ValueError:
                    continue
                out.append(change)
    return out


def test_an_irreversible_floor_names_only_changes_irreversible_json_covers() -> None:
    covered = irreversible.load()
    locked = [k for k in KINDS.kinds if k.floor == "irreversible"]
    assert locked, "the gate must see a kind irreversible.json locks"
    for kind in locked:
        changes = _changes(kind)
        assert changes, kind.kind
        assert [c.key() for c in changes if not covered.covers(c.key())] == []
    setup = next(k for k in KINDS.kinds if k.kind == "house_setup")
    assert setup.floor is None and not covered.covers(Change("write", "automation", "x").key()), "control"
