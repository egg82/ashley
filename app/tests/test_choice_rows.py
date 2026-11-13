"""A facts choice row (`ashley.workshop.facts`): what kind of thing something is, with the same sources,
the same confirmed test and the same guard as a number; a citation checked where its context is (a piece in `decide`,
a turn in her bench tools, `bad_citation`); the run's file carrying it; and a check against a reference stand-in made
`unconfirmed` by a guessed form, from the report the CAD image's helper wrote (`tests/cad_models/strap_reference*`)."""

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest
from ashley import services
from ashley.channels.said_links import turns_by_people
from ashley.conversations.conversations import Conversations, ConversationsUnavailable, NullConversations
from ashley.conversations.model import Author, Conversation, Turn
from ashley.inference.model import ToolCall
from ashley.runs.model import Output
from ashley.tools.bench_now import open_rows
from ashley.tools.bench_tools import BenchTools
from ashley.workshop import facts, facts_file, rules as workshop_rules
from ashley.workshop.commands import Add, Command, Edit
from ashley.workshop.decide import Accepted, BenchState, decide
from ashley.workshop.model import HER, By, Bench, Owner, Piece, Place, Text
from ashley.workshop.model_report import report_of
from ashley.workshop.workshop import Applied, BenchView, Workshop
from bench_tools_support import EPOCH, FakeWorkshop

RULES = workshop_rules.load()
ALANA = By(7)
MODELS = Path(__file__).parent / "cad_models"
FORM = {"kind": "choice", "name": "lanyard_form", "label": "The lanyard", "value": "flat woven strap",
        "options": ["flat woven strap", "round cord"], "source": "guessed"}
WIDTH = {"name": "strap_width", "value": 20.0, "unit": "mm", "source": "guessed", "given": "lanyard_form"}
THICK = {"name": "strap_thickness", "value": 1.5, "unit": "mm", "source": "guessed", "given": "lanyard_form"}
PHOTO = Piece(3, "image", Text("photo", ""), 1, Place(0, "medium"), 3)
NOTE = Piece(4, "note", Text("note", ""), 1, Place(1, "medium"), 4)


def body(*items: Mapping[str, object]) -> str:
    return json.dumps({"items": list(items)})


def form(**changes: object) -> dict[str, object]:
    return {k: v for k, v in {**FORM, **changes}.items() if v is not None}


def added(by: By, text: str, pieces: tuple[Piece, ...] = (PHOTO, NOTE), shelf: tuple[Piece, ...] = ()) -> str:
    made = decide(BenchState(pieces, next_seq=10, shelf=shelf), Add(by, "facts", Text("m", text), "medium"), RULES)
    return "accepted" if isinstance(made, Accepted) else made.reason


def edited(by: By, before: str, after: str) -> str:
    piece = Piece(5, "facts", Text("m", before), 1, Place(2, "medium"), 5)
    made = decide(BenchState((PHOTO, NOTE, piece), next_seq=10), Edit(by, 5, 1, Text("m", after)), RULES)
    return "accepted" if isinstance(made, Accepted) else made.reason


@pytest.mark.parametrize("row", [
    FORM, form(options=None), form(ref="the person's photo"), form(source="stated", turn=927),
    form(source="accepted", turn=1), form(source="stated"), form(source="seen", piece=3), form(source="datasheet"),
    form(value="v" * facts.MAX_VALUE, options=None), form(label="l" * facts.MAX_LABEL),
    form(options=["flat woven strap", "b", "c", "d", "e", "f"])])
def test_choice_rows_of_the_shape_are_accepted(row: dict[str, object]) -> None:
    assert added(ALANA, body(row, WIDTH)) == "accepted"


@pytest.mark.parametrize("row", [
    form(kind="number"), form(kind="Choice"), form(label=None), form(label=""), form(label="  "),
    form(label="l" * (facts.MAX_LABEL + 1)), form(value=None), form(value=""), form(value=3),
    form(value="v" * (facts.MAX_VALUE + 1), options=None), form(value="oval cord"), form(options=[]),
    form(options=["flat woven strap"]), form(options=["flat woven strap", "flat woven strap"]),
    form(options=["flat woven strap", "b", "c", "d", "e", "f", "g"]), form(options="flat woven strap"),
    form(options=["flat woven strap", 2]), form(source="measured"), form(source="bound"), form(source="rumour"),
    form(turn=927), form(source="seen", turn=927), form(source="stated", piece=3), form(source="stated", turn=0),
    form(source="stated", turn="927"), form(source="stated", turn=True), form(source="seen", piece=-1),
    form(unit="mm"), form(tolerance=1), form(asked=True), form(name="two words"), form(ref="r" * 201), form(extra=1)])
def test_choice_rows_outside_the_shape_are_refused_bad_facts(row: dict[str, object]) -> None:
    assert added(ALANA, body(row)) == "bad_facts"


def test_a_number_given_a_choice_names_one_in_the_same_piece() -> None:
    assert added(ALANA, body(WIDTH)) == "bad_facts"
    assert added(ALANA, body({**WIDTH, "given": "strap_thickness"}, THICK)) == "bad_facts"
    assert added(ALANA, body({**WIDTH, "given": 3}, FORM)) == "bad_facts"
    assert added(ALANA, body(form(name="strap_width"), WIDTH)) == "bad_facts"


def test_choice_rows_read_back_as_their_fields_and_a_row_without_kind_is_a_number() -> None:
    got = facts.items_of(body(form(source="stated", turn=927, ref="r"), WIDTH))
    assert got == (facts.Choice("lanyard_form", "The lanyard", "flat woven strap", "stated",
                                       ("flat woven strap", "round cord"), 927, None, "r"),
                   facts.Measurement("strap_width", 20.0, "mm", "guessed", None, None, "lanyard_form"))
    assert got is not None and [facts.confirmed(r) for r in got] == [True, False]


@pytest.mark.parametrize("after,outcome", [
    (form(source="stated", turn=927, value="round cord"), "confirmed_measurement"),
    (form(source="stated", turn=927, value="round cord", ref="new note"), "confirmed_measurement"),
    (form(source="stated", turn=930, value="round cord"), "accepted"),
    (form(source="guessed", value="round cord"), "accepted"),
    (form(source="stated", turn=927), "accepted")])
def test_her_edit_of_a_confirmed_choice_value_alone_is_refused(after: dict[str, object], outcome: str) -> None:
    before = body(form(source="stated", turn=927))
    assert edited(HER, before, body(after)) == outcome
    assert edited(ALANA, before, body(after)) == "accepted"


def test_a_guessed_choice_may_change_and_a_number_and_choice_of_one_name_are_not_compared() -> None:
    assert edited(HER, body(FORM), body(form(value="round cord"))) == "accepted"
    measured = {"name": "lanyard_form", "value": 3, "unit": "mm", "source": "measured"}
    assert not facts.rewrites_confirmed(body(measured), body(form(source="stated", turn=1)))


@pytest.mark.parametrize("row,outcome", [
    (form(source="seen", piece=3), "accepted"), (form(source="datasheet", piece=3), "accepted"),
    (form(source="seen"), "bad_citation"), (form(source="datasheet"), "bad_citation"),
    (form(source="seen", piece=4), "bad_citation"), (form(source="seen", piece=99), "bad_citation"),
    (form(source="stated"), "accepted"), (FORM, "accepted")])
def test_her_cited_piece_must_be_a_source_on_the_bench(row: dict[str, object], outcome: str) -> None:
    assert added(HER, body(row)) == outcome
    assert added(ALANA, body(row)) == "accepted"


def test_a_shelved_source_may_be_cited_and_a_kept_row_is_not_judged_again() -> None:
    assert added(HER, body(form(source="seen", piece=3)), pieces=(NOTE,), shelf=(PHOTO,)) == "accepted"
    persons = body(form(source="seen"), {"name": "w", "value": 1, "unit": "mm", "source": "guessed"})
    assert edited(HER, persons, body(form(source="seen"), {"name": "w", "value": 2, "unit": "mm", "source": "guessed"})) == "accepted"
    assert edited(HER, persons, body(form(source="datasheet", value="round cord"))) == "bad_citation"


def test_the_run_file_carries_choice_rows_whole_and_numbers_with_given() -> None:
    first = body(form(source="stated", turn=927, ref="r"), WIDTH)
    text = facts_file.file_of([first, body(form(value="round cord"))])
    assert text is not None
    assert json.loads(text)["items"] == [
        {"kind": "choice", "name": "lanyard_form", "label": "The lanyard", "value": "flat woven strap",
         "source": "stated", "options": ["flat woven strap", "round cord"], "turn": 927, "ref": "r"},
        {"name": "strap_width", "value": 20.0, "unit": "mm", "source": "guessed", "given": "lanyard_form"}]
    assert facts.items_of(text) == facts.items_of(first)


def strap_report(*rows: Mapping[str, object]) -> dict[str, str]:
    """The verdicts of the helper's real report for `strap_reference.py`, against the run's facts `rows`."""
    output = Output("ran", 0, "", "", False, {"out/report.json": (MODELS / "strap_reference_report.json").read_text()}, ())
    inputs = facts_file.file_of([body(*rows)])
    assert inputs is not None
    report = report_of(output, {"facts.json": inputs})
    assert report is not None
    assert [p.form for p in report.parts] == [None, "lanyard_form"]
    return {c.name: c.verdict for c in report.checks}


def test_a_guessed_strap_form_leaves_the_stand_ins_parts_apart_unconfirmed() -> None:
    measured = [{**WIDTH, "source": "measured"}, {**THICK, "source": "measured"}]
    assert strap_report(FORM, *measured)["parts_apart:holder:strap"] == "unconfirmed"
    stated = strap_report(form(source="stated", turn=927), *measured)
    assert stated == {"strap_shown_wide": "pass", "parts_apart:holder:strap": "pass"}
    assert strap_report(form(source="stated", turn=927), WIDTH, THICK)["parts_apart:holder:strap"] == "pass"


def test_a_guessed_choice_is_carried_open_and_a_confirmed_one_is_not() -> None:
    facts_kind = Piece(2, "facts", Text("m", body(FORM, form(name="oven", label="Oven", value="gas",
                                                                             options=None, source="stated"))),
                              1, Place(0, "medium"), 2)
    view = BenchView(Bench(9, 10, 1, "Lanyard", EPOCH, None), (facts_kind,), ())
    assert open_rows(view, RULES) == [
        {"piece": 2, "name": "lanyard_form", "kind": "choice", "label": "The lanyard", "value": "flat woven strap"}]


CONVERSATION = 5
OWNER = Owner(10, 1)


@dataclass
class Deciding(FakeWorkshop):
    """A Workshop whose `apply` is the real `decide` over `pieces`."""

    async def apply(self, owner: Owner, bench_id: int, command: Command) -> Applied:
        made = decide(BenchState(self.pieces, next_seq=10), command, RULES)
        return Applied(made.seq, "accepted", made.seq) if isinstance(made, Accepted) else Applied(made.seq, made.reason, None)


@dataclass
class Talk(NullConversations):
    turns: tuple[Turn, ...] = ()
    down: bool = False

    async def get(self, conversation_id: int) -> Conversation | None:
        if self.down:
            raise ConversationsUnavailable()
        return Conversation(CONVERSATION, 10, "brainstorm", frozenset({1}), EPOCH, EPOCH, "open", self.turns)


def turn(n: int, author: Author) -> Turn:
    return Turn(n, author, 1 if author == "person" else None, "it does not, no. Solid rope", EPOCH,
                conversation_id=CONVERSATION)


@pytest.fixture
def shop() -> Deciding:
    fake = Deciding(pieces=(Piece(5, "facts", Text("m", body(FORM, WIDTH)), 1, Place(0, "medium"), 5),))
    services.register(Workshop, fake)
    services.register(Conversations, Talk((turn(926, "ashley"), turn(927, "person"))))
    return fake


def her_call(name: str, args: Mapping[str, object], conversation: bool = True) -> str:
    tools = BenchTools(OWNER.household_id, OWNER.person_id, 4, turns=turns_by_people(CONVERSATION) if conversation else None)
    asyncio.run(tools.call(ToolCall("r", "bench_read_piece", {"piece_id": 5})))
    result = asyncio.run(tools.call(ToolCall("c", name, dict(args))))
    return "accepted" if not result.is_error else result.content.split(":")[0]


def her_edit(row: dict[str, object], conversation: bool = True) -> str:
    return her_call("bench_edit", {"piece_id": 5, "base_version": 1, "title": "m", "body": body(row, WIDTH)}, conversation)


@pytest.mark.parametrize("row,outcome", [
    (form(source="stated", turn=927), "accepted"), (form(source="accepted", turn=927), "accepted"),
    (form(source="stated", turn=926), "bad_citation"), (form(source="stated", turn=999), "bad_citation"),
    (form(source="stated"), "bad_citation"), (form(source="accepted"), "bad_citation"),
    (form(source="guessed", value="round cord"), "accepted")])
def test_her_cited_turn_must_be_the_persons_on_this_talk(shop: Deciding, row: dict[str, object], outcome: str) -> None:
    assert her_edit(row) == outcome


def test_with_no_talk_no_turn_is_hers_to_cite_and_an_unreadable_talk_is_unavailable(shop: Deciding) -> None:
    assert her_edit(form(source="stated", turn=927), conversation=False) == "bad_citation"
    services.register(Conversations, Talk(down=True))
    assert her_edit(form(source="stated", turn=927)) == "unavailable"
    assert her_edit(form(value="round cord")) == "accepted"


def test_a_replace_and_an_add_are_checked_too_and_a_kept_row_is_not(shop: Deciding) -> None:
    stated = json.dumps(form(source="stated", turn=926))
    added_piece = {"kind": "facts", "title": "m", "body": body(json.loads(stated)), "size": "medium"}
    assert her_call("bench_add", added_piece) == "bad_citation"
    old = json.dumps(FORM)[1:-1]
    assert her_call("bench_replace", {"piece_id": 5, "base_version": 1, "old": old, "new": stated[1:-1]}) == "bad_citation"
    shop.pieces = (Piece(5, "facts", Text("m", body(form(source="stated"), WIDTH)), 1, Place(0, "medium"), 5),)
    assert her_call("bench_replace", {"piece_id": 5, "base_version": 1, "old": '"value": 20.0', "new": '"value": 21.0'}) == "accepted"
