"""A bench's whole talk through the real app over a real database: the conversations on its thread read back oldest
or newest as the history route pages them, closed ones included, each turn readable by `GET
/api/chat/conversations/{id}`; another person's bench is 404."""

from collections.abc import Generator

import pytest
from ashley import services
from ashley.api.history_models import PastHistory
from ashley.api.models import ErrorResponse
from ashley.conversations.model import NewTurn
from ashley.main import create_app
from ashley.settings import Settings
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import place_before_now, run, service
from fastapi.testclient import TestClient
from respond_support import ALANA, SAM
from test_workshop_routes import PUBLIC, As, opened, seeded


@pytest.fixture
def signed_in(db_url: str) -> Generator[As]:
    seeded(db_url)
    app = create_app(Settings(database_url=db_url, build_version="test", public_url=PUBLIC))
    with TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC}) as client:
        yield As(app, client)
    services.unregister(Workshop)


def _talk(db_url: str, thread: str, *texts: str) -> list[int]:
    """One conversation per text on `thread`, each closed before the next is started."""
    made: list[int] = []

    async def scenario() -> None:
        async with service(db_url) as conv:
            for text in texts:
                found = await conv.for_thread(ALANA.household_id, thread, "brainstorm", [ALANA.id])
                await conv.add_turn(found.id, NewTurn("person", text, ALANA.id))
                made.append(found.id)
                place_before_now(db_url, found.id, 2_000_000)

    run(scenario())
    return made


def test_a_bench_whose_talk_closed_still_reads_back_all_of_it(signed_in: As, db_url: str) -> None:
    alana = signed_in(ALANA)
    bench = opened(alana)
    first, second = _talk(db_url, bench.thread, "screws?", "and washers?")
    assert alana.get(f"/api/benches/{bench.id}/conversation").json()["turns"] == []
    got = PastHistory.model_validate(alana.get(f"/api/benches/{bench.id}/conversations").json())
    assert [(c.id, c.state, c.turn_count) for c in got.conversations] == [(second, "closed", 1), (first, "closed", 1)]
    assert got.next is None
    paged = PastHistory.model_validate(alana.get(f"/api/benches/{bench.id}/conversations?limit=1").json())
    assert [c.id for c in paged.conversations] == [second] and paged.next is not None
    rest = alana.get(f"/api/benches/{bench.id}/conversations?limit=1&before={paged.next}")
    assert [c["id"] for c in rest.json()["conversations"]] == [first]


def test_only_this_benchs_thread_is_listed(signed_in: As, db_url: str) -> None:
    alana = signed_in(ALANA)
    bench, other = opened(alana, "one"), opened(alana, "two")
    mine, = _talk(db_url, bench.thread, "here")
    _talk(db_url, other.thread, "there")
    got = PastHistory.model_validate(alana.get(f"/api/benches/{bench.id}/conversations").json())
    assert [c.id for c in got.conversations] == [mine]


def test_another_persons_bench_history_is_404(signed_in: As, db_url: str) -> None:
    bench = opened(signed_in(ALANA))
    _talk(db_url, bench.thread, "private")
    sam = signed_in(SAM)
    for url in (f"/api/benches/{bench.id}/conversations", f"/api/benches/{bench.id + 99}/conversations"):
        response = sam.get(url)
        assert response.status_code == 404 and ErrorResponse.model_validate(response.json()).code == "not_found"
