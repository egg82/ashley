"""`find`: her search over the records each system keeps (`ashley.find`), the same composite `GET /api/find` asks, for
the hearer of her turn: `owner_alone` decides whether the answer reaches the speaker alone, so a shared screen gets no
ledger and no conversations. Each record carries a number from the turn's count (`tools.results`) that her reply cites
(`Reply.cites`); code keeps which numbers it gave on the result (`ToolResult.citable`). The result is also the trail:
which sources answered, how many records each gave, and which were unreachable. Logs `tools.call` with the counts."""

import time
from collections import Counter
from dataclasses import replace

from ..conversations.model import Hearer
from ..find.find import Source, find
from ..find.model import Found, Kind
from ..find.sources import everyday
from ..inference.model import ToolCall, ToolResult, ToolSpec
from ..receipts import Citable, Shown, ShownKind
from ..tools import bench_results, results
from ..tools.tools import Catalogue, Tools

NAME = "find"
PER_SOURCE = 8
"""How many records each source gives one search."""
_CARDS: dict[Kind, ShownKind] = {"memory": "fact"}
"""The card each kind of record is shown as once cited; a kind with no card yet is cited without being shown."""
_OUTSIDE: frozenset[Kind] = frozenset({"print", "transaction"})
"""Kinds whose text is written outside the household (a print file's name, a merchant), as their own tools mark them."""
SPEC = ToolSpec(NAME, "Search what the household keeps, all at once: what you remember, the person's own past "
                "conversations, the print library and the ledger, each only as far as the people hearing you may "
                "read it. Each record has a number n; put the numbers of the records your reply rests on in `cites`. "
                "A source in unreachable did not answer, so say it could not be searched rather than that nothing "
                "was found. confirmed false marks a guess.",
                {"type": "object", "properties": {"query": {"type": "string", "description": "the words to search for"}},
                 "required": ["query"]}, reads=True, outside=False)


class FindTools(Tools):
    def __init__(self, hearer: Hearer, sources: tuple[Source, ...] | None = None) -> None:
        self._hearer = hearer
        self._sources = everyday() if sources is None else sources

    async def catalogue(self) -> Catalogue:
        return Catalogue((SPEC,), None)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises for a source that fails: it is named in `unreachable`. An unknown tool or a missing query is an
        error result."""
        started = time.monotonic()
        query = call.arguments.get("query")
        if call.name != NAME or not isinstance(query, str) or not query.strip():
            return bench_results.failed(call, started, "unknown_tool" if call.name != NAME else "bad_arguments",
                                        f"no tool named {call.name}" if call.name != NAME else "find needs a query")
        findings = await find(self._sources, self._hearer, query.strip(), PER_SOURCE)
        numbered = [(results.current().number(), f) for f in findings.found]
        counts = Counter(f.kind for f in findings.found)
        body: dict[str, object] = {
            "records": [_record(n, f) for n, f in numbered], "answered": list(findings.answered),
            "counts": {k: counts[k] for k in findings.answered}, "unreachable": list(findings.unreachable)}
        got = bench_results.ok(call, started, body, outside=any(f.kind in _OUTSIDE for f in findings.found),
                               records=len(numbered), unreachable=len(findings.unreachable))
        return replace(got, citable=tuple(Citable(n, _shown(f)) for n, f in numbered))


def _record(n: int, found: Found) -> dict[str, object]:
    when = found.when.isoformat() if found.when is not None else found.dated.isoformat() if found.dated else None
    return {"n": n, "kind": found.kind, "title": found.title, "when": when, "confirmed": found.confirmed}


def _shown(found: Found) -> Shown | None:
    card = _CARDS.get(found.kind)
    return None if card is None else Shown(card, found.ref)
