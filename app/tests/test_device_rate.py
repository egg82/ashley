"""The device rate in device_rate.json, and its count in Postgres: requests inside a window are allowed up to the
maximum, the next is refused and still counted, a device counts apart from another, and a new window starts at zero."""

import pytest
from ashley.channels.device_rate import Rate, load, parse
from ashley.channels.postgres_devices import PostgresDevices
from ashley.db.pool import PoolDatabase
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template, run
from contract.conversations_support import scalar


def test_the_shipped_file_is_valid() -> None:
    assert load().max_requests >= 1


def test_a_well_formed_file_parses() -> None:
    assert parse({"window_seconds": 60, "max_requests": 5}) == Rate(60, 5)


@pytest.mark.parametrize("bad", [[], {}, {"window_seconds": 60}, {"window_seconds": 60, "max_requests": 5, "x": 1},
                                 {"window_seconds": 0, "max_requests": 5}, {"window_seconds": 60, "max_requests": 1.5},
                                 {"window_seconds": True, "max_requests": 5}, {"window_seconds": 60, "max_requests": "5"}])
def test_a_malformed_file_is_refused(bad: object) -> None:
    with pytest.raises(ValueError):
        parse(bad)


def allow_all(db_url: str, rate: Rate, *device_ids: int) -> list[bool]:
    out: list[bool] = []

    async def scenario() -> None:
        db = PoolDatabase(db_url)
        await db.open()
        try:
            devices = PostgresDevices(db, rate)
            out.extend([await devices.allow(d) for d in device_ids])
        finally:
            await db.close()

    run(scenario())
    return out


def test_the_count_is_kept_per_device_and_window(db_url: str) -> None:
    home = household(db_url)
    ids = [scalar(db_url, "INSERT INTO devices (household_id, name, place, audience, medium, kind, token_sha256) "
                  "VALUES (%s, 'd', 'p', 'present', 'text', 'chat', decode(%s, 'hex')) RETURNING id",
                  (home, f"{n:064x}")) for n in (1, 2)]
    rate = Rate(86400, 2)
    assert allow_all(db_url, rate, ids[0], ids[0], ids[0], ids[0], ids[1]) == [True, True, False, False, True]
    assert scalar(db_url, "SELECT requests FROM device_requests WHERE device_id = %s", (ids[0],)) == 4

    scalar(db_url, "WITH u AS (UPDATE device_requests SET window_start = window_start - interval '2 days' "
           "WHERE device_id = %s RETURNING 1) SELECT count(*) FROM u", (ids[0],))
    assert allow_all(db_url, rate, ids[0]) == [True]
    assert scalar(db_url, "SELECT count(*) FROM device_requests WHERE device_id = %s", (ids[0],)) == 1
    assert scalar(db_url, "SELECT requests FROM device_requests WHERE device_id = %s", (ids[0],)) == 1
