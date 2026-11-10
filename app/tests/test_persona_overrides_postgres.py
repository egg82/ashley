"""The persona overrides over a real database: versions per household and section, a revert a new version, "back to
the shipped text" a null body, the lock refused at the writer, and the skills' family kept apart in the same table."""

from collections.abc import Coroutine
from typing import Any

import psycopg
import pytest

from ashley.db.pool import PoolDatabase
from ashley.skills import config as skills_config
from ashley.skills.persona import bodies
from ashley.skills.persona_write import PersonaRefused
from ashley.skills.postgres import PostgresSkills
from ashley.skills.postgres_persona import PostgresPersonaOverrides
from ashley.skills.postgres_persona_write import PostgresPersonaWriter
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run

CONFIG = skills_config.load()
SHIPPED = {"wit": "Shipped wit.", "examples": "Shipped examples."}


async def refused(reason: str, change: Coroutine[Any, Any, int]) -> None:
    with pytest.raises(PersonaRefused) as got:
        await change
    assert got.value.reason == reason


def test_versions_reverts_and_heads(db_url: str) -> None:
    home, other = household(db_url), household(db_url)
    alana, olly = person(db_url, home), person(db_url, other)

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        try:
            reads, writes = PostgresPersonaOverrides(database, CONFIG), PostgresPersonaWriter(database, CONFIG, SHIPPED)
            assert await reads.heads(home) == {}
            assert await writes.edit(home, "wit", "Drier.", "too chatty", 0, alana) == 1
            assert await writes.edit(home, "wit", "Driest.", "still", 1, alana) == 2
            assert await writes.edit(other, "wit", "Theirs.", "theirs", 0, olly) == 1
            assert bodies(await reads.heads(home)) == {"wit": "Driest."}
            assert await writes.revert(home, "wit", 0, "back", 2, alana) == 3
            assert bodies(await reads.heads(home)) == {}
            assert (await reads.heads(home))["wit"].restored_from == 0
            assert await writes.revert(home, "wit", 1, "liked it", 3, alana) == 4
            log = await reads.changelog(home, "wit")
            assert [(v.version, v.body, v.restored_from, v.base_version, v.person_id) for v in log] == [
                (4, "Drier.", 1, 3, alana), (3, None, 0, 2, alana), (2, "Driest.", None, 1, alana),
                (1, "Drier.", None, 0, alana)]
            assert bodies(await reads.heads(other)) == {"wit": "Theirs."}
        finally:
            await database.close()

    run(scenario())


def test_refusals(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home)

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        try:
            writes = PostgresPersonaWriter(database, CONFIG, SHIPPED)
            await refused("locked", writes.edit(home, "contract", "Anything.", "why", 0, alana))
            await refused("locked", writes.revert(home, "contract", 0, "why", 0, alana))
            await refused("bad_body", writes.edit(home, "wit", "  ", "why", 0, alana))
            await refused("bad_body", writes.edit(home, "wit", "x" * (CONFIG.max_body_chars + 1), "why", 0, alana))
            await refused("bad_note", writes.edit(home, "wit", "Dry.", " ", 0, alana))
            await refused("unchanged", writes.edit(home, "wit", " Shipped wit. ", "why", 0, alana))
            await refused("unchanged", writes.revert(home, "wit", 0, "why", 0, alana))
            await refused("no_such_version", writes.revert(home, "wit", 1, "why", 0, alana))
            assert await writes.edit(home, "wit", "Dry.", "why", 0, alana) == 1
            await refused("stale", writes.edit(home, "wit", "Drier.", "why", 0, alana))
            await refused("unchanged", writes.edit(home, "wit", "Dry.", "why", 1, alana))
            await refused("unchanged", writes.revert(home, "wit", 1, "why", 1, alana))
            assert await writes.revert(home, "wit", 0, "why", 1, alana) == 2
            await refused("no_such_version", writes.revert(home, "wit", 2, "why", 2, alana))
        finally:
            await database.close()

    run(scenario())


def test_the_table_holds_persona_rows_to_a_person_and_keeps_the_families_apart(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home)

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        try:
            skills = PostgresSkills(database, CONFIG, {})
            await skills.add_kind(home, "wit", "Wit")
            await skills.edit(home, "wit", "A skill body.", "what", "why", 0, None, None)
            await PostgresPersonaWriter(database, CONFIG, SHIPPED).edit(home, "wit", "Dry.", "why", 0, alana)
            skill = await skills.current(home, "wit")
            assert skill is not None and (skill.version, skill.body) == (1, "A skill body.")
            assert bodies(await PostgresPersonaOverrides(database, CONFIG).heads(home)) == {"wit": "Dry."}
        finally:
            await database.close()

    run(scenario())
    for bad in ("INSERT INTO skill_versions (household_id, family, kind, version, body, what, why, status, base_version)"
                " VALUES (%s, 'persona', 'wit', 9, 'x', 'w', 'y', 'live', 0)",
                "INSERT INTO skill_versions (household_id, family, kind, version, body, what, why, status, base_version)"
                " VALUES (%s, 'skill', 'wit', 9, NULL, 'w', 'y', 'live', 0)"):
        with psycopg.connect(db_url) as conn, pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(bad, (home,))
