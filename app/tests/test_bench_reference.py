"""A site or video piece she puts up names a search result by its number, or gives a URL the person or the bench already
had: the server fills in the result's URL from this turn's `Results`, refuses an unknown number, and refuses a URL she
composed, naming the result-number path. The kind checks run on the filled URL."""

import asyncio
import json
from dataclasses import dataclass, field

import pytest
from ashley import logs, services
from ashley.channels.said_links import by_people
from ashley.conversations.conversations import Conversations, NullConversations
from ashley.conversations.model import Author, Conversation, Turn
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools.bench_reference import SaidUnavailable
from ashley.tools.bench_tools import BenchTools
from ashley.tools.results import Results
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Add, Command, Edit
from ashley.workshop.decide import BenchState, Accepted, decide
from ashley.workshop.model import HER, Owner, Piece, Place, Text
from ashley.workshop.workshop import Applied, Workshop
from bench_tools_support import EPOCH, FakeWorkshop

OWNER = Owner(10, 1)
WIKI = "https://en.wikipedia.org/wiki/Travelling_salesman_problem"
TALK = "https://www.youtube.com/watch?v=SC5CX8drAtU"
BLOG = "https://example.org/tsp-notes"
COMPOSED = "https://en.wikipedia.org/wiki/Salesman"
CONVERSATION = 5


@dataclass
class Deciding(FakeWorkshop):
    """A Workshop whose `apply` is the real `decide` over `pieces`."""

    seen: list[Command] = field(default_factory=list[Command])

    async def apply(self, owner: Owner, bench_id: int, command: Command) -> Applied:
        decision = decide(BenchState(self.pieces, next_seq=10), command, workshop_rules.load())
        if not isinstance(decision, Accepted):
            return Applied(decision.seq, decision.reason, None)
        self.seen.append(command)
        return Applied(decision.seq, "accepted", decision.seq)


@dataclass
class Talk(NullConversations):
    """The conversation's turns."""

    turns: tuple[Turn, ...] = ()

    async def get(self, conversation_id: int) -> Conversation | None:
        assert conversation_id == CONVERSATION
        return Conversation(CONVERSATION, 10, "brainstorm", frozenset({1}), EPOCH, EPOCH, "open", self.turns)


def said(author: Author, text: str, n: int) -> Turn:
    return Turn(n, author, 1 if author == "person" else None, text, EPOCH, conversation_id=CONVERSATION)


@pytest.fixture
def shop() -> Deciding:
    fake = Deciding()
    services.register(Workshop, fake)
    services.register(Conversations, Talk())
    return fake


def results() -> Results:
    store = Results()
    for url in (WIKI, TALK, BLOG):
        store.record(url)
    return store


def tools(store: Results | None = None) -> BenchTools:
    return BenchTools(OWNER.household_id, OWNER.person_id, 4, results=store or results(), said=by_people(CONVERSATION))


def call(t: BenchTools, name: str, **args: object) -> ToolResult:
    return asyncio.run(t.call(ToolCall("c1", name, args)))


def piece(pid: int, kind: str, body: str) -> Piece:
    return Piece(pid, kind, Text("t", body), 1, Place(pid, "medium"), pid)


def test_a_result_number_fills_a_site_pieces_url(shop: Deciding) -> None:
    got = call(tools(), "bench_add", kind="site", title="TSP", result=1)
    assert not got.is_error, got.content
    assert shop.seen == [Add(HER, "site", Text("TSP", WIKI), "medium")]


def test_a_result_number_fills_a_video_pieces_body_with_its_start(shop: Deciding) -> None:
    assert not call(tools(), "bench_add", kind="video", title="Talk", result=2, start=90).is_error
    assert not call(tools(), "bench_add", kind="video", title="Talk", result=2).is_error
    bodies = [json.loads(c.text.body) for c in shop.seen if isinstance(c, Add)]
    assert bodies == [{"url": TALK, "start": 90}, {"url": TALK}]


def test_an_unknown_result_number_is_refused_and_nothing_is_applied(shop: Deciding) -> None:
    for number in (0, 4, 99):
        got = call(tools(), "bench_add", kind="site", title="T", result=number)
        assert got.is_error and got.content.startswith("unknown_result:"), got.content
    assert shop.seen == []


def test_a_youtube_result_is_refused_as_a_site_and_accepted_as_a_video(shop: Deciding) -> None:
    site = call(tools(), "bench_add", kind="site", title="T", result=2)
    assert site.is_error and site.content.startswith("bad_site:")
    assert not call(tools(), "bench_add", kind="video", title="T", result=2).is_error
    assert len(shop.seen) == 1


def test_a_result_is_for_a_site_or_video_and_replaces_the_body(shop: Deciding) -> None:
    note = call(tools(), "bench_add", kind="note", title="T", result=1)
    both = call(tools(), "bench_add", kind="site", title="T", body=WIKI, result=1)
    assert note.is_error and note.content.startswith("bad_arguments:")
    assert both.is_error and both.content.startswith("bad_arguments:")
    assert shop.seen == []


def test_a_start_goes_with_a_result(shop: Deciding) -> None:
    got = call(tools(), "bench_add", kind="video", title="T", body='{"url": "' + TALK + '"}', start=5)
    assert got.is_error and got.content.startswith("bad_arguments:")


def test_a_composed_url_is_refused_naming_the_result_path(shop: Deciding) -> None:
    for kind, body in (("site", COMPOSED), ("video", json.dumps({"url": TALK}))):
        got = call(tools(), "bench_add", kind=kind, title="T", body=body)
        assert got.is_error and got.content.startswith("unlisted_url:"), got.content
        assert "result" in got.content
    assert shop.seen == []


def test_a_url_the_person_pasted_is_accepted(shop: Deciding) -> None:
    services.register(Conversations, Talk((
        said("person", f"look at {COMPOSED}, and also ({BLOG}).", 1), said("ashley", f"see {TALK}", 2))))
    assert not call(tools(), "bench_add", kind="site", title="T", body=COMPOSED).is_error
    assert not call(tools(), "bench_add", kind="site", title="T", body=BLOG).is_error
    assert call(tools(), "bench_add", kind="video", title="T", body=json.dumps({"url": TALK})).is_error


def test_a_longer_url_of_the_person_does_not_vouch_for_a_prefix_of_it(shop: Deciding) -> None:
    services.register(Conversations, Talk((said("person", COMPOSED + "_problem", 1),)))
    assert call(tools(), "bench_add", kind="site", title="T", body=COMPOSED).is_error


def test_a_url_already_in_a_site_or_video_piece_on_the_bench_is_accepted_but_not_one_in_a_document(shop: Deciding) -> None:
    shop.pieces = (piece(1, "site", BLOG), piece(2, "video", json.dumps({"url": TALK})),
                   piece(3, "document", f"links: {COMPOSED}"))
    assert not call(tools(), "bench_add", kind="site", title="T", body=BLOG).is_error
    assert not call(tools(), "bench_add", kind="video", title="T", body=json.dumps({"url": TALK, "start": 3})).is_error
    assert call(tools(), "bench_add", kind="site", title="T", body=COMPOSED).is_error


def test_an_empty_body_is_a_draft_and_needs_no_source(shop: Deciding) -> None:
    assert not call(tools(), "bench_add", kind="site", title="T", body="").is_error


def test_an_edit_names_a_result_or_a_url_the_same_way(shop: Deciding) -> None:
    shop.pieces = (piece(1, "site", BLOG),)
    t = tools()
    asyncio.run(t.call(ToolCall("r", "bench_read_piece", {"piece_id": 1})))
    composed = call(t, "bench_edit", piece_id=1, base_version=1, title="T", body=COMPOSED)
    assert composed.is_error and composed.content.startswith("unlisted_url:")
    filled = call(t, "bench_edit", piece_id=1, base_version=1, title="T", result=3)
    assert not filled.is_error, filled.content
    assert shop.seen == [Edit(HER, 1, 1, Text("T", BLOG))]
    unknown = call(t, "bench_edit", piece_id=1, base_version=1, title="T", result=9)
    assert unknown.is_error and unknown.content.startswith("unknown_result:")


def test_a_note_with_a_link_in_its_text_is_unchecked(shop: Deciding) -> None:
    assert not call(tools(), "bench_add", kind="note", title="T", body=f"see {COMPOSED}").is_error


def test_without_a_conversation_only_the_bench_vouches(shop: Deciding) -> None:
    t = BenchTools(OWNER.household_id, OWNER.person_id, 4, results=results())
    got = call(t, "bench_add", kind="site", title="T", body=COMPOSED)
    assert got.is_error and got.content.startswith("unlisted_url:")


def test_the_log_line_names_the_outcome_and_no_url(shop: Deciding, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    call(tools(), "bench_add", kind="site", title="T", body=COMPOSED)
    call(tools(), "bench_add", kind="site", title="T", result=1)
    out = capsys.readouterr().out
    assert "unlisted_url" in out and "outcome=ok" in out and "wikipedia" not in out


def test_a_conversation_that_cannot_be_read_refuses_a_direct_url_as_unavailable(shop: Deciding) -> None:
    async def down() -> frozenset[str]:
        raise SaidUnavailable()
    t = BenchTools(OWNER.household_id, OWNER.person_id, 4, results=results(), said=down)
    got = call(t, "bench_add", kind="site", title="T", body=COMPOSED)
    assert got.is_error and got.content.startswith("unavailable:")
    assert not call(t, "bench_add", kind="site", title="T", result=1).is_error


@pytest.mark.parametrize("kind", ["site", "video"])
def test_a_site_or_video_piece_is_not_changed_by_replace_which_would_skip_the_check(shop: Deciding, kind: str) -> None:
    body = BLOG if kind == "site" else json.dumps({"url": BLOG})
    shop.pieces = (piece(1, kind, body),)
    t = tools()
    asyncio.run(t.call(ToolCall("r", "bench_read_piece", {"piece_id": 1})))
    got = call(t, "bench_replace", piece_id=1, base_version=1, old=BLOG, new=COMPOSED)
    assert got.is_error and got.content.startswith("bad_arguments:") and "bench_edit" in got.content
    assert shop.seen == []
