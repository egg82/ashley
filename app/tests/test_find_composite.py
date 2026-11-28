"""`ashley.find.find.find` over stub sources: a source that fails or runs out of time is unreachable, never an empty
answer; one that does not serve the hearer is in neither list; a defect in a source is not hidden."""

import asyncio

import pytest
from ashley.conversations.model import Hearer
from ashley.find.find import Source, find
from ashley.find.model import Found, Kind, SourceDown

HEARER = Hearer(1, 2, owner_only=True)


class Stub(Source):
    def __init__(self, kind: Kind, answer: tuple[Found, ...] | None | BaseException | str) -> None:
        self.kind = kind
        self._answer = answer

    async def find(self, hearer: Hearer, query: str, limit: int) -> tuple[Found, ...] | None:
        if self._answer == "hang":
            await asyncio.Event().wait()
        if isinstance(self._answer, BaseException):
            raise self._answer
        assert not isinstance(self._answer, str)
        return self._answer


def record(kind: Kind, ref: str) -> Found:
    return Found(kind, ref, "title", None, True)


def test_failing_and_slow_sources_are_unreachable_while_the_rest_answer() -> None:
    sources = [Stub("memory", (record("memory", "1"),)), Stub("conversation", SourceDown("down")),
               Stub("print", "hang"), Stub("transaction", ())]
    got = asyncio.run(find(sources, HEARER, "q", 5, timeout_s=0.05))
    assert got.found == (record("memory", "1"),)
    assert got.answered == ("memory", "transaction")
    assert got.unreachable == ("conversation", "print")


def test_a_source_that_does_not_serve_the_hearer_is_in_neither_list() -> None:
    got = asyncio.run(find([Stub("transaction", None), Stub("print", (record("print", "p"),))], HEARER, "q", 5))
    assert got.answered == ("print",) and got.unreachable == ()


def test_a_defect_in_a_source_propagates() -> None:
    with pytest.raises(ValueError):
        asyncio.run(find([Stub("memory", ValueError("bug")), Stub("print", ())], HEARER, "q", 5))


def test_each_source_is_capped_at_limit() -> None:
    many = tuple(record("print", str(i)) for i in range(4))
    got = asyncio.run(find([Stub("print", many), Stub("memory", (record("memory", "m"),))], HEARER, "q", 2))
    assert [f.ref for f in got.found] == ["0", "1", "m"]
