"""Opening a bench from the Workshop list with an ask: the ask is the person's first message in the bench's talk, whole,
and she answers it in a turn that leads; a name alone opens a bench and starts no turn; until she names the bench its
title is cut from the ask."""

import time
from collections.abc import Callable

import pytest
from ashley.api.bench_opening import inbound_for
from ashley.api.models import ChatConversation
from ashley.api.workshop_models import BenchRequest, BenchSummary
from ashley.inference.reply import Reply
from ashley.tools import bench_tools
from ashley.tools.bench_lead import lead
from ashley.workshop.provisional import provisional_title
from pydantic import ValidationError
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from respond_support import ALANA, Fakes, wired as wired
from test_workshop_routes import As, signed_in as signed_in

ASK = "Are you able to read this book? " + "Ortega, J., Field notes on shared kitchens. " * 90
REPLY = Reply(spoken="I can.", text="I can.")


def until(done: Callable[[], bool], seconds: float = 5.0) -> None:
    end = time.monotonic() + seconds
    while not done() and time.monotonic() < end:
        time.sleep(0.01)


def open_with(alana: As, **body: object) -> BenchSummary:
    response = alana(ALANA).post("/api/benches", json=body)
    assert response.status_code == 200
    return BenchSummary.model_validate(response.json())


def test_an_ask_is_the_first_message_in_the_benchs_talk_in_full_and_she_answers_it_leading(
        signed_in: As, wired: Fakes) -> None:
    assert len(ASK) > 3000
    wired.inference.script = [REPLY]
    bench = open_with(signed_in, ask=ASK)
    until(lambda: len(wired.inference.prompts) == 1)
    until(lambda: _talk(signed_in, bench).turns[-1:] != [] and _talk(signed_in, bench).turns[-1].author == "ashley")
    assert len(wired.inference.prompts) == 1
    assert wired.contexts[0].tool_instructions is not None and lead(bench_tools.CONFIG.lead_adds) in wired.contexts[0].tool_instructions
    assert [t.text for t in _talk(signed_in, bench).turns] == [ASK, "I can."]
    assert _talk(signed_in, bench).thread == bench.thread


def test_the_ask_is_cut_to_a_provisional_title_and_a_name_given_with_it_is_kept(signed_in: As, wired: Fakes) -> None:
    wired.inference.script = [REPLY, REPLY]
    assert open_with(signed_in, ask=ASK).title == provisional_title(ASK, 120)
    assert open_with(signed_in, ask=ASK, title="the book").title == "the book"
    until(lambda: len(wired.inference.prompts) == 2)


def test_a_name_alone_opens_a_bench_and_starts_no_turn(signed_in: As, wired: Fakes) -> None:
    bench = open_with(signed_in, title="desk")
    time.sleep(0.2)
    assert bench.title == "desk" and wired.inference.prompts == []
    assert signed_in(ALANA).get(f"/api/benches/{bench.id}/conversation").json()["turns"] == []


@pytest.mark.parametrize("body", [{}, {"ask": ""}, {"ask": "  "}, {"ask": "x" * 4001}, {"ask": "a\u0000b"},
                                  {"title": ""}])
def test_an_open_needs_a_name_or_an_ask_within_the_talks_limits(signed_in: As, wired: Fakes, body: dict[str, str]) -> None:
    assert signed_in(ALANA).post("/api/benches", json=body).status_code == 422
    assert wired.inference.prompts == []


def test_the_request_model_takes_either_alone() -> None:
    assert BenchRequest.model_validate({"ask": "a"}).title is None
    assert BenchRequest.model_validate({"title": "t"}).ask is None
    with pytest.raises(ValidationError):
        BenchRequest.model_validate({})


def test_the_inbound_is_the_bench_talks_with_the_lead_and_one_source_per_bench() -> None:
    got = inbound_for(ALANA, 4, "hi")
    assert got.lead and got.bench_id == 4 and got.thread == "bench:4" and got.text == "hi"
    assert got.source == "bench-opened:4" and got.speaker_id == ALANA.id and got.on_page and got.later_by == "turn"


def test_a_short_ask_is_its_own_title_and_a_long_one_is_cut_at_a_word_with_an_ellipsis() -> None:
    assert provisional_title("  a   b\nc ", 20) == "a b c"
    cut = provisional_title("word " * 40, 20)
    assert len(cut) <= 20 and cut.endswith("…") and not cut.endswith(" …")
    assert len(provisional_title("x" * 300, 20)) == 20


def _talk(alana: As, bench: BenchSummary) -> ChatConversation:
    return ChatConversation.model_validate(alana(ALANA).get(f"/api/benches/{bench.id}/conversation").json())
