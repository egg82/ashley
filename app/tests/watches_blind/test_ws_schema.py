"""The database's own constraints on `watches` and the `wakes` rows of kind `watch`."""

from typing import Any

import psycopg
import pytest
from contract.conversations_support import person
from watches_blind_support import (World, count, exists, insert_wake, insert_watch, scenario, settle_wakes,
                                   wakes_of)

Violation = (psycopg.errors.CheckViolation, psycopg.errors.NotNullViolation)


def put(w: World, **more: Any) -> int:
    return insert_watch(w.url, household_id=w.hid, person_id=w.owner, **more)


def test_a_valid_row_of_each_state_is_accepted(db_url: str) -> None:
    async def body(w: World) -> None:
        put(w, target="a")
        put(w, target="b", state="paused", reason="unreachable", failures=3)
        put(w, target="c", state="ended", reason="until", ended=True)
        put(w, target="d", state="ended", reason="expired", ended=True)
        put(w, target="e", state="ended", reason="disarmed", ended=True)
        assert count(w.url) == 5

    scenario(db_url, body)


def test_reason_is_null_exactly_when_armed(db_url: str) -> None:
    async def body(w: World) -> None:
        with pytest.raises(psycopg.errors.CheckViolation):
            put(w, state="armed", reason="unreachable")
        with pytest.raises(psycopg.errors.CheckViolation):
            put(w, state="paused", reason=None)
        with pytest.raises(psycopg.errors.CheckViolation):
            put(w, state="ended", reason=None, ended=True)
        assert count(w.url) == 0

    scenario(db_url, body)


def test_an_ended_watch_takes_only_until_expired_or_disarmed(db_url: str) -> None:
    async def body(w: World) -> None:
        for bad in ("unreachable", "paused", "done", ""):
            with pytest.raises(psycopg.errors.CheckViolation):
                put(w, state="ended", reason=bad, ended=True)

    scenario(db_url, body)


def test_a_paused_watch_cannot_carry_an_ending_reason(db_url: str) -> None:
    async def body(w: World) -> None:
        for bad in ("until", "expired", "disarmed"):
            with pytest.raises(psycopg.errors.CheckViolation):
                put(w, state="paused", reason=bad, failures=3)

    scenario(db_url, body)


def test_state_and_armed_by_take_only_their_values(db_url: str) -> None:
    async def body(w: World) -> None:
        with pytest.raises(psycopg.errors.CheckViolation):
            put(w, state="sleeping", reason=None)
        with pytest.raises(psycopg.errors.CheckViolation):
            put(w, armed_by="someone")
        assert count(w.url) == 0

    scenario(db_url, body)


def test_kind_is_a_slug(db_url: str) -> None:
    async def body(w: World) -> None:
        for bad in ("Claude Session", ""):
            with pytest.raises(psycopg.errors.CheckViolation):
                put(w, kind=bad)

    scenario(db_url, body)


def test_target_is_one_to_500_characters(db_url: str) -> None:
    async def body(w: World) -> None:
        put(w, target="x" * 500)
        with pytest.raises(psycopg.errors.CheckViolation):
            put(w, target="")
        with pytest.raises(psycopg.errors.CheckViolation):
            put(w, target="x" * 501)

    scenario(db_url, body)


def test_label_is_one_to_100_characters(db_url: str) -> None:
    async def body(w: World) -> None:
        put(w, target="a", label="x" * 100)
        with pytest.raises(psycopg.errors.CheckViolation):
            put(w, target="b", label="")
        with pytest.raises(psycopg.errors.CheckViolation):
            put(w, target="c", label="x" * 101)

    scenario(db_url, body)


def test_track_is_one_to_eight_fields(db_url: str) -> None:
    async def body(w: World) -> None:
        put(w, target="a", track=("f",))
        put(w, target="b", track=tuple(f"f{i}" for i in range(8)))
        with pytest.raises(psycopg.errors.CheckViolation):
            put(w, target="c", track=())
        with pytest.raises(psycopg.errors.CheckViolation):
            put(w, target="d", track=tuple(f"f{i}" for i in range(9)))

    scenario(db_url, body)


def test_interval_is_positive_and_counters_are_not_negative(db_url: str) -> None:
    async def body(w: World) -> None:
        for more in ({"interval_s": 0}, {"interval_s": -5}, {"failures": -1}, {"version": -1}, {"series": -1}):
            with pytest.raises(psycopg.errors.CheckViolation):
                put(w, **more)
        put(w, target="zero", version=0, series=0, failures=0)

    scenario(db_url, body)


def test_one_live_watch_per_person_kind_and_target(db_url: str) -> None:
    async def body(w: World) -> None:
        put(w)
        with pytest.raises(psycopg.errors.UniqueViolation):
            put(w)
        with pytest.raises(psycopg.errors.UniqueViolation):
            put(w, state="paused", reason="refused", failures=3)
        put(w, kind="other")
        put(w, target="other")
        insert_watch(w.url, household_id=w.hid, person_id=w.mate)

    scenario(db_url, body)


def test_an_ended_watch_does_not_hold_the_target(db_url: str) -> None:
    async def body(w: World) -> None:
        put(w, state="ended", reason="until", ended=True)
        put(w, state="ended", reason="expired", ended=True)
        put(w)
        assert count(w.url) == 3

    scenario(db_url, body)


def test_a_person_of_another_household_is_refused(db_url: str) -> None:
    async def body(w: World) -> None:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            insert_watch(w.url, household_id=w.hid, person_id=w.stranger)
        assert count(w.url) == 0

    scenario(db_url, body)


def test_a_watch_goes_with_its_person(db_url: str) -> None:
    async def body(w: World) -> None:
        gone = person(w.url, w.hid, "leaver")
        wid = insert_watch(w.url, household_id=w.hid, person_id=gone)
        keep = put(w)
        with psycopg.connect(w.url, autocommit=True) as conn:
            conn.execute("DELETE FROM people WHERE id = %s", (gone,))
        assert not exists(w.url, wid) and exists(w.url, keep)

    scenario(db_url, body)


def test_wakes_accepts_a_watch_wake_with_its_watch_changes_and_person(db_url: str) -> None:
    async def body(w: World) -> None:
        wid = put(w)
        insert_wake(w.url, household_id=w.hid, person_id=w.owner, watch_id=wid, changes={"what": "changed"})
        assert len(wakes_of(w.url, wid)) == 1

    scenario(db_url, body)


def test_watch_id_is_set_exactly_for_kind_watch(db_url: str) -> None:
    async def body(w: World) -> None:
        wid = put(w)
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_wake(w.url, household_id=w.hid, person_id=w.owner, watch_id=None, changes={"what": "changed"})
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_wake(w.url, household_id=w.hid, person_id=w.owner, kind="reminder", watch_id=wid, event_id="r1")
        insert_wake(w.url, household_id=w.hid, person_id=w.owner, kind="reminder", event_id="r2")

    scenario(db_url, body)


def test_a_watch_wake_needs_changes_and_a_person_and_no_device(db_url: str) -> None:
    async def body(w: World) -> None:
        wid = put(w)
        device = int(_device(w))
        with pytest.raises(Violation):
            insert_wake(w.url, household_id=w.hid, person_id=w.owner, watch_id=wid, changes=None)
        with pytest.raises(Violation):
            insert_wake(w.url, household_id=w.hid, person_id=None, watch_id=wid, changes={"what": "changed"})
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_wake(w.url, household_id=w.hid, person_id=w.owner, watch_id=wid, changes={"what": "changed"},
                        device_id=device)
        assert wakes_of(w.url, wid) == []

    scenario(db_url, body)


def test_changes_must_be_a_json_object(db_url: str) -> None:
    async def body(w: World) -> None:
        wid = put(w)
        with pytest.raises(psycopg.errors.CheckViolation):
            _raw_changes(w, wid, "[1]")

    scenario(db_url, body)


def test_a_watch_wake_is_one_per_household_and_event(db_url: str) -> None:
    async def body(w: World) -> None:
        wid = put(w)
        insert_wake(w.url, household_id=w.hid, person_id=w.owner, watch_id=wid, changes={}, event_id=f"watch:{wid}:1")
        with pytest.raises(psycopg.errors.UniqueViolation):
            insert_wake(w.url, household_id=w.hid, person_id=w.owner, watch_id=wid, changes={},
                        event_id=f"watch:{wid}:1")

    scenario(db_url, body)


def test_deleting_a_watch_deletes_its_wakes(db_url: str) -> None:
    async def body(w: World) -> None:
        wid = put(w)
        insert_wake(w.url, household_id=w.hid, person_id=w.owner, watch_id=wid, changes={})
        settle_wakes(w.url, wid)
        with psycopg.connect(w.url, autocommit=True) as conn:
            conn.execute("DELETE FROM watches WHERE id = %s", (wid,))
        assert wakes_of(w.url, wid) == []
        assert _wake_count(w) == 0

    scenario(db_url, body)


def test_deleting_a_person_deletes_their_watches_wakes(db_url: str) -> None:
    async def body(w: World) -> None:
        gone = person(w.url, w.hid, "leaver")
        wid = insert_watch(w.url, household_id=w.hid, person_id=gone)
        insert_wake(w.url, household_id=w.hid, person_id=gone, watch_id=wid, changes={})
        with psycopg.connect(w.url, autocommit=True) as conn:
            conn.execute("DELETE FROM people WHERE id = %s", (gone,))
        assert _wake_count(w) == 0

    scenario(db_url, body)


def _wake_count(w: World) -> int:
    with psycopg.connect(w.url, autocommit=True) as conn:
        found = conn.execute("SELECT count(*) FROM wakes").fetchone()
    assert found is not None
    return int(found[0])


def _device(w: World) -> int:
    with psycopg.connect(w.url, autocommit=True) as conn:
        found = conn.execute("INSERT INTO devices (household_id, name, place, audience, medium, kind, token_sha256) "
                             "VALUES (%s, 'dev', 'hall', 'household', 'text', 'chat', sha256('x'::bytea)) RETURNING id",
                             (w.hid,)).fetchone()
    assert found is not None
    return int(found[0])


def _raw_changes(w: World, watch: int, text: str) -> None:
    with psycopg.connect(w.url, autocommit=True) as conn:
        conn.execute("INSERT INTO wakes (household_id, kind, event_id, event, at, due_at, person_id, watch_id, changes) "
                     "VALUES (%s, 'watch', 'raw', 'watch', now(), now(), %s, %s, %s::jsonb)",
                     (w.hid, w.owner, watch, text))
