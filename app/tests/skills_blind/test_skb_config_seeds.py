"""The skills config (`skills.json`) and the seed documents, from their documented shapes."""

import json
import re
from collections.abc import MutableMapping
from pathlib import Path

import pytest

from ashley.skills import config as skills_config
from ashley.skills import seeds
from ashley.skills.config import SkillsConfig, config_from

RAW: dict[str, object] = {"slug_pattern": "^[a-z0-9][a-z0-9-]*$", "max_slug_chars": 10, "max_label_chars": 8,
                          "max_body_chars": 50, "max_note_chars": 5, "changelog_read": 3}


def small() -> SkillsConfig:
    return config_from(RAW)


def seed_text(kind: str = "code", label: str = "Code", source: str = "src", body: str = "BODY") -> str:
    return f"---\nkind: {kind}\nlabel: {label}\nseeded_from: {source}\n---\n{body}"


# --- config ------------------------------------------------------------------------------------------------------


def test_config_from_reads_each_limit() -> None:
    c = small()
    assert (c.max_slug_chars, c.max_label_chars, c.max_body_chars, c.max_note_chars, c.changelog_read) == (10, 8, 50, 5, 3)
    assert c.slug_pattern == re.compile(str(RAW["slug_pattern"]))


def test_each_key_is_read_into_its_own_field() -> None:
    raw = {**RAW, "max_slug_chars": 11, "max_label_chars": 22, "max_body_chars": 33, "max_note_chars": 44,
           "changelog_read": 55}
    c = config_from(raw)
    assert (c.max_slug_chars, c.max_label_chars, c.max_body_chars, c.max_note_chars, c.changelog_read) == (
        11, 22, 33, 44, 55)


@pytest.mark.parametrize("missing", sorted(RAW))
def test_a_missing_key_is_refused(missing: str) -> None:
    with pytest.raises(ValueError):
        config_from({k: v for k, v in RAW.items() if k != missing})


def test_an_extra_key_is_refused() -> None:
    with pytest.raises(ValueError):
        config_from({**RAW, "kinds": ["code"]})


@pytest.mark.parametrize("raw", [None, [], "x", 3, [RAW]])
def test_a_config_that_is_not_an_object_is_refused(raw: object) -> None:
    with pytest.raises(ValueError):
        config_from(raw)


@pytest.mark.parametrize("key", ["max_slug_chars", "max_label_chars", "max_body_chars", "max_note_chars", "changelog_read"])
@pytest.mark.parametrize("bad", [0, -1, 1.5, 2.0, "3", True, None, [3]])
def test_a_limit_that_is_not_an_integer_of_at_least_one_is_refused(key: str, bad: object) -> None:
    with pytest.raises(ValueError):
        config_from({**RAW, key: bad})


@pytest.mark.parametrize("key", ["max_slug_chars", "max_label_chars", "max_body_chars", "max_note_chars", "changelog_read"])
def test_a_limit_of_exactly_one_is_accepted(key: str) -> None:
    assert config_from({**RAW, key: 1}) is not None


@pytest.mark.parametrize("bad", [None, 5, ["^a$"], True])
def test_a_pattern_that_is_not_a_string_is_refused(bad: object) -> None:
    with pytest.raises(ValueError):
        config_from({**RAW, "slug_pattern": bad})


def test_slug_ok_checks_the_whole_name_against_the_pattern_and_the_length() -> None:
    c = small()
    assert c.slug_ok("code") and c.slug_ok("7-up") and c.slug_ok("a" * 10)
    assert not c.slug_ok("a" * 11)
    for bad in ("", "Code", "-a", "a b", "a_b", "a\n", "ab!", "!ab"):
        assert not c.slug_ok(bad), bad


def test_slug_ok_matches_the_whole_name_not_a_prefix() -> None:
    c = config_from({**RAW, "slug_pattern": "[a-z]+"})
    assert c.slug_ok("abc") and not c.slug_ok("abc1") and not c.slug_ok("1abc")


def test_label_ok() -> None:
    c = small()
    assert c.label_ok("Code") and c.label_ok("x" * 8) and c.label_ok("a b")
    assert not c.label_ok("x" * 9)
    for bad in ("", " ", "\t\n", "a\x00"):
        assert not c.label_ok(bad), repr(bad)


def test_the_shipped_config_loads_and_accepts_the_kinds_the_decisions_name() -> None:
    c = skills_config.load()
    for kind in ("code", "3d", "research", "writing", "electronics", "garden-planning"):
        assert c.slug_ok(kind), kind
    assert not c.slug_ok("Not A Slug")
    shipped = json.loads(skills_config.FILE.read_text())
    assert c.max_body_chars == shipped["max_body_chars"] and c.changelog_read == shipped["changelog_read"]


# --- seeds -------------------------------------------------------------------------------------------------------


def test_parse_reads_a_seed() -> None:
    got = seeds.parse(seed_text(), small(), "code.md")
    assert (got.kind, got.label, got.seeded_from, got.body) == ("code", "Code", "src", "BODY")


def test_parse_keeps_a_multi_line_body_and_trims_its_ends() -> None:
    got = seeds.parse(seed_text(body="\n\nline one\n\n- two\n\n"), small(), "code.md")
    assert got.body == "line one\n\n- two"


def test_parse_keeps_colons_in_a_value() -> None:
    got = seeds.parse(seed_text(label="A: B", source="x: y"), small(), "code.md")
    assert (got.label, got.seeded_from) == ("A: B", "x: y")


@pytest.mark.parametrize("text", [
    "no front matter\nat all\nhere\nreally\nnot\nthere",
    "---\nkind: code\nlabel: Code\nseeded_from: s\nBODY\nmore",
    "---\nkind: code\nlabel: Code\nseeded_from: s\n---",
    "---\nkind: code\nlabel: Code\n---\nBODY\nmore\nlines",
    "---\nkind: code\nlabel: Code\nseeded_from: s\nextra: x\n---\nBODY",
    "---\nlabel: Code\nkind: code\nseeded_from: s\n---\nBODY",
    "---\nkind: code\nkind: code\nseeded_from: s\n---\nBODY",
    "---\nkind: code\nlabel Code\nseeded_from: s\n---\nBODY",
    "---\nkind: code\nlabel: Code\nsource: s\n---\nBODY",
    "",
])
def test_parse_refuses_a_malformed_front_matter(text: str) -> None:
    with pytest.raises(ValueError):
        seeds.parse(text, small(), "code.md")


@pytest.mark.parametrize("kind", ["Code", "has space", "-x", "", "k" * 11])
def test_parse_refuses_a_kind_that_is_not_a_slug(kind: str) -> None:
    with pytest.raises(ValueError):
        seeds.parse(seed_text(kind=kind), small(), f"{kind}.md")


def test_parse_refuses_a_kind_that_is_not_the_files_name() -> None:
    with pytest.raises(ValueError):
        seeds.parse(seed_text(kind="code"), small(), "other.md")
    with pytest.raises(ValueError):
        seeds.parse(seed_text(kind="code"), small(), "code.txt")


@pytest.mark.parametrize("label", ["", " ", "L" * 9])
def test_parse_refuses_a_bad_label(label: str) -> None:
    with pytest.raises(ValueError):
        seeds.parse(seed_text(label=label), small(), "code.md")


def test_parse_refuses_an_empty_seeded_from() -> None:
    with pytest.raises(ValueError):
        seeds.parse(seed_text(source=""), small(), "code.md")
    with pytest.raises(ValueError):
        seeds.parse(seed_text(source="   "), small(), "code.md")


def test_parse_refuses_an_empty_or_over_long_body_and_accepts_the_limit() -> None:
    for body in ("", "  \n ", "x" * 51):
        with pytest.raises(ValueError):
            seeds.parse(seed_text(body=body), small(), "code.md")
    assert seeds.parse(seed_text(body="x" * 50), small(), "code.md").body == "x" * 50


def test_the_error_names_the_file() -> None:
    with pytest.raises(ValueError, match=r"code\.md"):
        seeds.parse(seed_text(source=""), small(), "code.md")


def test_load_reads_every_seed_by_kind(tmp_path: Path) -> None:
    (tmp_path / "code.md").write_text(seed_text())
    (tmp_path / "3d.md").write_text(seed_text(kind="3d", label="3D", body="THREE"))
    got = seeds.load(small(), tmp_path)
    assert sorted(got) == ["3d", "code"]
    assert got["3d"].body == "THREE" and got["code"].label == "Code"


def test_load_of_an_absent_or_empty_directory_is_no_seeds(tmp_path: Path) -> None:
    assert dict(seeds.load(small(), tmp_path / "nope")) == {}
    assert dict(seeds.load(small(), tmp_path)) == {}


def test_load_skips_dotfiles(tmp_path: Path) -> None:
    (tmp_path / ".keep").write_text("not a seed")
    (tmp_path / "code.md").write_text(seed_text())
    assert sorted(seeds.load(small(), tmp_path)) == ["code"]


def test_load_refuses_a_bad_file_naming_it(tmp_path: Path) -> None:
    (tmp_path / "code.md").write_text(seed_text())
    (tmp_path / "bad.md").write_text("junk")
    with pytest.raises(ValueError, match=r"bad\.md"):
        seeds.load(small(), tmp_path)


def test_load_refuses_a_file_that_is_not_kind_dot_md(tmp_path: Path) -> None:
    (tmp_path / "code.txt").write_text(seed_text())
    with pytest.raises(ValueError):
        seeds.load(small(), tmp_path)


def test_the_loaded_seeds_are_not_a_mutable_mapping(tmp_path: Path) -> None:
    (tmp_path / "code.md").write_text(seed_text())
    assert not isinstance(seeds.load(small(), tmp_path), MutableMapping)


def test_the_seeds_that_ship_all_parse_under_the_shipped_config() -> None:
    got = seeds.load(skills_config.load())
    for kind, seed in got.items():
        assert seed.kind == kind and seed.body and seed.seeded_from
