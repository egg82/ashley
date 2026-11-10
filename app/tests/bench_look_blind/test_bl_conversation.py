"""Looks under her answers: a look is recorded against the person turn that asked and shown under her final answer to
that turn, on the web thread and on a bench's talk, with a picture link that fetches its bytes."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from ashley import services
from ashley.files import config as files_config
from ashley.looks import links
from ashley.looks.keys import key_of
from ashley.looks.looks import Looks, NullLooks
from bench_look_blind_support import (LINK_KEY, SHOT_BYTES, FailingLooks, Rig, fields_of, go, new_look, rig, scene,
                                      sha)

LINK_TTL_S = files_config.load().link_ttl_s
KEY = LINK_KEY.encode()


@dataclass(frozen=True)
class Surface:
    name: str
    thread: Callable[[Rig], str]
    path: Callable[[int], str]


WEB = Surface("web", lambda r: f"person:{r.w.alana.person_id}:web", lambda bench: "/api/chat/conversation")
TALK = Surface("talk", lambda r: "", lambda bench: f"/api/benches/{bench}/conversation")
SURFACES = [WEB, TALK]


def read(r: Rig, surface: Surface, bench: int) -> list[dict[str, Any]]:
    got = r.client.get(surface.path(bench))
    assert got.status_code == 200, got.text
    turns: list[dict[str, Any]] = got.json()["turns"]
    return turns


def talk(r: Rig, surface: Surface, bench: int) -> str:
    return surface.thread(r) or f"bench:{bench}"


async def seed(r: Rig, surface: Surface, bench: int, *, looks_for: tuple[str, ...] = ("a",), final: bool = True,
               held: bool = False, owner_name: str = "alana") -> tuple[int, int, int | None]:
    """A person turn with `looks_for` calls' looks, optionally a held line, optionally a final answer. Ids of the person
    turn, the final answer (or None)."""
    owner = {"alana": r.w.alana, "sam": r.w.sam, "zed": r.w.zed}[owner_name]
    async with scene(r.url, register=False) as s:
        conv, turn = await s.asked(owner, thread=talk(r, surface, bench))
        for i, c in enumerate(looks_for):
            await s.looks.keep(new_look(owner, conv, turn.id, c, bench=bench, data=SHOT_BYTES + bytes([i]), piece=None))
        if held:
            await s.answer(conv, turn, "one moment", follows=True)
        answer = await s.answer(conv, turn) if final else None
        return conv, turn.id, answer.id if answer else None


def by_id(turns: list[dict[str, Any]], turn_id: int | None) -> dict[str, Any]:
    (found,) = [t for t in turns if t["id"] == turn_id]
    return found


@pytest.mark.parametrize("surface", SURFACES, ids=lambda s: s.name)
def test_looks_are_under_her_final_answer_not_the_question(db_url: str, surface: Surface) -> None:
    with rig(db_url) as r:
        bench = r.new_bench()
        _, asked, answer = go(seed(r, surface, bench))
        turns = read(r, surface, bench)
        assert len(by_id(turns, answer)["looks"]) == 1
        assert by_id(turns, asked)["looks"] == []


@pytest.mark.parametrize("surface", SURFACES, ids=lambda s: s.name)
def test_a_held_line_before_the_answer_shows_no_looks(db_url: str, surface: Surface) -> None:
    with rig(db_url) as r:
        bench = r.new_bench()
        _, _, answer = go(seed(r, surface, bench, held=True))
        turns = read(r, surface, bench)
        held = [t for t in turns if t["author"] == "ashley" and t["id"] != answer]
        assert held and all(t["looks"] == [] for t in held)
        assert len(by_id(turns, answer)["looks"]) == 1


@pytest.mark.parametrize("surface", SURFACES, ids=lambda s: s.name)
def test_a_look_waits_for_its_answer(db_url: str, surface: Surface) -> None:
    with rig(db_url) as r:
        bench = r.new_bench()
        go(seed(r, surface, bench, final=False, held=True))
        assert all(t["looks"] == [] for t in read(r, surface, bench))


@pytest.mark.parametrize("surface", SURFACES, ids=lambda s: s.name)
def test_a_look_has_its_bench_piece_type_and_a_link_that_fetches_its_bytes(db_url: str, surface: Surface) -> None:
    with rig(db_url) as r:
        bench = r.new_bench()
        _, _, answer = go(seed(r, surface, bench))
        (look,) = by_id(read(r, surface, bench), answer)["looks"]
        assert (look["bench_id"], look["piece_id"], look["media_type"]) == (bench, None, "image/jpeg")
        r.store.held[key_of(r.w.alana.household_id, sha(SHOT_BYTES + b"\x00"))] = SHOT_BYTES + b"\x00"
        got = r.client.get(look["url"])
        assert got.status_code == 200 and got.content == SHOT_BYTES + b"\x00"


@pytest.mark.parametrize("surface", SURFACES, ids=lambda s: s.name)
def test_the_link_lives_between_half_and_all_of_the_link_ttl(db_url: str, surface: Surface) -> None:
    with rig(db_url) as r:
        bench = r.new_bench()
        _, _, answer = go(seed(r, surface, bench))
        before = time.time()
        (look,) = by_id(read(r, surface, bench), answer)["looks"]
        after = time.time()
        assert before + LINK_TTL_S / 2 - 1 <= look["expires_at"] <= after + LINK_TTL_S + 1
        token = look["url"].rsplit("/", 1)[-1]
        picture = links.check_picture(KEY, token, time.time())
        assert picture is not None and picture.expires_at == look["expires_at"]
        assert (picture.household_id, picture.media_type) == (r.w.alana.household_id, "image/jpeg")


@pytest.mark.parametrize("surface", SURFACES, ids=lambda s: s.name)
def test_several_looks_come_in_the_order_she_took_them(db_url: str, surface: Surface) -> None:
    with rig(db_url) as r:
        bench = r.new_bench()
        _, _, answer = go(seed(r, surface, bench, looks_for=("z", "m", "a")))
        looks = by_id(read(r, surface, bench), answer)["looks"]
        assert [look["id"] for look in looks] == sorted(look["id"] for look in looks) and len(looks) == 3


def test_each_answer_shows_the_looks_of_its_own_question(db_url: str) -> None:
    with rig(db_url) as r:
        bench = r.new_bench()
        async def two() -> tuple[int, int]:
            async with scene(r.url, register=False) as s:
                conv, first = await s.asked(r.w.alana)
                await s.looks.keep(new_look(r.w.alana, conv, first.id, "a", data=b"1"))
                one = await s.answer(conv, first)
                _, second = await s.asked(r.w.alana, "again")
                await s.looks.keep(new_look(r.w.alana, conv, second.id, "a", data=b"2"))
                await s.looks.keep(new_look(r.w.alana, conv, second.id, "b", data=b"3"))
                two = await s.answer(conv, second)
                return one.id, two.id

        one, two_ = go(two())
        turns = read(r, WEB, bench)
        assert len(by_id(turns, one)["looks"]) == 1 and len(by_id(turns, two_)["looks"]) == 2


def test_a_conversation_with_no_looks_has_empty_lists(db_url: str) -> None:
    with rig(db_url) as r:
        async def plain() -> None:
            async with scene(r.url, register=False) as s:
                conv, turn = await s.asked(r.w.alana)
                await s.answer(conv, turn)

        go(plain())
        turns = read(r, WEB, 0)
        assert turns and all(t["looks"] == [] for t in turns)


def test_an_unreadable_record_does_not_fail_the_conversation(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    with rig(db_url) as r:
        bench = r.new_bench()
        _, asked, answer = go(seed(r, WEB, bench))
        services.register(Looks, FailingLooks(NullLooks(), frozenset({"in_conversation"})))
        with caplog.at_level(logging.DEBUG):
            turns = read(r, WEB, bench)
        assert {t["id"] for t in turns} >= {asked, answer}
        assert all(t["looks"] == [] for t in turns)
        assert fields_of(caplog, "chat.looks_unavailable")


def test_another_households_conversation_shows_none_of_these_looks(db_url: str) -> None:
    with rig(db_url) as r:
        bench = r.new_bench()
        go(seed(r, WEB, bench))
        r.as_("zed")
        turns = read(r, WEB, bench)
        assert all(t["looks"] == [] for t in turns)


def test_another_person_does_not_read_a_look_off_a_conversation_that_is_not_theirs(db_url: str) -> None:
    with rig(db_url) as r:
        bench = r.new_bench()
        go(seed(r, WEB, bench))
        r.as_("sam")
        assert all(t["looks"] == [] for t in read(r, WEB, bench))


def test_a_link_for_one_household_does_not_fetch_a_look_of_another(db_url: str) -> None:
    with rig(db_url) as r:
        bench = r.new_bench()
        _, _, answer = go(seed(r, WEB, bench))
        (look,) = by_id(read(r, WEB, bench), answer)["looks"]
        r.store.held[key_of(r.w.alana.household_id, sha(SHOT_BYTES + b"\x00"))] = SHOT_BYTES + b"\x00"
        mine = links.check_picture(KEY, look["url"].rsplit("/", 1)[-1], time.time())
        assert mine is not None
        theirs = links.mint_picture(KEY, links.Picture(r.w.zed.household_id, mine.sha256, mine.media_type, mine.expires_at))
        assert r.client.get(f"/api/looks/{theirs}").status_code == 404
