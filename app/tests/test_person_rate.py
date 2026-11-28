"""`Sessions.allow` over a real database: a person's requests inside a window are allowed up to the policy's maximum, the
next is refused and still counted, a person counts apart from another, and a new window starts at zero."""

from ashley.signin import policy as signin_policy
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template, run, scalar
from test_signin_postgres import household, sessions
import psycopg
from ashley.people import admin


def allowed(url: str, home: int, *people: int) -> list[bool]:
    out: list[bool] = []

    async def scenario() -> None:
        async with sessions(url, press_max=2, press_window_seconds=86400) as s:
            out.extend([await s.allow(home, p) for p in people])

    run(scenario())
    return out


def test_the_count_is_kept_per_person_and_window(db_url: str) -> None:
    home, alana, _ = household(db_url)
    with psycopg.connect(db_url) as conn:
        ella = admin.add_person(conn, home, "Ella")
    assert allowed(db_url, home, alana, alana, alana, alana, ella) == [True, True, False, False, True]
    assert scalar(db_url, "SELECT requests FROM person_requests WHERE person_id = %s", (alana,)) == 4

    scalar(db_url, "WITH u AS (UPDATE person_requests SET window_start = window_start - interval '2 days' "
           "WHERE person_id = %s RETURNING 1) SELECT count(*) FROM u", (alana,))
    assert allowed(db_url, home, alana) == [True]
    assert scalar(db_url, "SELECT count(*) FROM person_requests WHERE person_id = %s", (alana,)) == 1
    assert scalar(db_url, "SELECT requests FROM person_requests WHERE person_id = %s", (alana,)) == 1


def test_the_shipped_policy_allows_some_presses() -> None:
    loaded = signin_policy.load()
    assert loaded.press_max >= 1 and loaded.press_window_seconds >= 1
