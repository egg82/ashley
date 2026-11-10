"""The seeds that ship: each loads, names the source skill it came from, carries no instance data, and never
replaces a household's own edit."""

import re
from collections.abc import Mapping

from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.skills import config as skills_config
from ashley.skills import seeds
from ashley.skills.postgres import PostgresSkills
from ashley.skills.seeds import Seed
from ashley.skills.skills import Skills
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, run

CONFIG = skills_config.load()
EXPECTED = {"code": "agentic-engineering", "3d": "cad-design", "research": "search-craft", "writing": "writing-craft"}

# Shapes of instance data and of mechanics that belong to another tool. The household's own names and hosts are
# test_household_names.py's, across the whole tree; these are other tools the source skills name.
LEAKS: Mapping[str, re.Pattern[str]] = {
    "ipv4": re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
    "home path": re.compile(r"~/|/home/|/Users/|/mnt/"),
    "private domain": re.compile(r"\b[\w-]+\.(home|internal|pub|lan|local)\b", re.IGNORECASE),
    "other tool": re.compile(r"Claude Code|subagent|\bhooks\b|\bSKILL\.md\b|WebSearch|SearXNG|\binstance\.md\b", re.IGNORECASE),
    "known name": re.compile(r"\b(fetcharr|makerworld|bambu)\b", re.IGNORECASE),
    "dated incident": re.compile(r"\b20\d\d-\d\d-\d\d\b|\b(Opus|Sonnet|Haiku)\b"),
}


def leaks(body: str) -> list[str]:
    return [name for name, pattern in LEAKS.items() if pattern.search(body)]


def test_every_kind_ships_a_seed_naming_its_source() -> None:
    found = seeds.load(CONFIG)
    assert {k: s.seeded_from for k, s in found.items()} == EXPECTED
    assert all(s.body for s in found.values())


def test_the_seed_bodies_carry_no_instance_data() -> None:
    found = seeds.load(CONFIG)
    assert found
    assert {kind: leaks(s.body) for kind, s in found.items() if leaks(s.body)} == {}


def test_the_scan_can_fail() -> None:
    planted = ("Run it on 10.0.0.5, keep files in ~/cad, ask a subagent, see git.example.home, Claude Code hooks, "
               "fetcharr, dated 2026-10-24.")
    assert sorted(leaks(planted)) == sorted(LEAKS)
    assert leaks("Small functions, tests that can fail.") == []


def test_a_households_edit_is_never_replaced_by_a_seed(db_url: str) -> None:
    home = household(db_url)
    old, new = Seed("code", "Code", "agentic-engineering", "Old seed."), Seed("code", "Code", "agentic-engineering", "New seed.")

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        try:
            services.register(Skills, PostgresSkills(database, CONFIG, {"code": old}))
            await services.get(Skills).edit(home, "code", "Household's own.", "own", "better", 0, None, None)
            services.register(Skills, PostgresSkills(database, CONFIG, {"code": new}))
            skills = services.get(Skills)
            kept = await skills.current(home, "code")
            assert kept is not None and (kept.body, kept.version, kept.seeded_from) == ("Household's own.", 1, None)
            await skills.rollback(home, "code", 0, "back to the seed", None, None)
            back = await skills.current(home, "code")
            assert back is not None and back.body == "New seed."
        finally:
            await database.close()

    run(scenario())
