"""The `job` kind is by_code: only the jobs' runner adds or edits its pieces, with a body of its shape; anyone may remove
it; and the runner's mark survives the command log."""

from dataclasses import replace

from ashley.workshop import job_body, rules as workshop_rules
from ashley.workshop.codec import decode_command, encode_command
from ashley.workshop.commands import Add, Edit, Remove, Undo
from ashley.workshop.decide import EMPTY, Accepted, Refused, decide
from ashley.workshop.model import HER, RUNNER, By, Text

RULES = workshop_rules.load()
BODY = job_body.body_of(job_body.JobBody(None, "agent", "t", "due", None, None, None, (), 0, None))


def added() -> Accepted:
    got = decide(EMPTY, Add(RUNNER, "job", Text("Job", BODY), "small"), RULES)
    assert isinstance(got, Accepted)
    return got


def test_only_the_runner_adds_a_job_piece() -> None:
    added()
    for by in (HER, By(7), By(None, outside=True)):
        got = decide(EMPTY, Add(by, "job", Text("Job", BODY), "small"), RULES)
        assert isinstance(got, Refused) and got.reason == "bad_body"


def test_only_the_runner_edits_it_and_its_body_must_be_a_job_body() -> None:
    state = added().state
    for by in (HER, By(7)):
        got = decide(state, Edit(by, 1, 1, Text("Job", BODY)), RULES)
        assert isinstance(got, Refused) and got.reason == "bad_body"
    assert isinstance(decide(state, Edit(RUNNER, 1, 1, Text("Job", BODY)), RULES), Accepted)
    bad = decide(state, Edit(RUNNER, 1, 1, Text("Job", '{"state": "x"}')), RULES)
    assert isinstance(bad, Refused) and bad.reason == "bad_body"


def test_a_person_may_remove_it_but_not_undo_the_runners_edit() -> None:
    edited = decide(added().state, Edit(RUNNER, 1, 1, Text("Job", BODY.replace('"due"', '"running"'))), RULES)
    assert isinstance(edited, Accepted)
    undone = decide(edited.state, Undo(By(7), edited.seq), RULES)
    assert isinstance(undone, Refused) and undone.reason == "bad_body"
    assert isinstance(decide(edited.state, Remove(By(7), 1), RULES), Accepted)


def test_the_runner_mark_is_logged_with_the_command_and_a_person_cannot_forge_it_in_replay() -> None:
    command = Add(RUNNER, "job", Text("Job", BODY), "small")
    raw = encode_command(command)
    assert raw["runner"] is True
    assert decode_command(raw, By(None)) == command
    plain = encode_command(replace(command, by=HER))
    assert "runner" not in plain and not decode_command(plain, By(None)).by.runner


def test_a_malformed_job_body_is_not_well_formed() -> None:
    assert job_body.well_formed(BODY)
    assert not job_body.well_formed("{}") and not job_body.well_formed("nope")
    assert not job_body.well_formed(BODY.replace('"outputs":[]', '"outputs":["a"]'))
