"""`MAY_HEAR` over a real Postgres, the one rule facts and turns pass: a `members` row is heard only when only the
speaker hears the reply and the speaker is known."""

from typing import get_args

import psycopg
import pytest
from ashley.hearing import MAY_HEAR, Visibility
from hm_support import make_home


def heard(url: str, visibility: str, owner: int | None, speaker: int | None, owner_only: bool) -> bool:
    with psycopg.connect(url) as conn:
        row = conn.execute(f"SELECT {MAY_HEAR} FROM (SELECT %(v)s::text AS visibility, %(o)s::bigint AS owner_id) r"
                           .encode(), {"v": visibility, "o": owner, "speaker": speaker, "owner_only": owner_only}
                           ).fetchone()
    assert row is not None
    return bool(row[0])


def test_members_is_a_visibility() -> None:
    assert "members" in get_args(Visibility)
    assert set(get_args(Visibility)) == {"shared", "discreet", "members", "private"}


@pytest.mark.parametrize("owner", [None, 1])
def test_a_members_row_is_heard_only_by_a_known_speaker_who_alone_hears_the_reply(db_url: str, owner: int | None) -> None:
    assert heard(db_url, "members", owner, 2, True) is True
    assert heard(db_url, "members", owner, 1, True) is True
    assert heard(db_url, "members", owner, None, True) is False
    assert heard(db_url, "members", owner, 2, False) is False
    assert heard(db_url, "members", owner, None, False) is False


def test_the_other_visibilities_are_as_they_were(db_url: str) -> None:
    assert heard(db_url, "shared", None, None, False) is True
    assert heard(db_url, "discreet", None, None, False) is False
    assert heard(db_url, "discreet", None, 2, False) is True
    assert heard(db_url, "private", 1, 2, True) is False
    assert heard(db_url, "private", 1, 1, True) is True
    assert heard(db_url, "private", 1, 1, False) is False
    assert heard(db_url, "private", None, 1, True) is False


def test_the_schema_stores_a_members_fact_and_still_refuses_an_unknown_visibility(db_url: str) -> None:
    home = make_home(db_url)
    assert home.row(home.raw("a members fact", None, "members"))[2] == "members"
    with pytest.raises(psycopg.errors.CheckViolation):
        home.raw("nonsense", None, "everyone")
