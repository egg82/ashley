"""`outside.judged` carries the tool, the decision and a reason from the enum, and never the person's words, an argument
or the explanation (design 3.3). Records are read by their fields, which `caplog.text` omits."""

import logging

import pytest
from action_judge_blind_support import EXPLANATION, WORDS, Judged, fields_of, judged_events, free_text_source, prompt_call, run_judged, says
from taint_tiers_blind.taint_tiers_blind_support import PLANT, REASONS




def test_the_scan_sees_a_secret_in_a_record_field() -> None:
    log = logging.getLogger("probe")
    records: list[logging.LogRecord] = []

    class Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    log.addHandler(Keep())
    log.warning("x", extra={"fields": {"words": WORDS}})
    assert WORDS in fields_of(records)


@pytest.mark.parametrize("decision", ["run", "ask"])
def test_outside_judged_has_tool_decision_and_reason_and_none_of_the_words_arguments_or_explanation(
        db_url: str, caplog: pytest.LogCaptureFixture, decision: str) -> None:
    async def body(j: Judged) -> None:
        caplog.set_level(logging.DEBUG)
        reason = "asked_directly" if decision == "run" else "not_asked"
        o = j.outside(free_text_source())
        await o.call(prompt_call(f"{PLANT} do it"))
        [line] = judged_events(caplog.records, "outside.judged")
        assert line["tool"] == "claude_prompt" and line["decision"] == decision and line["reason"] == reason
        assert reason in REASONS and "explanation" not in line and "words" not in line
        assert line.get("tier", "judged") == "judged"
        seen = fields_of(caplog.records) + caplog.text
        for secret in (PLANT, EXPLANATION, WORDS):
            assert secret not in seen, secret

    run_judged(db_url, body, [says(decision, "asked_directly" if decision == "run" else "not_asked")])


def test_a_fault_logs_judge_unavailable_and_no_request_text(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def body(j: Judged) -> None:
        caplog.set_level(logging.DEBUG)
        await j.outside(free_text_source()).call(prompt_call(PLANT))
        [line] = judged_events(caplog.records, "outside.judged")
        assert line["decision"] == "ask" and line["reason"] == "judge_unavailable"
        seen = fields_of(caplog.records) + caplog.text
        assert PLANT not in seen and WORDS not in seen

    from contract.inference_support import fail
    run_judged(db_url, body, [fail("unavailable")])
