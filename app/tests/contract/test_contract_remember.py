"""Remembering one line (`POST /api/memory/remembered`), from the contract alone: who may ask, which turns they may
name, what the writer is shown, where the conversation's watermark ends up, what comes back and what is logged. A real
app and database; the writer is scripted behind the locator."""

from collections.abc import Generator

import pytest
from ashley import logs
from ashley.api.models import ErrorResponse, MemoryFact, MemoryFactsResponse, RememberResponse
from ashley.inference.inference import InferenceRefused, InferenceUnavailable
from ashley.memory.memory import FactWriter, Memory
from ashley.memory.model import Invalidate, Noop, Update
from ashley.main import create_app
from ashley.services import register, unregister
from ashley.settings import Settings
from fastapi.testclient import TestClient

from conversations_support import db_url as db_url, events, migrated_template as migrated_template, scalar
from memory_support import conversation, say
from remember_contract_support import PUBLIC, URL, Home, Scripted, app_client, build_home, fact, remember


@pytest.fixture
def writer() -> Scripted:
    return Scripted()


@pytest.fixture
def home(db_url: str, writer: Scripted) -> Home:
    return build_home(db_url, writer)


@pytest.fixture
def client(home: Home) -> Generator[TestClient]:
    yield from app_client(home)


def learned(client: TestClient, conversation_id: int, turn_id: int) -> RememberResponse:
    got = remember(client, conversation_id, turn_id)
    assert got.status_code == 200, got.text
    return RememberResponse.model_validate(got.json())


def listed(client: TestClient) -> dict[int, MemoryFact]:
    return {f.id: f for f in MemoryFactsResponse.model_validate(client.get("/api/memory/facts").json()).items}


def test_a_line_past_the_watermark_is_decided_with_the_lines_before_it_and_moves_the_watermark(
        client: TestClient, home: Home, writer: Scripted) -> None:
    writer.will((fact("Alana likes tea"),))
    assert home.watermark() is None
    got = learned(client, home.talk, home.turns[2])
    assert len(writer.calls) == 1
    shown = writer.calls[0][0]
    assert (shown.id, shown.household_id) == (home.talk, home.id)
    assert writer.seen_turns() == home.turns[:3]
    assert home.watermark() == home.turns[2]
    assert [f.text for f in got.facts] == ["Alana likes tea"]
    assert (got.unseen, got.ended) == (0, 0)
    assert listed(client)[got.facts[0].id] == got.facts[0]
    assert scalar(home.url, "SELECT source_conversation_id FROM facts WHERE id = %s", (got.facts[0].id,)) == home.talk


def test_a_later_line_is_decided_over_only_the_turns_not_yet_written(client: TestClient, home: Home,
                                                                    writer: Scripted) -> None:
    learned(client, home.talk, home.turns[1])
    learned(client, home.talk, home.turns[4])
    assert writer.seen_turns() == home.turns[2:5]
    assert home.watermark() == home.turns[4]


def test_the_next_line_moves_the_watermark_on_and_an_earlier_one_never_moves_it_back(
        client: TestClient, home: Home, writer: Scripted) -> None:
    learned(client, home.talk, home.turns[3])
    assert home.watermark() == home.turns[3]
    learned(client, home.talk, home.turns[4])
    assert home.watermark() == home.turns[4]
    learned(client, home.talk, home.turns[1])
    assert home.watermark() == home.turns[4]
    learned(client, home.talk, home.turns[4])
    assert home.watermark() == home.turns[4]


def test_a_line_already_written_is_decided_again_with_the_turn_before_it(
        client: TestClient, home: Home, writer: Scripted) -> None:
    learned(client, home.talk, home.turns[4])
    writer.will((fact("Alana is learning piano"),))
    got = learned(client, home.talk, home.turns[2])
    shown = writer.seen_turns()
    assert shown[-1] == home.turns[2] and home.turns[1] in shown
    assert not set(shown) & set(home.turns[3:])
    assert [f.text for f in got.facts] == ["Alana is learning piano"]
    assert home.watermark() == home.turns[4]


def test_either_authors_line_may_be_named(client: TestClient, home: Home, writer: Scripted) -> None:
    learned(client, home.talk, home.turns[1])
    assert writer.seen_turns() == home.turns[:2]


def test_the_writer_is_shown_the_current_facts_most_like_the_line(client: TestClient, home: Home,
                                                                  writer: Scripted) -> None:
    writer.will((fact("Alana likes tea"),))
    first = learned(client, home.talk, home.turns[0]).facts[0].id
    other = say(home.url, conversation(home.url, home.id), "I really like tea too", speaker=home.alana)
    scalar(home.url, "INSERT INTO conversation_participants SELECT conversation_id, household_id, %s "
                     "FROM turns WHERE id = %s RETURNING person_id", (home.alana, other[0]))
    learned(client, int(scalar(home.url, "SELECT conversation_id FROM turns WHERE id = %s", (other[0],))), other[0])
    assert first in writer.calls[-1][1]


def test_what_the_reader_may_not_see_is_stored_and_counted_but_not_returned(
        client: TestClient, home: Home, writer: Scripted) -> None:
    writer.will((fact("Mochi is fed at six"),
                 fact("Ella plans a party", home.ella, home.ella, "private"),
                 fact("Alana is learning piano", home.alana, home.ella, "discreet"),
                 fact("Ella's gift for Alana", home.alana, home.ella, "private")))
    got = learned(client, home.talk, home.turns[4])
    assert [f.text for f in got.facts] == ["Mochi is fed at six", "Alana is learning piano"]
    assert got.unseen == 2
    assert home.fact_count() == 4
    home.sign_in(home.ella)
    assert len(listed(client)) == 4


def test_an_update_returns_the_fact_with_what_it_replaced_and_an_invalidate_is_counted(
        client: TestClient, home: Home, writer: Scripted) -> None:
    writer.will((fact("Alana likes tea", home.alana, home.alana), fact("Alana owns a kiln", home.alana, home.alana)))
    tea, kiln = (f.id for f in learned(client, home.talk, home.turns[0]).facts)
    new = fact("Alana likes green tea", home.alana, home.alana).fact
    writer.will((Update(tea, new), Invalidate(kiln)))
    got = learned(client, home.talk, home.turns[2])
    assert [f.text for f in got.facts] == ["Alana likes green tea"]
    replaced = got.facts[0].replaced
    assert replaced is not None and replaced.text == "Alana likes tea"
    assert (got.unseen, got.ended) == (0, 1)
    assert set(listed(client)) == {got.facts[0].id}


def test_nothing_new_is_empty_and_zero_and_still_moves_the_watermark(client: TestClient, home: Home,
                                                                     writer: Scripted) -> None:
    writer.will((Noop(None),))
    got = learned(client, home.talk, home.turns[3])
    assert (got.facts, got.unseen, got.ended) == ([], 0, 0)
    assert home.fact_count() == 0 and home.watermark() == home.turns[3]


def test_a_turn_of_another_conversation_a_missing_one_and_a_conversation_not_theirs_are_the_same_404(
        client: TestClient, home: Home, writer: Scripted) -> None:
    mine = conversation(home.url, home.id)
    scalar(home.url, "INSERT INTO conversation_participants VALUES (%s, %s, %s) RETURNING person_id",
           (mine, home.id, home.alana))
    ellas = conversation(home.url, home.id)
    scalar(home.url, "INSERT INTO conversation_participants VALUES (%s, %s, %s) RETURNING person_id",
           (ellas, home.id, home.ella))
    (ellas_turn,) = say(home.url, ellas, "Ella's secret", speaker=home.ella)
    strangers = home.id + 1000
    cases = [(mine, home.turns[0]), (home.talk, 999999), (999999, home.turns[0]), (ellas, ellas_turn),
             (ellas, home.turns[0]), (home.talk, ellas_turn), (strangers, home.turns[0])]
    bodies: list[object] = []
    for conversation_id, turn_id in cases:
        got = remember(client, conversation_id, turn_id)
        assert got.status_code == 404, (conversation_id, turn_id)
        assert ErrorResponse.model_validate(got.json()).code == "not_found"
        bodies.append(got.json())
    assert all(b == bodies[0] for b in bodies)
    assert writer.calls == [] and home.fact_count() == 0
    assert (home.watermark(), home.watermark(ellas), home.watermark(mine)) == (None, None, None)


def test_a_conversation_in_another_household_is_404(client: TestClient, home: Home, writer: Scripted) -> None:
    other = int(scalar(home.url, "INSERT INTO households (name) VALUES ('next door') RETURNING id"))
    talk = conversation(home.url, other)
    (turn,) = say(home.url, talk, "Hello", speaker=None)
    assert remember(client, talk, turn).status_code == 404
    assert writer.calls == [] and home.watermark(talk) is None


def test_no_session_is_401_a_foreign_origin_or_non_json_is_403_and_nothing_changes(
        home: Home, writer: Scripted) -> None:
    body = {"conversation_id": home.talk, "turn_id": home.turns[0]}
    anonymous = create_app(Settings(database_url=home.url, build_version="t", public_url=PUBLIC))
    with TestClient(anonymous, base_url=PUBLIC, headers={"origin": PUBLIC}) as c:
        register(FactWriter, writer)
        try:
            foreign = c.post(URL, json=body, headers={"origin": "https://evil.test"})
            plain = c.post(URL, content='{"conversation_id": 1, "turn_id": 1}', headers={"content-type": "text/plain"})
            got = c.post(URL, json=body)
        finally:
            unregister(FactWriter)
    for response in (foreign, plain):
        assert response.status_code == 403
        assert ErrorResponse.model_validate(response.json()).code == "forbidden"
    assert got.status_code == 401 and ErrorResponse.model_validate(got.json()).code == "unauthorized"
    assert writer.calls == [] and home.watermark() is None


@pytest.mark.parametrize("body", [{}, {"conversation_id": 1}, {"turn_id": 1}, {"conversation_id": 0, "turn_id": 1},
                                  {"conversation_id": 1, "turn_id": 0}, {"conversation_id": "x", "turn_id": 1},
                                  {"conversation_id": 1, "turn_id": 1, "text": "extra"}])
def test_a_body_outside_the_request_is_422_and_writes_nothing(client: TestClient, home: Home, writer: Scripted,
                                                              body: dict[str, object]) -> None:
    assert client.post(URL, json=body).status_code == 422
    assert writer.calls == [] and home.watermark() is None


def test_a_refusing_writer_is_422_refused_and_nothing_is_written(client: TestClient, home: Home,
                                                                 writer: Scripted) -> None:
    writer.will(InferenceRefused("no"))
    got = remember(client, home.talk, home.turns[2])
    assert got.status_code == 422 and ErrorResponse.model_validate(got.json()).code == "refused"
    assert home.fact_count() == 0 and home.watermark() is None


def test_an_unavailable_writer_or_memory_is_503_and_nothing_is_written(client: TestClient, home: Home,
                                                                       writer: Scripted) -> None:
    writer.will(InferenceUnavailable("down"))
    got = remember(client, home.talk, home.turns[2])
    assert got.status_code == 503 and ErrorResponse.model_validate(got.json()).code == "unavailable"
    assert home.fact_count() == 0 and home.watermark() is None
    writer.will((fact("Alana likes tea"),))
    register(Memory, Memory.null())
    try:
        got = remember(client, home.talk, home.turns[2])
    finally:
        unregister(Memory)
    assert got.status_code == 503 and ErrorResponse.model_validate(got.json()).code == "unavailable"
    assert home.fact_count() == 0 and home.watermark() is None


def test_the_log_carries_ids_and_counts_never_a_line_or_a_fact(client: TestClient, home: Home, writer: Scripted,
                                                               capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    writer.will((fact("Alana is secretly a pianist", home.alana, home.alana, "private"),))
    capsys.readouterr()
    got = learned(client, home.talk, home.turns[2])
    out = capsys.readouterr().out
    assert got.facts and [e for e in events(out, "http.request") if e["route"] == URL]
    for text in ("learning piano", "pianist", "feed Mochi", "I like tea"):
        assert text not in out
