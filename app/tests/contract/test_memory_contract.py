"""Blind contract tests for the memory page, written from `ashley.api.memory`'s docstrings, `openapi.json`, the `Memory`
interface and `decisions.md` ("People see, correct and forget what she knows of them", "People sign in through
OIDC") without reading the implementation. Each test names the clause it checks. A, B share a household; C has
another."""

from collections.abc import Generator
from typing import Any

import psycopg
import pytest
from conversations_support import events, scalar
from memory_contract_support import Cast, household_cast, plant, rows, supersede, talk, new_fact

LEAK = "ZEBRA-TURN-MARKER"


@pytest.fixture
def world(db_url: str) -> Generator[Cast]:
    with household_cast(db_url) as c:
        yield c


class Planted:
    """The facts every listing test reads, one id per name."""

    def __init__(self, w: Cast) -> None:
        u, h, a, b, c = w.url, w.hh["home"], w.who["A"], w.who["B"], w.who["C"]
        self.conv_a = talk(u, h, a, f"{LEAK} A says things", "ok")
        self.conv_b = talk(u, h, b, f"{LEAK} B says things", "ok")
        conv_c = talk(u, w.hh["other"], c, f"{LEAK} C says things", "ok")
        self.a_private = plant(u, h, self.conv_a, new_fact(a, a, "A private about A", "private"))
        self.b_private_about_a = plant(u, h, self.conv_b, new_fact(a, b, "B private about A surprise", "private"))
        self.b_private = plant(u, h, self.conv_b, new_fact(b, b, "B private about B", "private"))
        self.b_shared_about_a = plant(u, h, self.conv_b, new_fact(a, b, "B shared about A", "shared"))
        self.b_shared_about_b = plant(u, h, self.conv_b, new_fact(b, b, "B shared about B", "shared"))
        self.household = plant(u, h, self.conv_a, new_fact(None, None, "the house has a cat"))
        self.c_household = plant(u, w.hh["other"], conv_c, new_fact(None, None, "C house fact"))
        self.c_private = plant(u, w.hh["other"], conv_c, new_fact(c, c, "C private", "private"))


@pytest.fixture
def p(world: Cast) -> Planted:
    return Planted(world)


# --- listing ----------------------------------------------------------------------------------------------------


def test_listing_requires_a_session(world: Cast) -> None:
    """401 `unauthorized`: no live session."""
    r = world.get(None)
    assert r.status_code == 401


def test_listing_is_what_concerns_the_reader(world: Cast, p: Planted) -> None:
    """A sees facts about A, owned by A, and household facts."""
    assert world.ids("A") == {p.a_private, p.b_shared_about_a, p.household}


def test_listing_never_shows_anothers_private_fact_even_about_the_reader(world: Cast, p: Planted) -> None:
    """Never another person's private fact, even one about the reader (a surprise party)."""
    seen = world.ids("A")
    assert p.b_private_about_a not in seen and p.b_private not in seen
    assert p.b_private_about_a in world.ids("B")


def test_listing_does_not_show_facts_that_concern_only_someone_else(world: Cast, p: Planted) -> None:
    """Only facts about, owned by, or of the household of the reader."""
    assert p.b_shared_about_b not in world.ids("A")
    assert p.b_shared_about_b in world.ids("B")


def test_listing_never_crosses_households(world: Cast, p: Planted) -> None:
    """Nothing crosses households."""
    assert world.ids("C") == {p.c_household, p.c_private}
    assert not world.ids("A") & {p.c_household, p.c_private}


def test_listing_is_newest_first(world: Cast, p: Planted) -> None:
    """Newest `valid_from` first."""
    stamps = [f["valid_from"] for f in world.listed("A")]
    assert len(stamps) == 3 and stamps == sorted(stamps, reverse=True)


def test_listed_fact_carries_the_documented_fields(world: Cast, p: Planted) -> None:
    """MemoryFact: text, kind, standing, visibility, about/owner (null for a household fact), source."""
    by_id = {f["id"]: f for f in world.listed("A")}
    own, house = by_id[p.a_private], by_id[p.household]
    a = world.who["A"]
    assert own["text"] == "A private about A" and own["visibility"] == "private"
    assert own["about"]["id"] == a and own["owner"]["id"] == a
    assert house["about"] is None and house["owner"] is None and house["visibility"] == "shared"
    assert own["replaced"] is None


def test_listed_source_says_kind_start_and_whether_the_reader_took_part(world: Cast, p: Planted) -> None:
    """FactSource: conversation kind and start, `took_part` is whether the reader was in that conversation."""
    by_id = {f["id"]: f for f in world.listed("A")}
    mine, theirs = by_id[p.a_private]["source"], by_id[p.b_shared_about_a]["source"]
    assert mine["conversation_id"] == p.conv_a and mine["took_part"] is True
    assert theirs["conversation_id"] == p.conv_b and theirs["took_part"] is False
    assert mine["conversation_kind"] == "chat"
    started = scalar(world.url, "SELECT started_at FROM conversations WHERE id = %s", (p.conv_a,))
    assert mine["started_at"].startswith(started.astimezone(started.tzinfo).strftime("%Y-%m-%dT%H:%M:%S"))


def test_listing_never_carries_turn_text(world: Cast, p: Planted) -> None:
    """Where a fact was learned is its conversation's kind and start, and no turn text."""
    for name in ("A", "B", "C"):
        assert LEAK not in world.get(name).text


def test_replaced_fact_shows_old_text_and_valid_to(world: Cast, p: Planted) -> None:
    """`replaced` is the fact this one superseded: what it said, and when it stopped being true."""
    new = supersede(world.url, world.hh["home"], p.conv_a, p.household, new_fact(None, None, "the house has two cats"))
    fact = {f["id"]: f for f in world.listed("A")}[new]
    assert p.household not in world.ids("A")
    assert fact["replaced"]["text"] == "the house has a cat"
    closed = scalar(world.url, "SELECT valid_to FROM facts WHERE id = %s", (p.household,))
    assert fact["replaced"]["valid_to"].startswith(closed.strftime("%Y-%m-%dT%H:%M:%S"))


def test_replaced_fact_is_hidden_when_the_reader_may_not_see_it(world: Cast, p: Planted) -> None:
    """The fact a correction replaced shows only when the reader may see it too."""
    new = supersede(world.url, world.hh["home"], p.conv_b, p.b_private_about_a,
                    new_fact(world.who["A"], world.who["B"], "B party is on Friday", "shared"))
    fact = {f["id"]: f for f in world.listed("A")}[new]
    assert fact["replaced"] is None


# --- correcting -------------------------------------------------------------------------------------------------


def test_correcting_requires_a_session(world: Cast, p: Planted) -> None:
    """401 `unauthorized`."""
    assert world.correct(None, p.household).status_code == 401
    assert rows(world.url, [p.household])[0][2] is True


def test_correction_supersedes_and_never_edits_in_place(world: Cast, p: Planted) -> None:
    """201 with the fact that replaces; the old fact is closed and kept, its text untouched, linked to the new."""
    r = world.correct("A", p.a_private, {"text": "A corrected private"})
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["id"] != p.a_private and new["text"] == "A corrected private"
    assert new["replaced"]["text"] == "A private about A"
    old = rows(world.url, [p.a_private])[0]
    assert old[1] == "A private about A" and old[2] is False and old[3] == new["id"]
    ids = world.ids("A")
    assert p.a_private not in ids and new["id"] in ids
    shown = {f["id"]: f for f in world.listed("A")}[new["id"]]
    assert shown["replaced"]["text"] == "A private about A"


def test_correction_carries_kind_subject_owner_and_visibility(world: Cast, p: Planted) -> None:
    """Kind, who it is about and whose it is carry over; visibility carries over as stated."""
    new = world.correct("A", p.a_private, {"text": "A again"}).json()
    assert (new["kind"], new["visibility"]) == ("other", "private")
    assert new["about"]["id"] == world.who["A"] and new["owner"]["id"] == world.who["A"]


def test_correction_source_is_a_new_web_conversation_the_corrector_took_part_in(world: Cast, p: Planted) -> None:
    """A correction made on the web is a `command` conversation of its own, with the reader taking part."""
    src = world.correct("A", p.a_private).json()["source"]
    assert src["conversation_id"] not in (p.conv_a, p.conv_b)
    assert src["conversation_kind"] == "command" and src["took_part"] is True


def test_correction_conversation_holds_the_typed_text_as_one_person_turn(world: Cast, p: Planted) -> None:
    """It opens a conversation with them as participant and one person turn, the text they typed."""
    cid = world.correct("A", p.a_private, {"text": "typed words"}).json()["source"]["conversation_id"]
    with psycopg.connect(world.url) as conn:
        turns = conn.execute("SELECT author, text, speaker_id FROM turns WHERE conversation_id = %s", (cid,)).fetchall()
        who = conn.execute("SELECT person_id FROM conversation_participants WHERE conversation_id = %s", (cid,)).fetchall()
    assert turns == [("person", "typed words", world.who["A"])] and who == [(world.who["A"],)]


def test_correcting_someone_elses_private_fact_is_404_not_403(world: Cast, p: Planted) -> None:
    """Any fact outside the reader's set is 404, the answer for a fact that does not exist."""
    for fact in (p.a_private, p.b_private):
        r = world.correct("B" if fact == p.a_private else "A", fact)
        assert r.status_code == 404, (fact, r.status_code)
    assert world.correct("B", 999_999).status_code == 404
    assert rows(world.url, [p.a_private, p.b_private]) == [
        (p.a_private, "A private about A", True, None), (p.b_private, "B private about B", True, None)]


def test_correcting_a_private_fact_about_you_that_is_not_yours_is_404(world: Cast, p: Planted) -> None:
    """A's set excludes B's private fact about A, so it is 404 to every route."""
    assert world.correct("A", p.b_private_about_a).status_code == 404


def test_correcting_another_households_fact_is_404(world: Cast, p: Planted) -> None:
    """Nothing crosses households."""
    assert world.correct("C", p.household).status_code == 404
    assert world.correct("A", p.c_household).status_code == 404


def test_visibility_change_by_a_non_owner_is_403(world: Cast, p: Planted) -> None:
    """Only the fact's owner may change its visibility (403 otherwise)."""
    r = world.correct("A", p.b_shared_about_a, {"text": "x", "visibility": "private"})
    assert r.status_code == 403, r.text
    assert rows(world.url, [p.b_shared_about_a])[0][2] is True
    assert world.correct("B", p.b_shared_about_a, {"text": "x", "visibility": "private"}).status_code == 201


def test_non_owner_may_correct_text_of_a_fact_about_them(world: Cast, p: Planted) -> None:
    """The set is what they may see, correct and forget; the visibility carries over."""
    r = world.correct("A", p.b_shared_about_a, {"text": "B shared, fixed by A"})
    assert r.status_code == 201 and r.json()["visibility"] == "shared"
    assert r.json()["owner"]["id"] == world.who["B"]


def test_household_fact_is_correctable_by_any_household_member(world: Cast, p: Planted) -> None:
    """Any signed-in person of the household may correct a household fact."""
    first = world.correct("B", p.household, {"text": "two cats"})
    assert first.status_code == 201 and first.json()["about"] is None and first.json()["owner"] is None
    second = world.correct("A", first.json()["id"], {"text": "three cats"})
    assert second.status_code == 201
    assert world.ids("B") >= {second.json()["id"]} and first.json()["id"] not in world.ids("B")


@pytest.mark.parametrize("body", [{}, {"text": ""}, {"text": "   "}, {"text": "x" * 1001}, {"text": "ok", "extra": 1},
                                  {"text": "ok", "visibility": "public"}])
def test_correction_body_outside_the_model_is_422_and_changes_nothing(world: Cast, p: Planted, body: dict[str, Any]) -> None:
    """422: FastAPI's validation error for a body outside `CorrectionRequest`."""
    before = rows(world.url)
    assert world.correct("A", p.a_private, body).status_code == 422
    assert rows(world.url) == before


def test_correction_with_a_fact_id_below_one_is_422(world: Cast, p: Planted) -> None:
    assert world.correct("A", 0).status_code == 422


# --- origin rules -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("headers", [{"Origin": "https://evil.test"}, {"Sec-Fetch-Site": "cross-site"}])
def test_cross_site_write_is_refused_403(world: Cast, p: Planted, headers: dict[str, str]) -> None:
    """A write must come from `PUBLIC_URL`'s origin: a mismatched Origin, or with no Origin a Sec-Fetch-Site naming
    another site, is 403 `forbidden` and changes nothing."""
    before = rows(world.url)
    assert world.correct("A", p.a_private, headers=headers).status_code == 403
    assert world.forget("A", p.a_private, headers=headers).status_code == 403
    assert rows(world.url) == before


def test_write_with_a_matching_origin_or_same_site_fetch_metadata_is_accepted(world: Cast, p: Planted) -> None:
    """The control for the refusals above: the right origin passes, and so does no Origin with a same-origin hint."""
    assert world.correct("A", p.a_private, headers={"Sec-Fetch-Site": "same-origin"}).status_code == 201


def test_write_that_is_not_json_is_refused_403(world: Cast, p: Planted) -> None:
    """Any body must be `application/json`."""
    r = world.as_("A").client.post(f"/api/memory/facts/{p.a_private}/corrections", content='{"text":"x"}',
                                   headers={"Origin": "https://ashley.test", "Content-Type": "text/plain"})
    assert r.status_code == 403
    assert rows(world.url, [p.a_private])[0][2] is True


# --- forgetting -------------------------------------------------------------------------------------------------


def chain(w: Cast, p: Planted) -> tuple[int, int, int]:
    h, a = w.hh["home"], w.who["A"]
    first = plant(w.url, h, p.conv_a, new_fact(a, a, "chain one", "private"))
    second = supersede(w.url, h, p.conv_a, first, new_fact(a, a, "chain two", "private"))
    third = supersede(w.url, h, p.conv_a, second, new_fact(a, a, "chain three", "private"))
    return first, second, third


def test_forgetting_requires_a_session(world: Cast, p: Planted) -> None:
    assert world.forget(None, p.a_private).status_code == 401
    assert rows(world.url, [p.a_private])


def test_forgetting_the_newest_deletes_the_whole_chain_and_nothing_else(world: Cast, p: Planted) -> None:
    """A hard delete of the fact and every version it replaced; None is kept. 200 `ForgetResponse.deleted`."""
    first, second, third = chain(world, p)
    others = [r for r in rows(world.url) if r[0] not in (first, second, third)]
    r = world.forget("A", third)
    assert r.status_code == 200 and r.json() == {"deleted": 3}
    assert rows(world.url, [first, second, third]) == []
    assert [r for r in rows(world.url)] == others
    assert third not in world.ids("A")


def test_forgetting_a_single_fact_deletes_one(world: Cast, p: Planted) -> None:
    r = world.forget("A", p.a_private)
    assert r.status_code == 200 and r.json() == {"deleted": 1}
    assert rows(world.url, [p.a_private]) == []


def test_forgetting_an_old_version_is_404(world: Cast, p: Planted) -> None:
    """Only a current fact of yours can be forgotten; a superseded one is not in the set."""
    first, second, third = chain(world, p)
    assert world.forget("A", first).status_code == 404
    assert world.forget("A", second).status_code == 404
    assert len(rows(world.url, [first, second, third])) == 3


def test_forgetting_someone_elses_private_fact_is_404(world: Cast, p: Planted) -> None:
    """Outside the reader's set, even when it is about them."""
    for fact in (p.b_private, p.b_private_about_a):
        assert world.forget("A", fact).status_code == 404
    assert world.forget("B", p.a_private).status_code == 404
    assert len(rows(world.url, [p.b_private, p.b_private_about_a, p.a_private])) == 3


def test_another_household_forgetting_a_household_fact_is_404(world: Cast, p: Planted) -> None:
    assert world.forget("C", p.household).status_code == 404
    assert world.forget("A", p.c_household).status_code == 404
    assert len(rows(world.url, [p.household, p.c_household])) == 2


def test_household_fact_can_be_forgotten_by_any_member(world: Cast, p: Planted) -> None:
    assert world.forget("B", p.household).json() == {"deleted": 1}
    assert rows(world.url, [p.household]) == []


def test_forgotten_fact_cannot_be_corrected_or_forgotten_again(world: Cast, p: Planted) -> None:
    """A forgotten fact is 404 to every route, as one that never existed."""
    assert world.forget("A", p.a_private).status_code == 200
    assert world.correct("A", p.a_private).status_code == 404
    assert world.forget("A", p.a_private).status_code == 404
    assert rows(world.url, [p.a_private]) == []


# --- logs -------------------------------------------------------------------------------------------------------


def test_forgetting_logs_a_count_and_person_never_fact_text(world: Cast, p: Planted, capfd: pytest.CaptureFixture[str]) -> None:
    """One `memory.forgotten` line carries the household, `by` and the count, never text."""
    third = chain(world, p)[2]
    capfd.readouterr()
    assert world.forget("A", third).status_code == 200
    out = capfd.readouterr()
    text = out.out + out.err
    lines = events(text, "memory.forgotten")
    assert len(lines) == 1, text
    assert lines[0]["by"] == str(world.who["A"]) and "3" in lines[0].values()
    assert all(t not in text for t in ("chain one", "chain two", "chain three"))


def test_a_refused_forget_logs_no_forgotten_line(world: Cast, p: Planted, capfd: pytest.CaptureFixture[str]) -> None:
    capfd.readouterr()
    assert world.forget("A", p.b_private).status_code == 404
    out = capfd.readouterr()
    assert events(out.out + out.err, "memory.forgotten") == []
