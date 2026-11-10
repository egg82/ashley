"""The three conversation routes (web chat, a bench's talk, the kiosk) serve each run under her answer to the person
turn that asked, and say `unavailable` when runs cannot be read."""

from ashley.api.models import ErrorResponse
from ashley.runs.model import Output, Run
from cr_routes import CONVERSATION_ID, Surface
from cr_routes import surface as surface
from cr_support import run, turns
from respond_support import HOME, wired as wired
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template


def shown(surface: Surface, shape: str, runs: list[Run]) -> dict[int, list[int]]:
    got = surface.conversation(turns(shape), runs)
    return {t.id: [r.id for r in t.runs] for t in got.turns if t.runs}


def test_a_run_shows_under_her_answer_to_the_person_turn_that_asked(surface: Surface) -> None:
    assert shown(surface, "pa", [run(1, 1)]) == {2: [1]}


def test_every_turn_serves_a_runs_list_even_when_empty(surface: Surface) -> None:
    got = surface.read(turns("pa")).json()["turns"]
    assert [t["runs"] for t in got] == [[], []]


def test_a_held_line_carries_none_the_answer_after_it_does(surface: Surface) -> None:
    assert shown(surface, "pha", [run(1, 1), run(2, 1)]) == {3: [1, 2]}


def test_while_the_conversation_ends_on_a_held_line_the_runs_are_not_shown(surface: Surface) -> None:
    assert shown(surface, "ph", [run(1, 1)]) == {}


def test_once_the_answer_is_stored_the_runs_show(surface: Surface) -> None:
    assert shown(surface, "ph", [run(1, 1)]) == {} and shown(surface, "pha", [run(1, 1)]) == {3: [1]}


def test_each_answer_carries_the_runs_of_its_own_message_only(surface: Surface) -> None:
    assert shown(surface, "papa", [run(1, 1), run(2, 3), run(3, 1)]) == {2: [1, 3], 4: [2]}


def test_a_message_not_yet_answered_waits_while_an_earlier_one_shows(surface: Surface) -> None:
    assert shown(surface, "paph", [run(1, 1), run(2, 3)]) == {2: [1]}


def test_the_runs_come_in_the_order_the_service_gave_them(surface: Surface) -> None:
    assert shown(surface, "pa", [run(3, 1), run(4, 1), run(8, 1)]) == {2: [3, 4, 8]}


def test_the_runs_are_read_for_this_households_conversation_in_one_read(surface: Surface) -> None:
    surface.conversation(turns("papa"), [run(1, 1), run(2, 3)])
    assert surface.runs.asked == [(HOME.id, CONVERSATION_ID)]


def test_a_run_is_served_as_the_page_reads_it(surface: Surface) -> None:
    got = surface.conversation(turns("pa"), [run(1, 1), run(2, 1, Output("timed_out", None, "part", "", True))])
    first, second = got.turns[1].runs
    assert (first.result, first.exit_code, first.stdout, first.stderr, first.script) == ("ran", 0, "out", "err", "script 1")
    assert [(f.name, f.text) for f in first.made] == [("r.txt", "é")] and first.skipped == ["b.bin"]
    assert (second.result, second.exit_code, second.stdout, second.cut) == ("timed_out", None, "part", True)


def test_a_run_with_no_recorded_result_is_served_with_a_null_result(surface: Surface) -> None:
    raw = surface.read(turns("pa"), [run(1, 1, output=None)]).json()["turns"][1]["runs"][0]
    assert raw["result"] is None and raw["stdout"] == "" and raw["stderr"] == "" and raw["finished_at"] is None


def test_runs_that_cannot_be_read_are_503_unavailable(surface: Surface) -> None:
    got = surface.read(turns("pa"), [run(1, 1)], down=True)
    assert got.status_code == 503 and ErrorResponse.model_validate(got.json()).code == "unavailable"
