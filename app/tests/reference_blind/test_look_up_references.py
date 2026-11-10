"""`look_up`'s `references`: each is `{result, what, site}` for a result of this turn, the numbers continue across the
turn's look-ups, and nothing in the reply is a URL, however the result's URL is built. The inner search source records
into `results.current()` as `search_web` does."""

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import pytest
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools.look_up import LookedUp, Reference
from ashley.tools.results import Results, bound, current
from contract.look_up_contract_support import Brain, Sources, ask, look_up, reply

PATH_MARK = "zq-path-7731"
QUERY_MARK = "zqquery8842"
URLS = [f"https://www.example.org/watch/{PATH_MARK}?v={QUERY_MARK}#t=5", f"https://cdn.example.net:8443/{PATH_MARK}.mp4"]


@dataclass
class Searching(Sources):
    """`search_web` numbers each of `found` into the turn's store, as the real one does, and says nothing of the URLs."""

    found: tuple[str, ...] = ()

    async def call(self, call: ToolCall) -> ToolResult:
        if call.name == "search_web":
            for url in self.found:
                current().record(url)
        return await super().call(call)


def refs(*numbers: int) -> list[Reference]:
    return [Reference(result=n, what=f"thing {n}") for n in numbers]


def done(*numbers: int) -> LookedUp:
    return LookedUp(found=True, answer="It is the one you wanted.", sources=["example.org"], references=refs(*numbers))


def run(found: tuple[str, ...], *numbers: int) -> dict[str, Any]:
    brain = Brain([ask("search_web"), done(*numbers)])
    return reply(look_up(brain, sources=Searching(found=found)))


def test_a_reference_is_its_number_what_and_the_site() -> None:
    with bound(Results()):
        got = run(("https://www.example.org/a", "https://cdn.example.net/b.mp4"), 2, 1)
    assert got["references"] == [{"result": 2, "what": "thing 2", "site": "cdn.example.net"},
                                 {"result": 1, "what": "thing 1", "site": "www.example.org"}]


def test_the_numbers_are_the_turns_so_the_bench_tools_can_use_them() -> None:
    turn = Results()
    with bound(turn):
        run((URLS[0],), 1)
    assert turn.url(1) == URLS[0]


def test_numbers_continue_across_look_ups_of_one_turn() -> None:
    turn = Results()
    with bound(turn):
        first = run(("https://one.example.org/a", "https://one.example.org/b"), 2)
        second = run(("https://two.example.org/a",), 3)
    assert first["references"][0]["site"] == "one.example.org"
    assert second["references"] == [{"result": 3, "what": "thing 3", "site": "two.example.org"}]
    assert turn.url(3) == "https://two.example.org/a"


def test_a_second_turn_starts_again_from_one() -> None:
    a, b = Results(), Results()
    with bound(a):
        run(("https://one.example.org/a",), 1)
    with bound(b):
        got = run(("https://two.example.org/a",), 1)
    assert got["references"][0]["site"] == "two.example.org"
    assert b.url(1) == "https://two.example.org/a"


@pytest.mark.parametrize("url", URLS)
def test_the_reply_never_carries_a_url_or_any_part_of_one(url: str) -> None:
    with bound(Results()):
        out = run((url,), 1)
    text = json.dumps(out)
    parts = urlsplit(url)
    assert PATH_MARK not in text and QUERY_MARK not in text
    assert "http://" not in text and "https://" not in text and "://" not in text
    assert out["references"][0]["site"] == parts.hostname


def test_a_look_up_with_no_references_names_none() -> None:
    with bound(Results()):
        got = run(("https://one.example.org/a",))
    assert got.get("references", []) == []


def test_the_reply_shows_references_only_in_that_field() -> None:
    with bound(Results()):
        got = run((URLS[0],), 1)
    assert {"found", "answer", "sources", "references"} <= set(got)
    assert all(set(r) == {"result", "what", "site"} for r in got["references"])


def test_a_reference_to_a_number_this_turn_never_had_is_dropped_and_the_others_stay() -> None:
    with bound(Results()):
        got = run(("https://www.example.org/a",), 1, 9)
    assert got["references"] == [{"result": 1, "what": "thing 1", "site": "www.example.org"}]
