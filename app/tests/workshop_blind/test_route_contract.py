"""The workshop's routes from `openapi.json`: who may call them, the declared status of each outcome, a refused command
as 409 with its reason, and what Live is told."""

import json
from collections.abc import Generator, Mapping
from pathlib import Path
from typing import Any

import pytest
from ashley import services
from ashley.api.models import ChatConversation, ChatReply, ErrorResponse
from ashley.api.workshop_models import BenchDetail, BenchList, BenchSummary, CommandRefused, WorkshopKinds
from ashley.live.events import BenchChanged, Shown
from ashley.workshop.commands import REASONS
from ashley.workshop.model import SIZES
from ashley.workshop.workshop import Workshop
from respond_support import Fakes, wired as wired
from route_support import Rig, build
from service_support import changed, rows

SHIPPED = Path(__file__).resolve().parents[2] / "ashley" / "workshop"
BODY = "PLANTED-BODY-r5"


@pytest.fixture
def rig(db_url: str, wired: Fakes) -> Generator[Rig]:
    made = build(db_url, wired)
    with made.client:
        yield made


def new_bench(rig: Rig, title: str = "bench") -> int:
    got = rig.post("/api/benches", {"title": title})
    assert got.status == 200
    return int(BenchSummary.model_validate(got.json).id)


def command(rig: Rig, bench_id: int, body: Mapping[str, object]) -> tuple[int, dict[str, Any]]:
    got = rig.post(f"/api/benches/{bench_id}/commands", body)
    return got.status, got.json


def add_body(title: str = "a", text: str = "", kind: str = "note", size: str = "small") -> dict[str, object]:
    return {"type": "add", "kind": kind, "title": title, "body": text, "size": size}


def detail(rig: Rig, bench_id: int) -> BenchDetail:
    got = rig.get(f"/api/benches/{bench_id}")
    assert got.status == 200
    return BenchDetail.model_validate(got.json)


def err(got: tuple[int, dict[str, object]] | object) -> str:
    assert isinstance(got, tuple)
    return ErrorResponse.model_validate(got[1]).code


# --- the kinds ---------------------------------------------------------------------------------------------------


def test_the_kinds_route_serves_what_the_data_files_hold(rig: Rig) -> None:
    got = WorkshopKinds.model_validate(rig.get("/api/workshop/kinds").json)
    kinds = json.loads((SHIPPED / "kinds.json").read_text())
    limits = json.loads((SHIPPED / "workshop.json").read_text())
    assert {k.name: (k.family, k.label, k.max_chars) for k in got.kinds} == {
        n: (k["family"], k["label"], k["max_chars"]) for n, k in kinds.items() if k["family"] != "screen"}
    assert (got.max_pieces, got.title_max_chars, got.sizes) == (limits["max_pieces"], limits["title_max_chars"], list(SIZES))


# --- signed out, cross-site, unavailable ---------------------------------------------------------------------------

ROUTES = [("GET", "/api/workshop/kinds", None), ("GET", "/api/benches", None), ("POST", "/api/benches", {"title": "x"}),
          ("GET", "/api/benches/1", None), ("POST", "/api/benches/1/close", None),
          ("POST", "/api/benches/1/commands", {"type": "remove", "piece_id": 1}),
          ("POST", "/api/benches/1/messages", {"text": "hi"}), ("GET", "/api/benches/1/conversation", None)]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_signed_out_is_401_on_every_route(db_url: str, wired: Fakes, method: str, path: str, body: object) -> None:
    with build(db_url, wired, signed_in=False).client as client:
        response = client.request(method, path, json=body)
    assert response.status_code == 401 and ErrorResponse.model_validate(response.json()).code == "unauthorized"
    assert rows(db_url, "benches") == 0 and wired.conversations.calls == []


@pytest.mark.parametrize(("method", "path", "body"), [r for r in ROUTES if r[0] == "POST"])
def test_a_write_from_another_site_is_403_and_changes_nothing(db_url: str, wired: Fakes, method: str, path: str,
                                                                body: object) -> None:
    made = build(db_url, wired, signed_in=False)
    with made.client as client:
        response = client.request(method, path, json=body, headers={"origin": "https://evil.test"})
    assert response.status_code == 403 and ErrorResponse.model_validate(response.json()).code == "forbidden"
    assert rows(db_url, "benches") == 0 and wired.conversations.calls == [] and made.live.published == []


@pytest.mark.parametrize(("method", "path", "body"), [r for r in ROUTES if r[1] != "/api/workshop/kinds"
                                                       and "messages" not in r[1] and "conversation" not in r[1]])
def test_an_unreachable_workshop_is_503_unavailable(rig: Rig, method: str, path: str, body: object) -> None:
    services.register(Workshop, Workshop.null())
    got = rig.client.request(method, path, json=body)
    assert got.status_code == 503 and ErrorResponse.model_validate(got.json()).code == "unavailable"


# --- open, list, close, read --------------------------------------------------------------------------------------


def test_open_returns_the_new_bench_and_list_has_it(rig: Rig) -> None:
    got = BenchSummary.model_validate(rig.post("/api/benches", {"title": "x" * 120}).json)
    assert got.title == "x" * 120 and got.closed_at is None and got.thread == f"bench:{got.id}"
    assert [b.id for b in BenchList.model_validate(rig.get("/api/benches").json).benches] == [got.id]


@pytest.mark.parametrize("body", [{}, {"title": ""}, {"title": "   "}, {"title": "x" * 121}, {"title": "a", "x": 1},
                                  {"title": 5}, {"title": None}])
def test_a_bad_bench_request_is_422_and_opens_nothing(rig: Rig, body: object, db_url: str) -> None:
    assert rig.post("/api/benches", body).status == 422
    assert rows(db_url, "benches") == 0


def test_the_list_is_the_persons_own_open_benches_newest_first(rig: Rig) -> None:
    first, second, third = new_bench(rig, "1"), new_bench(rig, "2"), new_bench(rig, "3")
    rig.post(f"/api/benches/{second}/close")
    rig.as_("sam")
    theirs = new_bench(rig, "s")
    rig.as_("zed")
    far = new_bench(rig, "z")
    rig.as_("alana")

    def ids() -> list[int]:
        return [b.id for b in BenchList.model_validate(rig.get("/api/benches").json).benches]

    assert ids() == [third, first]
    rig.as_("sam")
    assert ids() == [theirs]
    rig.as_("zed")
    assert ids() == [far]


def test_close_closes_it_once_and_a_closed_bench_still_reads(rig: Rig) -> None:
    bench_id = new_bench(rig)
    command(rig, bench_id, add_body("a", BODY))
    first = BenchSummary.model_validate(rig.post(f"/api/benches/{bench_id}/close").json)
    again = BenchSummary.model_validate(rig.post(f"/api/benches/{bench_id}/close").json)
    assert first.closed_at is not None and again == first
    got = detail(rig, bench_id)
    assert got.bench == first and [p.body for p in got.pieces] == [BODY] and len(got.recent) == 1


def test_a_bench_that_is_not_the_persons_is_404_whoever_asks_and_however_it_is_asked(rig: Rig) -> None:
    bench_id = new_bench(rig)
    command(rig, bench_id, add_body("a"))
    before = detail(rig, bench_id)
    for who in ("sam", "zed"):
        rig.as_(who)
        for got in (rig.get(f"/api/benches/{bench_id}"), rig.post(f"/api/benches/{bench_id}/close"),
                    rig.post(f"/api/benches/{bench_id}/commands", add_body("x")),
                    rig.post(f"/api/benches/{bench_id}/messages", {"text": "hi"}),
                    rig.get(f"/api/benches/{bench_id}/conversation"), rig.get(f"/api/benches/{bench_id + 99}")):
            assert got.status == 404 and ErrorResponse.model_validate(got.json).code == "not_found"
    rig.as_("alana")
    assert detail(rig, bench_id) == before and changed(rig.live)[0].seq == 1 and len(changed(rig.live)) == 1
    assert rig.fakes.conversations.calls == []


@pytest.mark.parametrize("path", ["/api/benches/x", "/api/benches/1.5", "/api/benches/x/conversation"])
def test_a_bench_id_that_is_not_a_number_is_422(rig: Rig, path: str) -> None:
    assert rig.get(path).status == 422


# --- commands -------------------------------------------------------------------------------------------------------


def test_each_command_type_is_accepted_and_the_bench_shows_it(rig: Rig) -> None:
    b = new_bench(rig)
    assert command(rig, b, add_body("a", "x")) == (200, {"seq": 1, "piece_id": 1})
    assert command(rig, b, add_body("b", "y", "document", "large"))[0] == 200
    assert command(rig, b, {"type": "edit", "piece_id": 1, "base_version": 1, "title": "c", "body": "z"}) == (
        200, {"seq": 3, "piece_id": 1})
    assert command(rig, b, {"type": "move", "piece_id": 2, "placement": {"order": 0, "size": "full"}}) == (
        200, {"seq": 4, "piece_id": 2})
    assert command(rig, b, {"type": "undo", "seq": 3}) == (200, {"seq": 5, "piece_id": 1})
    assert command(rig, b, {"type": "remove", "piece_id": 1}) == (200, {"seq": 6, "piece_id": 1})
    got = detail(rig, b)
    assert [(p.id, p.kind, p.title, p.body, p.piece_version, p.placement.order, p.placement.size, p.changed_by) for p in got.pieces] == [
        (2, "document", "b", "y", 1, 0, "full", 4)]
    assert [(r.seq, r.type, r.outcome, r.author, r.piece_id) for r in got.recent] == [
        (i + 1, t, "accepted", "person", p) for i, (t, p) in enumerate(
            [("add", 1), ("add", 2), ("edit", 1), ("move", 2), ("undo", 1), ("remove", 1)])]
    assert [r.person_id for r in got.recent] == [rig.w.alana.person_id] * 6


REFUSALS = [("unknown_kind", add_body(kind="hologram")), ("bad_title", add_body(title="")),
            ("bad_title", add_body(title="   ")), ("too_long", add_body(text="x" * 4001)),
            ("no_such_piece", {"type": "remove", "piece_id": 9}),
            ("no_such_piece", {"type": "move", "piece_id": 9, "placement": {"order": 0, "size": "small"}}),
            ("no_such_piece", {"type": "edit", "piece_id": 9, "base_version": 1, "title": "a", "body": ""}),
            ("bad_place", {"type": "move", "piece_id": 1, "placement": {"order": 1, "size": "small"}}),
            ("stale_base", {"type": "edit", "piece_id": 1, "base_version": 1, "title": "a", "body": ""}),
            ("nothing_to_undo", {"type": "undo", "seq": 99}), ("nothing_to_undo", {"type": "undo", "seq": 0}),
            ("changed_since", {"type": "undo", "seq": 1}), ("bad_wake", add_body(kind="wake", text="not a rule")),
            ("bad_facts", add_body(kind="facts", text="not facts")),
            ("bad_body", add_body(kind="job")), ("bad_session", add_body(kind="session", text="not a session"))]


@pytest.mark.parametrize(("why", "body"), REFUSALS)
def test_a_refused_command_is_409_with_its_reason_and_is_logged_as_the_next_seq(rig: Rig, why: str, body: dict[str, object]) -> None:
    b = new_bench(rig)
    command(rig, b, add_body("a"))
    command(rig, b, {"type": "edit", "piece_id": 1, "base_version": 1, "title": "e", "body": ""})
    before = detail(rig, b).pieces
    status, raw = command(rig, b, body)
    refused = CommandRefused.model_validate(raw)
    assert status == 409 and (refused.code, refused.reason, refused.seq) == ("refused", why, 3)
    after = detail(rig, b)
    assert after.pieces == before and (after.recent[-1].seq, after.recent[-1].outcome, after.recent[-1].piece_id) == (3, why, None)
    assert command(rig, b, add_body("b"))[1] == {"seq": 4, "piece_id": 4}


def test_every_reason_the_contract_names_is_reachable_through_a_route() -> None:
    # `not_runnable` is the run route's (test_bench_run_route.py); an automation piece's are the install route's and
    # her tools' (test_workshop_install_routes.py, test_bench_automations.py).
    # `bad_site` and `bad_video` are test_workshop_embed_routes.py's.
    installs = {"bad_automation", "not_installable", "incomplete", "no_proposal", "needs_person"}
    embeds = {"bad_site", "bad_video"}
    cues = {"not_video", "bad_cue"}   # a cue has no route: hers alone, test_workshop_cue_postgres.py
    points = {"bad_reader", "not_reader", "bad_passage"}   # bad_reader is test_workshop_reader_routes.py's; a point has no route
    files = {"bad_file"}   # test_bench_files_routes.py's
    screens = {"bad_controls", "already_shown", "required"}   # a screen's, test_screen_decide.py
    hers = {"confirmed_measurement", "bad_citation"}   # her edits only, never a person's route: test_facts.py, test_choice_rows.py
    recipes = {"bad_recipe"}   # test_workshop_recipe_routes.py's
    surfaced = {"bad_rows"}   # a Surfaced has no route of its own: test_workshop_surfaced.py
    assert ({why for why, _ in REFUSALS} | {"full", "not_runnable"} | installs | embeds | cues | points | files | screens
            | hers | recipes | surfaced == set(REASONS))


def test_a_full_bench_is_409_full_at_the_shipped_limit(rig: Rig) -> None:
    b = new_bench(rig)
    limit = WorkshopKinds.model_validate(rig.get("/api/workshop/kinds").json).max_pieces
    for _ in range(limit):
        assert command(rig, b, add_body("p"))[0] == 200
    status, raw = command(rig, b, add_body("p"))
    assert status == 409 and CommandRefused.model_validate(raw).reason == "full"


BAD = [{}, {"type": "paint"}, {"type": "remove"}, {"type": "remove", "piece_id": "x"}, {"type": "remove", "piece_id": 1, "x": 1},
       {"type": "undo", "seq": None}, add_body(size="huge"), add_body(title="t" * 121), add_body(text="x" * 200001),
       add_body(kind=""), add_body(kind="k" * 65), {**add_body(), "by": 5},
       {"type": "move", "piece_id": 1, "placement": {"order": -1, "size": "small"}},
       {"type": "move", "piece_id": 1, "placement": {"order": 0}}, {"type": "edit", "piece_id": 1, "base_version": [1],
                                                              "title": "a", "body": ""}]


@pytest.mark.parametrize("body", BAD)
def test_a_body_outside_the_command_models_is_422_and_logs_nothing(rig: Rig, body: object) -> None:
    b = new_bench(rig)
    assert rig.post(f"/api/benches/{b}/commands", body).status == 422
    assert detail(rig, b).recent == [] and rig.live.published == []


def test_a_closed_bench_takes_no_command_410_and_logs_nothing(rig: Rig) -> None:
    b = new_bench(rig)
    command(rig, b, add_body("a"))
    rig.post(f"/api/benches/{b}/close")
    for body in (add_body("b"), add_body(kind="hologram"), {"type": "undo", "seq": 1}):
        status, raw = command(rig, b, body)
        assert status == 410 and ErrorResponse.model_validate(raw).code == "closed"
    assert len(detail(rig, b).recent) == 1 and len(changed(rig.live)) == 1
    got = rig.post(f"/api/benches/{b}/messages", {"text": "hi"})
    assert got.status == 410 and ErrorResponse.model_validate(got.json).code == "closed"


def test_the_recent_commands_never_carry_what_a_piece_says(rig: Rig) -> None:
    b = new_bench(rig)
    command(rig, b, add_body("a", BODY))
    command(rig, b, add_body("a", BODY, kind="hologram"))
    raw = rig.get(f"/api/benches/{b}").json
    assert BODY not in json.dumps(raw["recent"]) and BODY in json.dumps(raw["pieces"])


# --- Live -----------------------------------------------------------------------------------------------------------


def test_live_gets_the_bench_and_seq_to_the_owner_after_an_accepted_command_and_nothing_after_a_refusal(rig: Rig) -> None:
    b = new_bench(rig)
    assert rig.live.published == []
    command(rig, b, add_body("a"))
    command(rig, b, add_body(kind="hologram"))
    command(rig, b, add_body("c"))
    command(rig, b, {"type": "paint"})
    rig.as_("sam")
    command(rig, b, add_body("d"))
    owner = Shown(rig.w.alana.household_id, rig.w.alana.person_id)
    assert rig.live.published == [BenchChanged(owner, b, 1, "person"), BenchChanged(owner, b, 3, "person")]


# --- the bench's talk --------------------------------------------------------------------------------------------------


def test_the_bench_message_route_talks_on_the_bench_thread(rig: Rig) -> None:
    from ashley.inference.reply import Reply
    rig.fakes.inference.script = [Reply(spoken="Done.", text="Done!")]
    b = new_bench(rig)
    got = rig.post(f"/api/benches/{b}/messages", {"text": "hello"})
    assert got.status == 200 and ChatReply.model_validate(got.json).body == "Done!"
    [call] = [c for c in rig.fakes.conversations.calls if c[0] == "for_thread"]
    assert call[1] == (rig.w.alana.household_id, f"bench:{b}", "brainstorm", (rig.w.alana.person_id,))
    talk = ChatConversation.model_validate(rig.get(f"/api/benches/{b}/conversation").json)
    assert talk.thread == f"bench:{b}" and [t.text for t in talk.turns][:1] == ["hello"]


def test_an_empty_message_is_422_and_starts_no_conversation(rig: Rig) -> None:
    b = new_bench(rig)
    assert rig.post(f"/api/benches/{b}/messages", {"text": ""}).status == 422
    assert rig.fakes.conversations.calls == []


# --- edges through the routes --------------------------------------------------------------------------------------

HUGE = 2 ** 70


@pytest.mark.parametrize("path", [f"/api/benches/{HUGE}", f"/api/benches/-{HUGE}", f"/api/benches/{2 ** 63}"])
def test_a_bench_id_no_database_integer_holds_is_404_or_422_never_a_crash(rig: Rig, path: str) -> None:
    assert rig.get(path).status in (404, 422)
    assert rig.post(path + "/close").status in (404, 422)
    assert rig.post(path + "/commands", add_body()).status in (404, 422)


def test_numbers_no_database_integer_holds_in_a_command_are_refused_by_reason(rig: Rig) -> None:
    b = new_bench(rig)
    command(rig, b, add_body("a"))
    bodies = [{"type": "remove", "piece_id": HUGE}, {"type": "undo", "seq": -HUGE}, {"type": "undo", "seq": HUGE},
              {"type": "edit", "piece_id": 1, "base_version": HUGE, "title": "a", "body": ""},
              {"type": "move", "piece_id": 1, "placement": {"order": HUGE, "size": "small"}}]
    got = [command(rig, b, body) for body in bodies]
    assert [s for s, _ in got] == [409] * 5
    assert [CommandRefused.model_validate(raw).reason for _, raw in got] == [
        "no_such_piece", "nothing_to_undo", "nothing_to_undo", "stale_base", "bad_place"]


@pytest.mark.parametrize("title", [" ", "　", "  "])
def test_a_title_of_unicode_whitespace_is_refused_like_any_blank_one(rig: Rig, title: str) -> None:
    assert rig.post("/api/benches", {"title": title}).status == 422
    b = new_bench(rig)
    status, raw = command(rig, b, add_body(title=title))
    assert status == 409 and CommandRefused.model_validate(raw).reason == "bad_title"


def test_an_unknown_kind_at_the_longest_name_and_a_document_at_its_longest_body(rig: Rig) -> None:
    b = new_bench(rig)
    status, raw = command(rig, b, add_body(kind="k" * 64))
    assert status == 409 and CommandRefused.model_validate(raw).reason == "unknown_kind"
    big = "ü" * 200000
    assert command(rig, b, add_body("a", big, "document"))[0] == 200
    assert detail(rig, b).pieces[0].body == big


def test_a_nul_in_a_body_is_422(rig: Rig) -> None:
    b = new_bench(rig)
    status, _ = command(rig, b, add_body("a", "a\u0000b", "document"))
    assert status == 422
