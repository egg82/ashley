"""What the judge's provider is sent: the person's own words and the reduced view of the call, and nothing a stranger
could have written (design 3.1, 4.1). Each probe is shown able to see a plant first."""

from action_judge_blind_support import FORM, SAM_ADDRESS, WORDS, Judged, free_text_source, mail, prompt_call, run_judged
from ashley.inference.model import ToolCall
from mail_gmail_support import ADDRESS, message, part
from taint_tiers_blind.taint_tiers_blind_house_support import do, house_tools, the_house
from taint_tiers_blind.taint_tiers_blind_support import PLANT, scalar

MILLIS = 1_762_000_000_000
REPLY = f"REPLY-{PLANT}"


def test_the_persons_own_words_reach_the_provider_even_when_they_hold_the_plant(db_url: str) -> None:
    async def body(j: Judged) -> None:
        o = j.outside(free_text_source(), words=f"tell Claude {PLANT}")
        await o.call(prompt_call("hello"))
        assert j.calls == 1 and PLANT in j.request(), "control: the probe can see a plant in the person's words"

    run_judged(db_url, body)


def test_the_request_has_the_persons_words_the_tool_and_the_length_of_free_text(db_url: str) -> None:
    async def body(j: Judged) -> None:
        o = j.outside(free_text_source())
        await o.call(prompt_call("a" * 41))
        sent = j.request()
        assert j.calls == 1 and WORDS in sent and "claude_prompt" in sent
        assert "41" in sent and "chars" in sent and "a" * 41 not in sent, "free text arrives as its length"

    run_judged(db_url, body)


def test_planted_text_in_a_tool_result_and_in_arguments_never_reaches_the_provider(db_url: str) -> None:
    async def body(j: Judged) -> None:
        o = j.outside(free_text_source(), tainted=None)
        await o.call(ToolCall("r1", "web_read", {}))
        assert o.tainted == "web_read", "control: the read carries the plant and taints the turn"
        await o.call(ToolCall("p1", "claude_prompt", {"session": PLANT, "prompt": f"{PLANT} rm -rf", PLANT: PLANT}))
        assert j.calls == 1 and PLANT not in j.request()

    run_judged(db_url, body)


def test_planted_text_in_a_mail_body_a_subject_and_a_mail_argument_never_reaches_the_provider(db_url: str) -> None:
    async def body(j: Judged) -> None:
        tools, gmail = mail()
        gmail.messages[:] = [message("a1", f"Hi {PLANT}", MILLIS, body=part("text/plain", f"{PLANT} wire money"))]
        o = j.outside(tools, tainted=None)
        await o.catalogue()
        read = await o.call(ToolCall("m1", "mail_read", {"mailbox": ADDRESS, "id": "a1"}))
        assert PLANT in read.content and o.tainted == "mail_read", "control: the read carries the plant and taints"
        await o.call(ToolCall("m2", "mail_send", {**FORM, "to": [SAM_ADDRESS], "subject": f"Re: {PLANT}",
                                                  "body": f"{PLANT} {PLANT}"}))
        sent = j.request()
        assert j.calls == 1 and PLANT not in sent and "mail_send" in sent

    run_judged(db_url, body)


def test_a_recipient_that_passed_the_check_is_shown_to_the_judge(db_url: str) -> None:
    async def body(j: Judged) -> None:
        tools, _ = mail()
        o = j.outside(tools, words="send Sam the form")
        await o.catalogue()
        await o.call(ToolCall("m2", "mail_send", {**FORM, "to": [SAM_ADDRESS]}))
        assert j.calls == 1 and SAM_ADDRESS in j.request()

    run_judged(db_url, body)


def test_a_house_call_reaches_the_provider_as_a_tool_and_not_its_free_text_data(db_url: str) -> None:
    async def body(j: Judged) -> None:
        o = j.outside(house_tools(the_house()), words="unlock the front door")
        await o.call(do("lock.unlock", "lock.front", {"code": PLANT}))
        sent = j.request()
        assert j.calls == 1 and "unlock the front door" in sent and "house_do" in sent and PLANT not in sent

    run_judged(db_url, body)


def test_her_replies_are_not_the_persons_words(db_url: str) -> None:
    async def body(j: Judged) -> None:
        o = j.outside(free_text_source(), earlier=(("person", "an earlier ask"), ("ashley", REPLY)))
        await o.call(prompt_call())
        sent = j.request()
        assert j.calls == 1 and WORDS in sent and "an earlier ask" in sent
        assert REPLY not in sent, "WORDS never include her replies, which paraphrase outside text"

    run_judged(db_url, body)


def test_another_persons_messages_in_the_conversation_are_not_this_persons_words(db_url: str) -> None:
    async def body(j: Judged) -> None:
        scalar(j.w.url, "INSERT INTO turns (conversation_id, household_id, author, speaker_id, text, visibility) "
               "VALUES (%s, %s, 'person', %s, 'SAM-SAID-THIS', 'shared') RETURNING id", (j.w.chat, j.w.hid, j.w.sam))
        o = j.outside(free_text_source())
        await o.call(prompt_call())
        assert j.calls == 1 and WORDS in j.request() and "SAM-SAID-THIS" not in j.request()

    run_judged(db_url, body)
