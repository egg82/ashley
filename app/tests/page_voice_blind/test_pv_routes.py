"""Contract 10 to 17, blind: `GET /api/chat/turns/{id}/voice` and `GET /api/kiosk/turns/{id}/voice` through the real app
over a real database with a scripted voice. Her stored `spoken` is synthesised on the fetch with the household's words,
only on the caller's own thread and only within `voice_s`; everything else is one 404 that never says whether the turn
exists; and the conversation reads say which of her turns have a voice."""

import pytest
from ashley import services
from ashley.api.models import ChatConversation, ErrorResponse
from ashley.conversations.conversations import Conversations
from ashley.inference.inference import InferenceUnavailable
from contract.conversations_support import events, scalar
from later_support import Logged
from pv_pg_support import Home, age, as_device, as_person, device_in, real_app, seed, teach, voice_url
from pv_pg_support import home as home
from voice_support import FakeSpeech

WORDS = "Mowchi is asleep, so I will keep it down."
AUDIO = b"ID3-0123456789"
KIOSK_TOKEN = "zqKIOSK-9931"


def alana_thread(home: Home) -> str:
    return f"person:{home.alana.id}:web"


def code(response: object) -> str:
    return ErrorResponse.model_validate(getattr(response, "json")()).code


def test_c10_a_person_fetches_the_voice_of_their_own_turn_respelled_by_the_household(home: Home) -> None:
    teach(home.url, home.house, "Mowchi", "Moe-chee")
    made = seed(home.url, home.house, alana_thread(home), home.alana.id, spoken=WORDS)
    speech = FakeSpeech(audio=AUDIO)
    with real_app(home.url, speech) as c:
        r = as_person(c, home.alana_token).get(voice_url("chat", made.turn))
    assert r.status_code == 200 and r.headers["content-type"].startswith("audio/mpeg")
    assert r.content == AUDIO
    assert speech.spoken == ["Moe-chee is asleep, so I will keep it down."]


def test_c10_the_words_apply_on_the_way_out_and_never_to_what_is_stored(home: Home) -> None:
    teach(home.url, home.house, "Mowchi", "Moe-chee")
    made = seed(home.url, home.house, alana_thread(home), home.alana.id, spoken=WORDS)
    with real_app(home.url) as c:
        as_person(c, home.alana_token).get(voice_url("chat", made.turn))
        shown = ChatConversation.model_validate(c.get("/api/chat/conversation").json())
    assert [t.text for t in shown.turns if t.author == "ashley"] == ["Dry all day."]
    assert scalar(home.url, "SELECT spoken FROM turns WHERE id = %s", (made.turn,)) == WORDS


def test_c10_a_household_with_no_words_is_spoken_as_stored(home: Home) -> None:
    made = seed(home.url, home.house, alana_thread(home), home.alana.id, spoken=WORDS)
    speech = FakeSpeech(audio=AUDIO)
    with real_app(home.url, speech) as c:
        as_person(c, home.alana_token).get(voice_url("chat", made.turn))
    assert speech.spoken == [WORDS]


def test_c10_another_households_words_are_not_applied(home: Home) -> None:
    teach(home.url, home.other_house, "Mowchi", "Moe-chee")
    made = seed(home.url, home.house, alana_thread(home), home.alana.id, spoken=WORDS)
    speech = FakeSpeech(audio=AUDIO)
    with real_app(home.url, speech) as c:
        as_person(c, home.alana_token).get(voice_url("chat", made.turn))
    assert speech.spoken == [WORDS]


def test_c10_the_kiosk_fetches_the_voice_of_a_turn_on_its_own_thread(home: Home) -> None:
    device = device_in(home.url, home.house, KIOSK_TOKEN)
    teach(home.url, home.house, "Mowchi", "Moe-chee")
    made = seed(home.url, home.house, f"device:{device.id}", None, spoken=WORDS)
    speech = FakeSpeech(audio=AUDIO)
    with real_app(home.url, speech) as c:
        r = as_device(c, KIOSK_TOKEN).get(voice_url("kiosk", made.turn))
    assert r.status_code == 200 and r.headers["content-type"].startswith("audio/mpeg") and r.content == AUDIO
    assert speech.spoken == ["Moe-chee is asleep, so I will keep it down."]


def test_c10_a_fetch_changes_nothing_and_needs_no_same_origin_header(home: Home) -> None:
    made = seed(home.url, home.house, alana_thread(home), home.alana.id, spoken=WORDS)
    with real_app(home.url) as c:
        as_person(c, home.alana_token)
        first = c.get(voice_url("chat", made.turn), headers={"origin": "https://elsewhere.test"})
        second = c.get(voice_url("chat", made.turn))
    assert first.status_code == 200 and second.status_code == 200, "a GET is read-only and repeatable within the window"


def test_c11_another_person_or_household_or_the_kiosk_thread_gets_404_not_found(home: Home) -> None:
    device = device_in(home.url, home.house, KIOSK_TOKEN)
    alanas = seed(home.url, home.house, alana_thread(home), home.alana.id, spoken=WORDS)
    kiosks = seed(home.url, home.house, f"device:{device.id}", None, spoken=WORDS)
    speech = FakeSpeech(audio=AUDIO)
    with real_app(home.url, speech) as c:
        mine = as_person(c, home.alana_token).get(voice_url("chat", alanas.turn))
        assert mine.status_code == 200, "control: the owner can"
        for token, turn in ((home.sam_token, alanas.turn), (home.zed_token, alanas.turn),
                            (home.alana_token, kiosks.turn)):
            c.cookies.clear()
            r = as_person(c, token).get(voice_url("chat", turn))
            assert r.status_code == 404 and code(r) == "not_found"
    assert speech.spoken == [WORDS], "only the owner's fetch reached the voice"


def test_c11_a_foreign_turn_and_a_missing_one_are_the_same_answer(home: Home) -> None:
    alanas = seed(home.url, home.house, alana_thread(home), home.alana.id, spoken=WORDS)
    with real_app(home.url) as c:
        as_person(c, home.sam_token)
        foreign = c.get(voice_url("chat", alanas.turn))
        missing = c.get(voice_url("chat", alanas.turn + 5000))
    assert foreign.status_code == missing.status_code == 404 and foreign.json() == missing.json()


def test_c12_the_kiosk_gets_404_for_a_persons_chat_and_for_another_kiosk(home: Home) -> None:
    device = device_in(home.url, home.house, KIOSK_TOKEN)
    other = device_in(home.url, home.house, "zqKIOSK-OTHER", name="kitchen tablet")
    persons = seed(home.url, home.house, alana_thread(home), home.alana.id, spoken=WORDS)
    others = seed(home.url, home.house, f"device:{other.id}", None, spoken=WORDS)
    own = seed(home.url, home.house, f"device:{device.id}", None, spoken=WORDS)
    speech = FakeSpeech(audio=AUDIO)
    with real_app(home.url, speech) as c:
        as_device(c, KIOSK_TOKEN)
        assert c.get(voice_url("kiosk", own.turn)).status_code == 200, "control: its own"
        for turn in (persons.turn, others.turn):
            r = c.get(voice_url("kiosk", turn))
            assert r.status_code == 404 and code(r) == "not_found"
    assert speech.spoken == [WORDS]


def test_c12_a_kiosk_of_another_household_gets_404_even_when_the_thread_name_is_shared(home: Home) -> None:
    strange = device_in(home.url, home.other_house, "zqKIOSK-STRANGE", name="their tablet")
    ours = seed(home.url, home.house, f"device:{strange.id}", None, spoken=WORDS)
    theirs = seed(home.url, home.other_house, f"device:{strange.id}", None, spoken="theirs")
    with real_app(home.url) as c:
        as_device(c, "zqKIOSK-STRANGE")
        assert c.get(voice_url("kiosk", theirs.turn)).status_code == 200, "control: its own household's turn"
        r = c.get(voice_url("kiosk", ours.turn))
        assert r.status_code == 404 and code(r) == "not_found"


def test_c13_a_turn_without_a_voice_a_person_turn_and_a_missing_id_are_404(home: Home) -> None:
    thread = alana_thread(home)
    plain = seed(home.url, home.house, thread, home.alana.id, spoken=None)
    speech = FakeSpeech(audio=AUDIO)
    with real_app(home.url, speech) as c:
        as_person(c, home.alana_token)
        for turn in (plain.turn, plain.asked, plain.turn + 5000):
            r = c.get(voice_url("chat", turn))
            assert r.status_code == 404 and code(r) == "not_found"
    assert speech.spoken == []


def test_c13_the_kiosk_answers_the_same_for_those(home: Home) -> None:
    device = device_in(home.url, home.house, KIOSK_TOKEN)
    plain = seed(home.url, home.house, f"device:{device.id}", None, spoken=None)
    with real_app(home.url) as c:
        as_device(c, KIOSK_TOKEN)
        for turn in (plain.turn, plain.asked, plain.turn + 5000):
            r = c.get(voice_url("kiosk", turn))
            assert r.status_code == 404 and code(r) == "not_found"


@pytest.mark.parametrize("kind", ["chat", "kiosk"])
def test_a_non_integer_id_is_422_not_404(home: Home, kind: str) -> None:
    device_in(home.url, home.house, KIOSK_TOKEN)
    with real_app(home.url) as c:
        as_device(as_person(c, home.alana_token), KIOSK_TOKEN)
        for bad in ("abc", "1.5", "voice"):
            assert c.get(voice_url(kind, bad)).status_code == 422


def test_c14_a_voice_older_than_voice_s_is_404_and_the_conversation_still_shows_it_voiced(home: Home) -> None:
    thread = alana_thread(home)
    made = seed(home.url, home.house, thread, home.alana.id, spoken=WORDS)
    with real_app(home.url) as c:
        as_person(c, home.alana_token)
        age(home.url, made.conversation, 100)
        assert c.get(voice_url("chat", made.turn)).status_code == 200, "control: inside the window"
        age(home.url, made.conversation, 30)
        r = c.get(voice_url("chat", made.turn))
        assert r.status_code == 404 and code(r) == "not_found"
        shown = ChatConversation.model_validate(c.get("/api/chat/conversation").json())
    assert [(t.author, t.voiced) for t in shown.turns] == [("person", False), ("ashley", True)]


def test_c14_the_kiosk_expires_the_same_way(home: Home) -> None:
    device = device_in(home.url, home.house, KIOSK_TOKEN)
    made = seed(home.url, home.house, f"device:{device.id}", None, spoken=WORDS)
    age(home.url, made.conversation, 130)
    with real_app(home.url) as c:
        as_device(c, KIOSK_TOKEN)
        assert c.get(voice_url("kiosk", made.turn)).status_code == 404
        shown = ChatConversation.model_validate(c.get("/api/kiosk/conversation").json())
    assert [t.voiced for t in shown.turns if t.author == "ashley"] == [True]


def test_c14_the_window_is_served_data_and_matches_the_page(home: Home) -> None:
    with real_app(home.url) as c:
        limits = c.get("/api/spoken/limits").json()
    assert limits["voice_s"] == 120 and "max_ms" in limits


def test_c15_no_session_is_401_and_cookies_do_not_stand_in_for_each_other(home: Home) -> None:
    device = device_in(home.url, home.house, KIOSK_TOKEN)
    mine = seed(home.url, home.house, alana_thread(home), home.alana.id, spoken=WORDS)
    kiosks = seed(home.url, home.house, f"device:{device.id}", None, spoken=WORDS)
    with real_app(home.url) as c:
        bare = c.get(voice_url("chat", mine.turn)), c.get(voice_url("kiosk", kiosks.turn))
        as_person(c, home.alana_token)
        person_on_kiosk = c.get(voice_url("kiosk", kiosks.turn))
        c.cookies.clear()
        as_device(c, KIOSK_TOKEN)
        device_on_chat = c.get(voice_url("chat", mine.turn))
    for r in (*bare, person_on_kiosk, device_on_chat):
        assert r.status_code == 401 and code(r) == "unauthorized"


def test_c15_a_voice_that_cannot_start_is_503_unavailable(home: Home) -> None:
    made = seed(home.url, home.house, alana_thread(home), home.alana.id, spoken=WORDS)
    with real_app(home.url, FakeSpeech(audio=InferenceUnavailable("down"))) as c:
        r = as_person(c, home.alana_token).get(voice_url("chat", made.turn))
    assert r.status_code == 503 and code(r) == "unavailable"


@pytest.mark.parametrize("kind", ["chat", "kiosk"])
def test_c15_conversations_that_cannot_be_read_are_503_unavailable(home: Home, kind: str) -> None:
    device_in(home.url, home.house, KIOSK_TOKEN)
    with real_app(home.url) as c:
        as_device(as_person(c, home.alana_token), KIOSK_TOKEN)
        services.register(Conversations, Conversations.null())
        r = c.get(voice_url(kind, 1))
    assert r.status_code == 503 and code(r) == "unavailable"


def test_c16_the_fetch_log_has_ids_counts_and_timings_and_neither_words_nor_credentials(
        home: Home, capsys: pytest.CaptureFixture[str]) -> None:
    device = device_in(home.url, home.house, KIOSK_TOKEN)
    mine = seed(home.url, home.house, alana_thread(home), home.alana.id, spoken=WORDS)
    kiosks = seed(home.url, home.house, f"device:{device.id}", None, spoken=WORDS)
    with real_app(home.url, FakeSpeech(audio=AUDIO)) as c:
        log = Logged(capsys)
        as_person(c, home.alana_token).get(voice_url("chat", mine.turn))
        as_device(c, KIOSK_TOKEN).get(voice_url("kiosk", kiosks.turn))
        c.get(voice_url("chat", mine.turn + 5000))
        text = log.read()
    by_person, by_device = events(text, "voice.turn")
    assert (by_person["turn"], by_person["by"], by_person["person"]) == (str(mine.turn), "person", str(home.alana.id))
    assert (by_device["turn"], by_device["by"], by_device["device"]) == (str(kiosks.turn), "device", str(device.id))
    for line in (by_person, by_device):
        assert (line["tts_provider"], line["tts_model"], line["bytes"], line["complete"]) == (
            "fake", "fake-tts", str(len(AUDIO)), "true")
        assert int(line["tts_first_byte_ms"]) >= 0
        assert not [k for k in line if k in ("text", "body", "spoken", "token", "cookie")]
    assert "Mowchi" not in text and "keep it down" not in text
    assert home.alana_token not in text and KIOSK_TOKEN not in text, "no credential in the log"
    assert len(events(text, "voice.turn")) == 2, "a 404 starts no stream and logs no fetch"


def test_c17_a_conversation_read_marks_voiced_exactly_on_her_turns_with_a_voice(home: Home) -> None:
    thread = alana_thread(home)
    seed(home.url, home.house, thread, home.alana.id, spoken=WORDS)
    seed(home.url, home.house, thread, home.alana.id, spoken=None)
    seed(home.url, home.house, thread, home.alana.id, spoken="One more.", follows=True)
    with real_app(home.url) as c:
        shown = ChatConversation.model_validate(as_person(c, home.alana_token).get("/api/chat/conversation").json())
    assert [(t.author, t.follows, t.voiced) for t in shown.turns] == [
        ("person", False, False), ("ashley", False, True), ("person", False, False), ("ashley", False, False),
        ("person", False, False), ("ashley", True, True)]


def test_c17_the_kiosks_conversation_read_marks_it_the_same(home: Home) -> None:
    device = device_in(home.url, home.house, KIOSK_TOKEN)
    seed(home.url, home.house, f"device:{device.id}", None, spoken=WORDS)
    seed(home.url, home.house, f"device:{device.id}", None, spoken=None)
    with real_app(home.url) as c:
        shown = ChatConversation.model_validate(as_device(c, KIOSK_TOKEN).get("/api/kiosk/conversation").json())
    assert [(t.author, t.voiced) for t in shown.turns] == [
        ("person", False), ("ashley", True), ("person", False), ("ashley", False)]


def test_c17_the_read_carries_no_voice_text_or_token(home: Home) -> None:
    seed(home.url, home.house, alana_thread(home), home.alana.id, spoken="zqVOICE words")
    with real_app(home.url) as c:
        raw = as_person(c, home.alana_token).get("/api/chat/conversation").text
    assert "zqVOICE" not in raw and "/voice" not in raw
