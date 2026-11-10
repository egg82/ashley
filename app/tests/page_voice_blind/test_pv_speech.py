"""Contract 10 and 15's service half, blind: `aloud.speech_of` reads her stored voice for a household and thread, applies
the household's words and starts the speech; it answers None for no voice and raises `AloudUnavailable` when a system it
needs is out of reach."""

import asyncio
import json
from collections.abc import Generator
from pathlib import Path

import pytest
from ashley import channels, services
from ashley.channels import aloud
from ashley.channels.lexicon import Lexicon
from ashley.channels.lexicons import Lexicons, NullLexicons
from ashley.conversations.conversations import ConversationsUnavailable, NullConversations
from ashley.conversations.conversations import Conversations
from ashley.inference.inference import Inference, InferenceUnavailable
from voice_support import FakeSpeech

BODY = "Mowchi is asleep, so I will keep it down."
SPOKEN_JSON = Path(channels.__file__).parent / "spoken.json"


class OneVoice(NullConversations):
    def __init__(self, body: str | None = BODY, down: bool = False) -> None:
        self.body, self.down, self.asked = body, down, list[tuple[int, str, int, int]]()

    async def spoken(self, household_id: int, thread: str, turn_id: int, within_s: int) -> str | None:
        self.asked.append((household_id, thread, turn_id, within_s))
        if self.down:
            raise ConversationsUnavailable("down")
        return self.body


class Words(NullLexicons):
    def __init__(self, words: dict[str, str]) -> None:
        self.words = words
        self.asked = list[int | None]()

    async def of(self, household_id: int | None) -> Lexicon:
        self.asked.append(household_id)
        return Lexicon(self.words)


@pytest.fixture(autouse=True)
def unwired() -> Generator[None]:
    yield
    for interface in (Conversations, Lexicons, Inference):
        services.unregister(interface)


def speak(household: int = 10, thread: str = "person:1:web", turn: int = 5) -> object:
    return asyncio.run(aloud.speech_of(household, thread, turn))


def test_c10_the_body_is_respelled_with_the_households_words_and_spoken_as_speak() -> None:
    conversations, words, speech = OneVoice(), Words({"Mowchi": "Moe-chee"}), FakeSpeech()
    for interface, fake in ((Conversations, conversations), (Lexicons, words), (Inference, speech)):
        services.register(interface, fake)
    got = speak(household=10, thread="person:1:web", turn=5)
    assert got is not None and speech.spoken == ["Moe-chee is asleep, so I will keep it down."]
    assert words.asked == [10]
    [(household, thread, turn, within_s)] = conversations.asked
    assert (household, thread, turn) == (10, "person:1:web", 5)
    assert within_s == json.loads(SPOKEN_JSON.read_text())["voice_s"] == 120


def test_c10_a_household_with_no_words_is_spoken_as_stored() -> None:
    services.register(Conversations, OneVoice())
    services.register(Inference, speech := FakeSpeech())
    assert speak() is not None and speech.spoken == [BODY]


def test_c13_no_voice_is_none_and_nothing_is_synthesised() -> None:
    services.register(Conversations, OneVoice(body=None))
    services.register(Inference, speech := FakeSpeech())
    assert speak() is None and speech.spoken == []


def test_c15_conversations_out_of_reach_is_aloud_unavailable() -> None:
    services.register(Conversations, OneVoice(down=True))
    services.register(Inference, FakeSpeech())
    with pytest.raises(aloud.AloudUnavailable):
        speak()


def test_c15_an_unwired_conversations_is_aloud_unavailable() -> None:
    services.register(Inference, FakeSpeech())
    with pytest.raises(aloud.AloudUnavailable):
        speak()


def test_c15_a_voice_that_cannot_start_is_aloud_unavailable() -> None:
    services.register(Conversations, OneVoice())
    services.register(Inference, FakeSpeech(audio=InferenceUnavailable("down")))
    with pytest.raises(aloud.AloudUnavailable):
        speak()
