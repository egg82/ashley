"""A push older than the outbox's `stale_s` is dropped and logged; the answer stays stored on the thread."""

import psycopg
import pytest
from ashley.channels.model import Outbound
from ashley.channels.outbox import Pushed
from ashley.channels.postgres_outbox import PostgresOutbox
from ashley.conversations.model import NewTurn
from contract.conversations_support import POLICY, household, run, scalar
from later_support import Logged
from nse_blind_support import rig

STALE_S = 100.0
THREAD = "web:1"


def _age(url: str, seconds: float) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(b"UPDATE outbox SET created_at = created_at - %s::interval", (f"{seconds} seconds",))


def test_a_stale_push_is_dropped_and_logged_and_its_answer_stays_stored(db_url: str,
                                                                       capsys: pytest.CaptureFixture[str]) -> None:
    logged = Logged(capsys)

    household(db_url, "another")  # the conversation's id (1) differs from its household's (2)

    async def go() -> None:
        async with rig(db_url) as r:
            conv_id, said_id = await r.said(THREAD)
            claim = await r.inflight.begin(conv_id, said_id, "cp")
            outbox = PostgresOutbox(r.db, STALE_S, POLICY)
            push = Pushed(r.home, THREAD, Outbound(conv_id, "text", "The lamp is on."))
            await outbox.answer(claim, NewTurn("ashley", "The lamp is on.", None, answers=said_id), [push])
            _age(db_url, STALE_S * 3)
            assert await outbox.take("web:") == []
            assert await outbox.take("web:") == []

    run(go())
    dropped = logged.events("outbox.stale_dropped")
    assert len(dropped) == 1
    assert dropped[0]["conversation"] == "1" and float(dropped[0]["age_ms"]) >= STALE_S * 3 * 1000
    assert dropped[0]["id"].isdigit()
    assert scalar(db_url, "SELECT count(*) FROM turns WHERE author = 'ashley' AND text = 'The lamp is on.'") == 1
    assert scalar(db_url, "SELECT count(*) FROM outbox") == 0


def test_a_fresh_push_is_returned_and_not_logged_stale(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logged = Logged(capsys)
    got: list[int] = []

    async def go() -> None:
        async with rig(db_url) as r:
            conv_id, _ = await r.said(THREAD)
            outbox = PostgresOutbox(r.db, STALE_S, POLICY)
            await outbox.add(r.home, THREAD, Outbound(conv_id, "text", "fresh"))
            got.extend(w.id for w in await outbox.take("web:"))

    run(go())
    assert len(got) == 1
    assert logged.events("outbox.stale_dropped") == []


def test_only_the_stale_ones_are_dropped_among_several(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logged = Logged(capsys)
    bodies: list[str] = []

    async def go() -> None:
        async with rig(db_url) as r:
            conv_id, _ = await r.said(THREAD)
            outbox = PostgresOutbox(r.db, STALE_S, POLICY)
            await outbox.add(r.home, THREAD, Outbound(conv_id, "text", "old"))
            _age(db_url, STALE_S * 2)
            await outbox.add(r.home, THREAD, Outbound(conv_id, "text", "new"))
            bodies.extend(w.outbound.body for w in await outbox.take("web:"))

    run(go())
    assert bodies == ["new"]
    assert len(logged.events("outbox.stale_dropped")) == 1
