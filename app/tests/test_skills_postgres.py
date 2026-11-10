"""The skills over a real database: versions numbered per household and kind, a rollback a new version, a pinned kind's
proposals, a seed read until the first edit, and her tools setting a bench's kind of work and loading its skill."""

import json
from pathlib import Path

import pytest

from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.inference.model import ToolCall
from ashley.live.live import Live
from ashley.skills import config as skills_config
from ashley.skills import seeds
from ashley.skills.postgres import PostgresSkills
from ashley.skills.seeds import Seed
from ashley.skills.skills import SkillRefused, Skills
from ashley.tools.bench_skills import BenchSkillTools
from ashley.workshop import rules as workshop_rules
from ashley.workshop.model import Owner
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run
from live_support import FakeLive

CONFIG = skills_config.load()
SEED = Seed("code", "Code", "agentic-engineering", "Small functions.")


async def wired(url: str, with_seed: bool = False) -> PoolDatabase:
    database = PoolDatabase(url)
    await database.open()
    services.register(Live, FakeLive())
    services.register(Workshop, PostgresWorkshop(database, workshop_rules.load()))
    services.register(Skills, PostgresSkills(database, CONFIG, {"code": SEED} if with_seed else {}))
    return database


def test_versions_rollback_and_the_edit_count(db_url: str) -> None:
    home, other = household(db_url), household(db_url)

    async def scenario() -> None:
        database = await wired(db_url)
        try:
            skills = services.get(Skills)
            with pytest.raises(SkillRefused) as unknown:
                await skills.current(home, "code")
            assert unknown.value.reason == "unknown_kind"
            await skills.add_kind(home, "code", "Code")
            assert await skills.current(home, "code") is None
            first = await skills.edit(home, "code", "one", "wrote it", "needed it", 0, None, None)
            second = await skills.edit(home, "code", "two", "tightened", "too loose", 1, None, None)
            assert (first.version, second.version, second.status) == (1, 2, "live")
            with pytest.raises(SkillRefused) as stale:
                await skills.edit(home, "code", "three", "x", "y", 1, None, None)
            assert stale.value.reason == "stale"
            with pytest.raises(SkillRefused) as same:
                await skills.edit(home, "code", "two", "x", "y", 2, None, None)
            assert same.value.reason == "unchanged"
            back = await skills.rollback(home, "code", 1, "worse", None, None)
            now = await skills.current(home, "code")
            assert back.version == 3 and now is not None and (now.body, now.version, now.edits) == ("one", 3, 3)
            assert [(v.version, v.restored_from) for v in await skills.changelog(home, "code")] == [(3, 1), (2, None), (1, None)]
            with pytest.raises(SkillRefused):
                await skills.current(other, "code")
        finally:
            await database.close()

    run(scenario())


def test_a_pinned_kind_holds_her_edit_until_a_person_approves_and_a_moved_skill_makes_it_stale(db_url: str) -> None:
    home = household(db_url)
    sam = person(db_url, home)

    async def scenario() -> None:
        database = await wired(db_url)
        try:
            skills = services.get(Skills)
            await skills.add_kind(home, "writing", "Writing")
            await skills.edit(home, "writing", "plain", "wrote", "needed", 0, None, None)
            await skills.pin(home, "writing", True)
            held = await skills.edit(home, "writing", "plainer", "cut", "wordy", 1, None, None)
            mine = await skills.edit(home, "writing", "plain, mine", "edit", "mine", 1, None, sam)
            assert (held.status, mine.status) == ("proposed", "live")
            now = await skills.current(home, "writing")
            assert now is not None and (now.body, now.pinned, now.edits) == ("plain, mine", True, 2)
            assert now.proposal is not None and now.proposal.version == held.version
            with pytest.raises(SkillRefused) as stale:
                await skills.decide(home, "writing", held.version, True)
            assert stale.value.reason == "stale"
            declined = await skills.decide(home, "writing", held.version, False)
            assert declined.status == "declined"
            again = await skills.edit(home, "writing", "plainest", "cut", "wordy", 3, None, None)
            assert (await skills.decide(home, "writing", again.version, True)).status == "live"
        finally:
            await database.close()

    run(scenario())


def test_a_seed_is_read_until_the_first_edit_and_is_a_rollback_target(db_url: str) -> None:
    home = household(db_url)

    async def scenario() -> None:
        database = await wired(db_url, with_seed=True)
        try:
            skills = services.get(Skills)
            seed = await skills.current(home, "code")
            assert seed is not None and (seed.version, seed.seeded_from, seed.edits) == (0, "agentic-engineering", 0)
            await skills.edit(home, "code", "Mine.", "own", "better", 0, None, None)
            await skills.rollback(home, "code", 0, "back", None, None)
            restored = await skills.current(home, "code")
            assert restored is not None and (restored.body, restored.version, restored.seeded_from) == (SEED.body, 2, None)
        finally:
            await database.close()

    run(scenario())


def test_her_tools_set_the_kind_of_work_load_its_skill_edit_and_roll_it_back(db_url: str) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))

    async def scenario() -> None:
        database = await wired(db_url, with_seed=True)
        try:
            shop = services.get(Workshop)
            bench = await shop.open(alana, "a script")
            hers = BenchSkillTools(home, alana.person_id, bench.id)
            before = (await hers.catalogue()).instructions or ""
            assert "Method for" not in before
            set_ = await hers.call(ToolCall("w", "bench_work", {"work": "code"}))
            assert not set_.is_error and (await shop.read(alana, bench.id)).bench.work == "code"
            assert json.loads(set_.content)["method"] == {"version": 0, "text": SEED.body}
            loaded = (await hers.catalogue()).instructions or ""
            assert "skill code, version 0" in loaded and SEED.body in loaded
            edited = await hers.call(ToolCall("e", "skill_edit", {"body": "Tests first.", "base_version": 0,
                                                                  "what": "tests", "why": "bugs"}))
            assert json.loads(edited.content) == {"kind": "code", "version": 1, "status": "live"}
            assert "skill code, version 1" in ((await hers.catalogue()).instructions or "")
            stale = await hers.call(ToolCall("s", "skill_edit", {"body": "x", "base_version": 0, "what": "a", "why": "b"}))
            assert stale.is_error and stale.content.startswith("stale:")
            await hers.call(ToolCall("r", "skill_rollback", {"to_version": 0, "why": "worse"}))
            assert SEED.body in ((await hers.catalogue()).instructions or "")
            read = json.loads((await hers.call(ToolCall("d", "skill_read", {}))).content)
            assert (read["version"], read["edits"]) == (2, 2) and [c["version"] for c in read["changelog"]] == [2, 1]
            cleared = await hers.call(ToolCall("n", "bench_work", {"work": "none"}))
            assert not cleared.is_error and (await shop.read(alana, bench.id)).bench.work is None
        finally:
            await database.close()

    run(scenario())


def test_a_kind_is_started_by_shape_and_listed_with_the_seeds_and_the_households_own(db_url: str) -> None:
    home, other = household(db_url), household(db_url)

    async def scenario() -> None:
        database = await wired(db_url, with_seed=True)
        try:
            skills = services.get(Skills)
            for bad in ("Electronics", "-x", "a b", "x" * 41, ""):
                with pytest.raises(SkillRefused) as refused:
                    await skills.add_kind(home, bad, "Label")
                assert refused.value.reason == "bad_kind", bad
            with pytest.raises(SkillRefused):
                await skills.add_kind(home, "garden", "  ")
            made = await skills.add_kind(home, "garden-planning", "Garden planning")
            again = await skills.add_kind(home, "garden-planning", "Renamed")
            assert made == again and made.label == "Garden planning"
            assert [(k.kind, k.label) for k in await skills.kinds(home)] == [("code", "Code"),
                                                                              ("garden-planning", "Garden planning")]
            assert [k.kind for k in await skills.kinds(other)] == ["code"]
            with pytest.raises(SkillRefused) as unknown:
                await skills.edit(other, "garden-planning", "x", "a", "b", 0, None, None)
            assert unknown.value.reason == "unknown_kind"
        finally:
            await database.close()

    run(scenario())


def test_she_starts_a_kind_of_work_on_a_bench_with_a_label_and_writes_its_first_method(db_url: str) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))

    async def scenario() -> None:
        database = await wired(db_url)
        try:
            shop = services.get(Workshop)
            bench = await shop.open(alana, "a circuit")
            hers = BenchSkillTools(home, alana.person_id, bench.id)
            bare = await hers.call(ToolCall("w", "bench_work", {"work": "electronics"}))
            assert bare.is_error and bare.content.startswith("bad_arguments:")
            made = await hers.call(ToolCall("w", "bench_work", {"work": "electronics", "label": "Electronics"}))
            assert not made.is_error and json.loads(made.content) == {"work": "electronics"}
            assert (await shop.read(alana, bench.id)).bench.work == "electronics"
            assert "electronics (Electronics)" in ((await hers.catalogue()).instructions or "")
            wrote = await hers.call(ToolCall("e", "skill_edit", {"body": "Check polarity first.", "base_version": 0,
                                                                  "what": "first", "why": "new kind"}))
            assert json.loads(wrote.content)["version"] == 1
            assert "Method for Electronics work" in ((await hers.catalogue()).instructions or "")
            bad = await hers.call(ToolCall("b", "bench_work", {"work": "Bad Kind", "label": "x"}))
            assert bad.is_error and bad.content.startswith("bad_kind:")
        finally:
            await database.close()

    run(scenario())


def test_seed_documents_name_what_they_were_seeded_from(tmp_path: Path) -> None:
    (tmp_path / "code.md").write_text(
        "---\nkind: code\nlabel: Code\nseeded_from: agentic-engineering\n---\nSmall functions.\n")
    found = seeds.load(CONFIG, tmp_path)
    assert found["code"] == Seed("code", "Code", "agentic-engineering", "Small functions.")
    (tmp_path / "writing.md").write_text("---\nkind: writing\nlabel: Writing\nseeded_from: \n---\nbody\n")
    with pytest.raises(ValueError):
        seeds.load(CONFIG, tmp_path)
    assert seeds.load(CONFIG, tmp_path / "missing") == {}
