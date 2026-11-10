"""A URL she composes herself: accepted only when a person's turn of this conversation wrote it, or a site or video
piece (on the bench or the shelf) already holds it; her own reply, a household turn, a document's text, another
conversation and a near miss never vouch. Refused `unlisted_url`, with no URL in the refusal; `unavailable` when the
conversation cannot be read. Each case runs as an Add and as an Edit."""

import asyncio
from dataclasses import replace

import pytest
from ashley import services
from ashley.conversations.conversations import Conversations
from ashley.conversations.model import Author, Conversation, Turn
from ashley.tools.results import Results
from refb_support import (OTHER, PASTED, WIKI, YT, body_of, by_people, conversation_down, error_code, piece, rig,
                        said_of, video_body)
from respond_support import EPOCH, FakeConversations

OPS = ["add", "edit"]


def chat(*turns: tuple[Author, str]) -> FakeConversations:
    """Conversation 1 holding `(author, text)` turns, registered as the locator's Conversations."""
    fake = FakeConversations()
    made = tuple(Turn(i + 1, a, 1 if a == "person" else None, t, EPOCH, conversation_id=1)
                 for i, (a, t) in enumerate(turns))
    fake.convs[1] = Conversation(1, 10, "chat", frozenset({1}), EPOCH, EPOCH, "open", made)
    services.register(Conversations, fake)
    return fake


@pytest.mark.parametrize("op", OPS)
def test_a_url_the_person_pasted_is_accepted(op: str) -> None:
    r = rig("site", said=said_of(PASTED))
    got = r.put(op, "site", body=PASTED)
    assert not got.is_error, got.content
    assert body_of(r.command()) == PASTED


@pytest.mark.parametrize("op", OPS)
def test_a_pasted_youtube_url_is_accepted_as_a_video_body(op: str) -> None:
    r = rig("video", said=said_of(YT))
    got = r.put(op, "video", body=video_body(YT, 30))
    assert not got.is_error, got.content


@pytest.mark.parametrize("op", OPS)
def test_a_url_nobody_vouches_for_is_unlisted_and_the_refusal_holds_no_url(op: str) -> None:
    r = rig("site", said=said_of(PASTED))
    got = r.put(op, "site", body=OTHER)
    assert error_code(got, "unlisted_url"), got.content
    assert "example.org" not in got.content and "http" not in got.content
    assert r.shop.applied == []


@pytest.mark.parametrize("op", OPS)
def test_without_a_reader_of_the_conversation_only_the_bench_vouches(op: str) -> None:
    r = rig("site", said=None)
    assert error_code(r.put(op, "site", body=OTHER), "unlisted_url")
    assert r.shop.applied == []


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("near", [PASTED + "/", PASTED + "?x=1", PASTED.upper(), PASTED.replace("https", "http"),
                                  PASTED[:-1], PASTED + "#top"])
def test_a_near_miss_of_a_pasted_url_is_not_it(op: str, near: str) -> None:
    r = rig("site", said=said_of(PASTED))
    got = r.put(op, "site", body=near)
    assert error_code(got, "unlisted_url", "bad_site"), got.content
    assert r.shop.applied == []


@pytest.mark.parametrize("op", OPS)
def test_a_url_on_the_bench_as_a_site_piece_is_accepted(op: str) -> None:
    r = rig("site", pieces=(piece(60, "site", WIKI),), said=said_of())
    assert not r.put(op, "site", body=WIKI).is_error
    assert body_of(r.command()) == WIKI


@pytest.mark.parametrize("op", OPS)
def test_a_url_in_a_video_piece_on_the_bench_vouches_for_a_site_too(op: str) -> None:
    r = rig("site", pieces=(piece(60, "video", video_body("https://cdn.example.com/a.mp4", 5)),), said=said_of())
    assert not r.put(op, "site", body="https://cdn.example.com/a.mp4").is_error


@pytest.mark.parametrize("op", OPS)
def test_a_url_in_a_video_piece_on_the_shelf_is_accepted(op: str) -> None:
    r = rig("video", shelf=(piece(61, "video", video_body(YT, 7)),), said=said_of())
    assert not r.put(op, "video", body=video_body(YT)).is_error


@pytest.mark.parametrize("op", OPS)
def test_a_url_in_a_site_piece_on_the_shelf_is_accepted(op: str) -> None:
    r = rig("site", shelf=(piece(61, "site", WIKI),), said=said_of())
    assert not r.put(op, "site", body=WIKI).is_error


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("kind", ["document", "note", "code"])
def test_a_documents_text_is_no_source(op: str, kind: str) -> None:
    text = f"see {OTHER} and also ({OTHER}). {OTHER}"
    r = rig("site", pieces=(piece(60, kind, text),), shelf=(piece(61, kind, text),), said=said_of())
    got = r.put(op, "site", body=OTHER)
    assert error_code(got, "unlisted_url"), got.content
    assert r.shop.applied == []


@pytest.mark.parametrize("op", OPS)
def test_a_piece_that_cited_a_url_cannot_launder_it_through_a_document(op: str) -> None:
    r = rig("site", pieces=(piece(60, "document", f"link: {WIKI}"),), said=said_of())
    assert error_code(r.put(op, "site", body=WIKI), "unlisted_url")


@pytest.mark.parametrize("op", OPS)
def test_a_reader_that_cannot_read_the_conversation_is_unavailable(op: str) -> None:
    r = rig("site", said=conversation_down)
    got = r.put(op, "site", body=OTHER)
    assert error_code(got, "unavailable"), got.content
    assert r.shop.applied == []


@pytest.mark.parametrize("op", OPS)
def test_a_number_needs_no_reading_of_the_conversation(op: str) -> None:
    r = rig("site", said=conversation_down)
    n = r.results.record(WIKI)
    got = r.put(op, "site", result=n)
    assert not got.is_error, got.content


@pytest.mark.parametrize("op", OPS)
def test_a_composed_video_host_page_is_refused_even_when_listed_as_a_site(op: str) -> None:
    r = rig("site", said=said_of(YT))
    assert error_code(r.put(op, "site", body=YT), "bad_site")


# --- the real reader of a conversation's person turns -------------------------------------------------------------


@pytest.mark.parametrize("op", OPS)
def test_by_people_accepts_a_url_in_a_person_turn(op: str) -> None:
    chat(("person", f"play {PASTED} for me"))
    r = rig("site", said=by_people(1))
    assert not r.put(op, "site", body=PASTED).is_error


@pytest.mark.parametrize("op", OPS)
def test_a_url_only_in_her_own_earlier_reply_is_refused(op: str) -> None:
    chat(("person", "show me something on salesmen"), ("ashley", f"How about {WIKI} ?"))
    r = rig("site", said=by_people(1))
    got = r.put(op, "site", body=WIKI)
    assert error_code(got, "unlisted_url"), got.content
    assert r.shop.applied == []


@pytest.mark.parametrize("op", OPS)
def test_a_url_only_in_a_household_turn_is_refused(op: str) -> None:
    chat(("person", "hi"), ("household", f"someone left {WIKI}"))
    r = rig("site", said=by_people(1))
    assert error_code(r.put(op, "site", body=WIKI), "unlisted_url")


@pytest.mark.parametrize("op", OPS)
def test_a_person_turn_of_another_conversation_does_not_count(op: str) -> None:
    fake = chat(("person", "hello"))
    fake.convs[2] = replace(fake.convs[1], id=2, turns=(Turn(9, "person", 1, f"see {WIKI}", EPOCH, conversation_id=2),))
    r = rig("site", said=by_people(1))
    assert error_code(r.put(op, "site", body=WIKI), "unlisted_url")
    assert not rig("site", said=by_people(2)).put(op, "site", body=WIKI).is_error


@pytest.mark.parametrize("op", OPS)
def test_by_people_reads_the_conversation_when_asked_so_a_later_turn_counts(op: str) -> None:
    fake = chat(("person", "hello"))
    r = rig("site", said=by_people(1))
    assert error_code(r.put(op, "site", body=PASTED), "unlisted_url")
    conv = fake.convs[1]
    fake.convs[1] = replace(conv, turns=(*conv.turns, Turn(5, "person", 1, PASTED, EPOCH, conversation_id=1)))
    assert not r.put(op, "site", body=PASTED).is_error


def test_by_people_of_a_conversation_nobody_has_is_empty() -> None:
    chat()
    async def read() -> frozenset[str]:
        return await by_people(77)()

    assert asyncio.run(read()) == frozenset()


def test_by_people_raises_when_the_conversations_are_down() -> None:
    from ashley.conversations.conversations import ConversationsUnavailable
    from ashley.tools.bench_reference import SaidUnavailable

    class Down(FakeConversations):
        async def get(self, conversation_id: int) -> Conversation | None:
            raise ConversationsUnavailable("down")

    services.register(Conversations, Down())
    async def read() -> frozenset[str]:
        return await by_people(1)()

    with pytest.raises(SaidUnavailable):
        asyncio.run(read())
    r = rig("site", said=by_people(1))
    assert error_code(r.put("add", "site", body=OTHER), "unavailable")


def test_a_pasted_url_never_makes_a_number_exist() -> None:
    r = rig("site", said=said_of(PASTED), results=Results())
    assert error_code(r.put("add", "site", result=1), "unknown_result")


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("url", [YT, "https://cdn.example.com/composed.mp4", "https://vimeo.com/76979871"])
def test_a_composed_video_url_is_unlisted_and_a_listed_one_is_not(op: str, url: str) -> None:
    r = rig("video", said=said_of(PASTED))
    got = r.put(op, "video", body=video_body(url, 12))
    assert error_code(got, "unlisted_url"), got.content
    assert r.shop.applied == []
    listed = rig("video", said=said_of(url))
    assert not listed.put(op, "video", body=video_body(url, 12)).is_error


@pytest.mark.parametrize("op", OPS)
def test_a_composed_video_url_is_refused_even_when_a_site_piece_holds_another(op: str) -> None:
    r = rig("video", pieces=(piece(60, "site", WIKI),), said=said_of())
    assert error_code(r.put(op, "video", body=video_body(YT)), "unlisted_url")
