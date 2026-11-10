"""A pasted or forwarded block over the threshold (`channels.pasted`) starts the person's turn `pasted`, and is never among
the action judge's words: the web composer's attachment, a Discord forward; under the threshold nothing changes, voice has
no paste, the typed text around a block stays in the words, and logs carry lengths, never the block."""

import asyncio
import json
from collections.abc import Generator
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from ashley import services
from ashley.channels import judge_words, pasted
from ashley.channels.discord.route import FORWARD_ONLY, route
from ashley.channels.model import Inbound, Outbound
from ashley.conversations.conversations import Conversations, NullConversations
from ashley.conversations.model import Attachment, Conversation, Turn
from discord_support import ALANA, CHANNEL, DM_CHANNEL, FAMILY, GUILD, ME, message
from ashley.channels.model import DiscordServer
from fastapi.testclient import TestClient
from respond_support import Fakes, wired as wired
from test_chat_routes import REPLY, client as client, outbox as outbox
from test_voice_run import carry
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from voice_support import FakeSpeech, FakeTurnLoop, satellite_row

SERVERS = {GUILD: DiscordServer(FAMILY, GUILD, CHANNEL)}
LIMIT = pasted.threshold()
OVER = "zqOVER " * (LIMIT // 7 + 2)
UNDER = "zqUNDER " * 5
NOW = datetime(2026, 11, 8, tzinfo=UTC)


def test_the_threshold_is_data_beside_its_reader() -> None:
    assert json.loads(pasted.FILE.read_text()) == {"taint_chars": LIMIT} and LIMIT > 1 and pasted.FILE.parent.name == "channels"


def test_a_block_is_pasted_only_when_longer_than_the_threshold() -> None:
    assert pasted.taint_of(Attachment(None, "x" * (LIMIT + 1))) == "pasted"
    assert pasted.taint_of(Attachment(None, "x" * LIMIT)) is None, "control: the threshold itself is not over it"
    assert pasted.taint_of(None) is None


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> list[Inbound]:
    got: list[Inbound] = []

    async def respond(inbound: Inbound) -> Outbound:
        got.append(inbound)
        return Outbound(1, "text", "ok")

    monkeypatch.setattr("ashley.api.chat.respond", respond)
    return got


def post(client: TestClient, **body: object) -> None:
    assert client.post("/api/chat/messages", json=body).status_code == 200


def test_a_web_paste_over_the_threshold_starts_the_turn_pasted(client: TestClient, seen: list[Inbound]) -> None:
    post(client, text="what should I do about this?", attachment={"text": OVER})
    [inbound] = seen
    assert inbound.taint == "pasted" and inbound.attachment == Attachment(None, OVER)
    assert inbound.text == "what should I do about this?"


def test_a_web_paste_under_the_threshold_changes_nothing_about_the_taint(client: TestClient, seen: list[Inbound]) -> None:
    post(client, text="see this", attachment={"text": UNDER})
    post(client, text="no paste")
    assert [i.taint for i in seen] == [None, None] and seen[0].attachment == Attachment(None, UNDER)


def test_the_paste_is_stored_apart_and_logged_by_length_only(client: TestClient, wired: Fakes,
                                                              capsys: pytest.CaptureFixture[str]) -> None:
    wired.inference.script = [REPLY]
    capsys.readouterr()
    post(client, text="zqTYPED", attachment={"title": "zqTITLE", "text": OVER})
    out = capsys.readouterr().out
    stored = wired.conversations.added[0]
    assert stored.text == "zqTYPED" and stored.attachment == Attachment("zqTITLE", OVER)
    line = next(ln for ln in out.splitlines() if "event=respond.attached" in ln)
    assert f"chars={len(OVER)}" in line and "tainted=true" in line
    assert not [m for m in ("zqOVER", "zqTITLE", "zqTYPED") if m in out]


def forward(text: str = "", **changes: object) -> Inbound:
    got = route(message(content=f"<@{ME}> {text}", forwarded=OVER, **changes), ME, SERVERS, ALANA)
    assert got is not None
    return got


def test_a_discord_forward_over_the_threshold_is_an_attachment_and_taints_the_turn() -> None:
    got = forward("is this right?")
    assert got.taint == "pasted" and got.attachment == Attachment("Forwarded", OVER.strip()) and got.text == "is this right?"


def test_a_discord_forward_with_nothing_typed_says_so_and_is_answered() -> None:
    assert forward().text == FORWARD_ONLY


def test_a_dm_forward_taints_too() -> None:
    got = route(message(guild_id=None, channel_id=DM_CHANNEL, mentions_me=False, content="", forwarded=OVER), ME, {}, ALANA)
    assert got is not None and got.taint == "pasted"


def test_a_short_discord_forward_is_read_but_does_not_taint() -> None:
    got = route(message(forwarded=UNDER), ME, SERVERS, ALANA)
    assert got is not None and got.taint is None and got.attachment is not None


def test_a_nul_in_the_forward_is_refused_like_one_in_the_text() -> None:
    assert route(message(content=f"<@{ME}> hi", forwarded="a\x00b"), ME, SERVERS, ALANA) is None
    assert route(message(content=f"<@{ME}> hi", forwarded="ab"), ME, SERVERS, ALANA) is not None, "control"


def test_a_message_forwarding_nothing_has_no_attachment_and_no_taint() -> None:
    got = route(message(), ME, SERVERS, ALANA)
    assert got is not None and got.attachment is None and got.taint is None


def test_a_strangers_forward_stays_stranger() -> None:
    got = route(message(forwarded=OVER), ME, SERVERS, None)
    assert got is not None and got.taint == "stranger"


def test_voice_has_no_paste(db_url: str) -> None:
    satellite = satellite_row(db_url, household(db_url))
    loop = FakeTurnLoop()
    carry(db_url, satellite, FakeSpeech(transcript=OVER), loop)
    [inbound] = loop.asked
    assert inbound.text == OVER and inbound.taint is None and inbound.attachment is None


class Stored(NullConversations):
    def __init__(self, turns: tuple[Turn, ...]) -> None:
        self.turns = turns

    async def get(self, conversation_id: int) -> Conversation | None:
        return Conversation(5, 1, "chat", frozenset({ALANA.id}), NOW, NOW, "open", self.turns)


@pytest.fixture
def unwired() -> Generator[None]:
    yield
    services.unregister(Conversations)


def test_the_typed_text_around_a_paste_stays_in_the_judges_words_and_the_paste_does_not(unwired: None) -> None:
    turns = (Turn(1, "person", ALANA.id, "what should I do about this?", NOW, attachment=Attachment(None, OVER)),
             Turn(2, "person", ALANA.id, "then reply to sam", NOW))
    services.register(Conversations, Stored(turns))
    clean = Inbound(1, "web", "yes", "chat", "text", "owner", ALANA.id, False, None, "web", taint=None)

    async def words(inbound: Inbound) -> tuple[str, ...]:
        return tuple(await judge_words.reader(inbound, 5, 10, 500)())

    assert asyncio.run(words(clean)) == ("what should I do about this?", "then reply to sam")
    assert asyncio.run(words(replace(clean, taint="pasted"))) == ("what should I do about this?", "then reply to sam")
    assert asyncio.run(words(replace(clean, taint="stranger"))) == (), "control: an outside origin has no words"
