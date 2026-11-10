"""A bench message with a paste: the paste goes on the bench as a document piece first and the message names it by
`piece_id`, which must be a piece of that bench (else 422 `refused`); a bench message takes no `attachment`."""

from ashley.people.model import Person
from bq_routes import Json, Site
from bq_support import reply
from respond_support import ALANA, SAM

TYPED = "make this the plan please"
BODY = "Long pasted text with a very particular phrase: kumquat-9"


def talk(site: Site, bench: int, body: Json, who: Person = ALANA) -> tuple[int, Json]:
    response = site.as_(who).post(f"/api/benches/{bench}/messages", json=body)
    return response.status_code, response.json()


def nothing_happened(site: Site) -> bool:
    return site.wired.inference.prompts == [] and not site.wired.conversations.added


def test_a_message_naming_the_pasted_piece_is_answered_and_she_is_told_of_it(site: Site) -> None:
    site.wired.inference.script = [reply(20)]
    bench = site.bench(ALANA)
    piece = site.put_piece(ALANA, bench, "Kumquat notes", BODY)
    status, got = talk(site, bench, {"text": TYPED, "piece_id": piece})
    assert status == 200 and got["body"]
    seen = repr(site.wired.inference.prompts[0].messages)
    assert TYPED in seen and "Kumquat notes" in seen and str(piece) in seen
    assert BODY not in seen


def test_the_piece_named_is_the_one_she_is_told_of(site: Site) -> None:
    site.wired.inference.script = [reply(20)]
    bench = site.bench(ALANA)
    first = site.put_piece(ALANA, bench, "First thing", "a")
    second = site.put_piece(ALANA, bench, "Second thing", "b")
    assert talk(site, bench, {"text": TYPED, "piece_id": second})[0] == 200
    seen = repr(site.wired.inference.prompts[0].messages)
    assert "Second thing" in seen and "First thing" not in seen and first != second


def test_a_message_naming_no_piece_tells_her_of_none(site: Site) -> None:
    site.wired.inference.script = [reply(20)]
    bench = site.bench(ALANA)
    site.put_piece(ALANA, bench, "Kumquat notes", BODY)
    assert talk(site, bench, {"text": TYPED})[0] == 200
    assert "Kumquat notes" not in repr(site.wired.inference.prompts[0].messages)


def test_a_piece_of_another_bench_of_the_same_person_is_refused(site: Site) -> None:
    site.wired.inference.script = [reply(20)]
    here, there = site.bench(ALANA, "here"), site.bench(ALANA, "there")
    elsewhere = site.put_piece(ALANA, there, "Elsewhere piece", "x")
    site.put_piece(ALANA, here, "Local piece", "y")
    status, got = talk(site, here, {"text": TYPED, "piece_id": elsewhere + 100})
    assert (status, got["code"]) == (422, "refused")
    nothing = nothing_happened(site)
    status, got = talk(site, here, {"text": TYPED, "piece_id": 9999})
    assert (status, got["code"]) == (422, "refused") and nothing and nothing_happened(site)


def test_a_piece_id_that_is_on_another_bench_only_is_refused(site: Site) -> None:
    site.wired.inference.script = [reply(20)]
    here, there = site.bench(ALANA, "here"), site.bench(ALANA, "there")
    site.put_piece(ALANA, there, "a", "x")
    only_there = site.put_piece(ALANA, there, "b", "y")
    assert only_there > 1
    status, got = talk(site, here, {"text": TYPED, "piece_id": only_there})
    assert (status, got["code"]) == (422, "refused") and nothing_happened(site)


def test_another_persons_piece_is_refused_and_leaks_nothing(site: Site) -> None:
    site.wired.inference.script = [reply(20)]
    mine, sams = site.bench(ALANA), site.bench(SAM)
    theirs = site.put_piece(SAM, sams, "Sam private title", "sam private body")
    assert theirs >= 1
    status, got = talk(site, mine, {"text": TYPED, "piece_id": theirs})
    assert (status, got["code"]) == (422, "refused") and nothing_happened(site)
    assert "Sam private" not in str(got)


def test_a_bench_message_carrying_an_attachment_is_refused_and_nothing_happens(site: Site) -> None:
    site.wired.inference.script = [reply(20)]
    bench = site.bench(ALANA)
    piece = site.put_piece(ALANA, bench)
    for body in ({"text": TYPED, "attachment": {"text": "pasted"}},
                 {"text": TYPED, "attachment": {"title": "T", "text": "pasted"}, "piece_id": piece},
                 {"text": TYPED, "attachment": None, "extra": 1}):
        assert talk(site, bench, body)[0] == 422, body
    assert nothing_happened(site)


def test_a_piece_id_that_is_not_positive_is_refused(site: Site) -> None:
    site.wired.inference.script = [reply(20)]
    bench = site.bench(ALANA)
    for bad in (0, -1):
        assert talk(site, bench, {"text": TYPED, "piece_id": bad})[0] == 422
    assert nothing_happened(site)


def test_a_piece_taken_off_the_bench_is_not_on_it(site: Site) -> None:
    site.wired.inference.script = [reply(20)]
    bench = site.bench(ALANA)
    piece = site.put_piece(ALANA, bench)
    removed = site.as_(ALANA).post(f"/api/benches/{bench}/commands", json={"type": "remove", "piece_id": piece})
    assert removed.status_code == 200
    status, got = talk(site, bench, {"text": TYPED, "piece_id": piece})
    assert (status, got["code"]) == (422, "refused") and nothing_happened(site)
