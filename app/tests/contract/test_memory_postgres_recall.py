"""The recall eval (`ashley.memory.eval.recall`) against PostgresMemory on a migrated database: every case, by SQL and
real full-text search."""

from datetime import UTC, datetime

from ashley.memory.eval import recall
from ashley.memory.model import Add, Asker, NewFact, Visibility
from ashley.memory.postgres import PostgresMemory

from conversations_support import household, person, run
from memory_support import ConversationsAsTheyCome, conversation, pool, recall_cast

AT = datetime(2026, 3, 1, tzinfo=UTC)

PERSON_HOUSEHOLD = {"alana": "home", "elodie": "home", "other-household": "other"}


def test_who_hears_what_when_the_query_reaches_every_fact(db_url: str) -> None:
    """The eval's exclusions pass vacuously when its query shares no word with the excluded fact; here every fact
    matches the query, so only the visibility filter decides."""
    home = household(db_url)
    alana, elodie = person(db_url, home, "alana"), person(db_url, home, "elodie")
    talk = conversation(db_url, home)
    rows: list[tuple[int | None, Visibility]] = [(None, "shared"), (alana, "shared"), (alana, "discreet"), (alana, "private"),
            (elodie, "discreet"), (elodie, "private")]
    seen = {
        # speaker, owner_only -> {(owner, visibility): may_volunteer}
        (None, False): {(None, "shared"): True, (alana, "shared"): True},
        (None, True): {(None, "shared"): True, (alana, "shared"): True},
        (alana, False): {(None, "shared"): True, (alana, "shared"): True, (alana, "discreet"): True,
                        (elodie, "discreet"): False},
        (alana, True): {(None, "shared"): True, (alana, "shared"): True, (alana, "discreet"): True,
                       (alana, "private"): True, (elodie, "discreet"): False},
    }

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            ops = [Add(NewFact(owner, owner, visibility, True, "other", False, f"tea number {i}"))
                   for i, (owner, visibility) in enumerate(rows)]
            ids = dict(zip(await memory.apply(home, talk, ops, AT), rows, strict=True))
            for (speaker, owner_only), wanted in seen.items():
                got = await memory.recall(Asker(home, speaker, owner_only, AT), "tea")
                assert {ids[r.fact.id]: r.may_volunteer for r in got} == wanted, (speaker, owner_only)

    run(scenario())


def test_every_recall_case_passes(db_url: str) -> None:
    data = recall.load()
    assert set(PERSON_HOUSEHOLD) == set(data["people"])
    recall_cast(db_url, data["people"], data["households"], PERSON_HOUSEHOLD)

    async def scenario() -> None:
        async with pool(db_url) as db:
            results = await recall.run_recall(lambda: ConversationsAsTheyCome(db, db_url))
        assert len(results) == len(data["cases"]) > 0
        assert not [(r.case_id, r.leaked, r.volunteered) for r in results if r.leaked or r.volunteered]
        assert not [(r.case_id, r.missing) for r in results if r.missing]

    run(scenario())
