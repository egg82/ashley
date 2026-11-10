"""The Reminders tab's feed: a reminder that waits on a deposit is listed with its rule in words, no repeat, and
cancelled like any other."""

from deposit_support import rule
from ashley.senses.postgres_deposits import PostgresDeposits
from ashley.db.pool import PoolDatabase
from ashley.senses.wakes import Reminder
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import run, scalar
from datetime import UTC, datetime
from fastapi.testclient import TestClient
from test_reminders_routes import ORIGIN, Homes, client as client, homes as homes


def arm(url: str, home: int, who: int) -> int:
    async def go() -> int:
        db = PoolDatabase(url, connect_timeout_s=5.0)
        await db.open()
        try:
            return await PostgresDeposits(db).arm(Reminder(home, who, who, "Bonus is in.", datetime.now(UTC), None), rule())
        finally:
            await db.close()

    out: list[int] = []

    async def keep() -> None:
        out.append(await go())

    run(keep())
    return out[0]


def test_a_deposit_reminder_is_listed_in_words_and_cancels(db_url: str, homes: Homes, client: TestClient) -> None:
    made = arm(db_url, homes.home, homes.alana)
    (item,) = client.get("/api/reminders").json()["reminders"]
    assert item["id"] == made and item["repeat"] is None and item["state"] == "scheduled"
    assert item["on_deposit"] == "a deposit into Checking of at least 1000.00 from a payee containing “Acme”"
    assert client.delete(f"/api/reminders/{made}", headers=ORIGIN).status_code == 200
    assert client.get("/api/reminders").json()["reminders"] == []
    assert scalar(db_url, "SELECT outcome FROM wakes WHERE id = %s", (made,)) == "cancelled"
