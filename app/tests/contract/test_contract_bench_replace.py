"""Her bench tools' windowed reads and `bench_replace`, blind: from the tool specs and the Workshop decision, through a
real Postgres Workshop with a 20-character window and a 40-character note."""


from ashley import services
from ashley.tools.bench_tools import BenchTools
from ashley.workshop.commands import Edit, Remove
from ashley.workshop.model import HER, By, Piece, Place, Text
from ashley.workshop.rules import load as load_rules
from ashley.workshop.workshop import BenchClosed, BenchNotFound, Workshop, WorkshopUnavailable
from bench_replace_support import NOTE_MAX, PLAIN, WINDOW, Result, Session, scenario
from bench_tools_support import FakeWorkshop
from contract.conversations_support import run
from ashley.inference.model import ToolCall




def refused(r: Result, code: str) -> None:
    """`r` is an error result that opens with `code`."""
    assert r.is_error and r.raw.startswith(f"{code}:"), r.raw


# --- finding the snippet in the whole body ----------------------------------------------------------------------------

def test_a_snippet_spanning_two_windows_is_found_once_after_reading_one_window(db_url: str) -> None:
    async def check(s: Session) -> None:
        pid = await s.person_adds("doc", PLAIN)
        first = await s.call("bench_read_piece", piece_id=pid)
        v = first.data["version"]
        r = await s.call("bench_replace", piece_id=pid, base_version=v, old=PLAIN[WINDOW - 3:WINDOW + 3], new="<>")
        assert not r.is_error, r.raw
        assert await s.body(pid) == PLAIN[:WINDOW - 3] + "<>" + PLAIN[WINDOW + 3:]

    scenario(db_url, check)


def test_a_snippet_spanning_a_multibyte_character_at_the_window_edge(db_url: str) -> None:
    body = "a" * (WINDOW - 1) + "😀é" + "b" * 20

    async def check(s: Session) -> None:
        pid = await s.person_adds("doc", body)
        v = (await s.call("bench_read_piece", piece_id=pid)).data["version"]
        r = await s.call("bench_replace", piece_id=pid, base_version=v, old="a😀é", new="Z")
        assert not r.is_error, r.raw
        assert await s.body(pid) == "a" * (WINDOW - 2) + "Z" + "b" * 20

    scenario(db_url, check)


def test_a_snippet_once_in_the_window_read_but_twice_in_the_whole_body_is_refused(db_url: str) -> None:
    body = "x" * 5 + "TWICE" + "y" * 20 + "TWICE" + "z" * 5

    async def check(s: Session) -> None:
        pid = await s.person_adds("doc", body)
        v = (await s.call("bench_read_piece", piece_id=pid)).data["version"]
        before = await s.log_len()
        r = await s.call("bench_replace", piece_id=pid, base_version=v, old="TWICE", new="once")
        refused(r, "bad_arguments")
        assert await s.body(pid) == body and await s.version(pid) == v and await s.log_len() == before

    scenario(db_url, check)


def test_replace_after_reading_only_the_last_window_reaches_text_in_the_first(db_url: str) -> None:
    async def check(s: Session) -> None:
        pid = await s.person_adds("doc", PLAIN)
        last = await s.call("bench_read_piece", piece_id=pid, offset=2 * WINDOW)
        assert last.data["body_cut"] is False
        r = await s.call("bench_replace", piece_id=pid, base_version=last.data["version"], old="BCDE", new="-")
        assert not r.is_error, r.raw
        assert await s.body(pid) == PLAIN.replace("BCDE", "-")

    scenario(db_url, check)


def test_zero_matches_an_empty_old_and_several_matches_are_bad_arguments_and_change_nothing(db_url: str) -> None:
    body = "ab-cd-ef-gh-" + "ab" * 3 + "-zz"

    async def check(s: Session) -> None:
        pid = await s.person_adds("doc", body)
        v = (await s.call("bench_read_piece", piece_id=pid)).data["version"]
        before = await s.log_len()
        for old in ("", "nope", "ab", "-", "KL", "AB-"):
            r = await s.call("bench_replace", piece_id=pid, base_version=v, old=old, new="Q")
            refused(r, "bad_arguments")
        assert await s.body(pid) == body and await s.version(pid) == v and await s.log_len() == before

    scenario(db_url, check)


def test_overlapping_matches_count_as_several(db_url: str) -> None:
    async def check(s: Session) -> None:
        pid = await s.person_adds("doc", "x-aaa-y")
        v = (await s.call("bench_read_piece", piece_id=pid)).data["version"]
        r = await s.call("bench_replace", piece_id=pid, base_version=v, old="aa", new="Q")
        refused(r, "bad_arguments")
        assert await s.body(pid) == "x-aaa-y"

    scenario(db_url, check)


def test_an_empty_old_is_refused_even_on_an_empty_body(db_url: str) -> None:
    async def check(s: Session) -> None:
        pid = await s.person_adds("doc", "")
        v = (await s.call("bench_read_piece", piece_id=pid)).data["version"]
        r = await s.call("bench_replace", piece_id=pid, base_version=v, old="", new="Q")
        refused(r, "bad_arguments")
        assert await s.body(pid) == ""

    scenario(db_url, check)


def test_the_match_is_exact_case_and_whitespace_included(db_url: str) -> None:
    async def check(s: Session) -> None:
        pid = await s.person_adds("doc", "Alpha beta\n  gamma")
        v = (await s.call("bench_read_piece", piece_id=pid)).data["version"]
        for old in ("alpha", "beta gamma", "beta\n gamma", "Alpha  beta"):
            r = await s.call("bench_replace", piece_id=pid, base_version=v, old=old, new="Q")
            refused(r, "bad_arguments")
        r = await s.call("bench_replace", piece_id=pid, base_version=v, old="beta\n  gamma", new="Q")
        assert not r.is_error, r.raw
        assert await s.body(pid) == "Alpha Q"

    scenario(db_url, check)


# --- what the replacement writes ---------------------------------------------------------------------------------------

def test_the_new_text_is_spliced_in_literally_and_the_rest_of_the_piece_is_untouched(db_url: str) -> None:
    new = "\\1 $& %s {0} .* \n\t é✓😀 \\g<0>"

    async def check(s: Session) -> None:
        other = await s.person_adds("doc", "other body", title="other")
        pid = await s.person_adds("doc", PLAIN, title="mine")
        v = (await s.call("bench_read_piece", piece_id=pid)).data["version"]
        r = await s.call("bench_replace", piece_id=pid, base_version=v, old="klmn", new=new)
        assert not r.is_error and r.data["piece_id"] == pid and r.data["version"] == v + 1, r.raw
        piece = await s.piece(pid)
        assert piece.text == Text("mine", PLAIN.replace("klmn", new)) and piece.version == v + 1
        assert (await s.piece(other)).text == Text("other", "other body") and (await s.piece(other)).version == 1

    scenario(db_url, check)


def test_an_empty_new_deletes_the_snippet(db_url: str) -> None:
    async def check(s: Session) -> None:
        pid = await s.person_adds("doc", PLAIN)
        v = (await s.call("bench_read_piece", piece_id=pid)).data["version"]
        r = await s.call("bench_replace", piece_id=pid, base_version=v, old="klmnop", new="")
        assert not r.is_error, r.raw
        assert await s.body(pid) == PLAIN.replace("klmnop", "")

    scenario(db_url, check)


def test_a_snippet_may_be_the_whole_body(db_url: str) -> None:
    async def check(s: Session) -> None:
        pid = await s.person_adds("doc", PLAIN)
        v = (await s.call("bench_read_piece", piece_id=pid)).data["version"]
        r = await s.call("bench_replace", piece_id=pid, base_version=v, old=PLAIN, new="short")
        assert not r.is_error, r.raw
        assert await s.body(pid) == "short"

    scenario(db_url, check)


def test_a_body_over_the_kind_cap_is_refused_too_long_and_one_at_the_cap_is_not(db_url: str) -> None:
    body = "head-" + "m" * 6 + "-tail"

    async def check(s: Session) -> None:
        pid = await s.person_adds("note", body)
        v = (await s.call("bench_read_piece", piece_id=pid)).data["version"]
        room = NOTE_MAX - (len(body) - 6)
        r = await s.call("bench_replace", piece_id=pid, base_version=v, old="mmmmmm", new="n" * (room + 1))
        refused(r, "too_long")
        assert await s.body(pid) == body and await s.version(pid) == v
        r = await s.call("bench_replace", piece_id=pid, base_version=v, old="mmmmmm", new="n" * room)
        assert not r.is_error, r.raw
        assert len(await s.body(pid)) == NOTE_MAX

    scenario(db_url, check)


# --- the version she replaces on -------------------------------------------------------------------------------------------

def test_a_piece_she_has_not_read_is_unread_and_nothing_changes(db_url: str) -> None:
    async def check(s: Session) -> None:
        pid = await s.person_adds("doc", PLAIN)
        before = await s.log_len()
        r = await s.call("bench_replace", piece_id=pid, base_version=1, old="klmn", new="Q")
        refused(r, "unread")
        assert await s.body(pid) == PLAIN and await s.log_len() == before

    scenario(db_url, check)


def test_a_new_turn_has_read_nothing(db_url: str) -> None:
    async def check(s: Session) -> None:
        pid = await s.person_adds("doc", PLAIN)
        await s.call("bench_read_piece", piece_id=pid)
        s.new_turn()
        r = await s.call("bench_replace", piece_id=pid, base_version=1, old="klmn", new="Q")
        refused(r, "unread")

    scenario(db_url, check)


def test_a_version_she_never_read_is_unread_even_when_it_is_not_the_one_she_read(db_url: str) -> None:
    async def check(s: Session) -> None:
        pid = await s.person_adds("doc", PLAIN)
        await s.call("bench_read_piece", piece_id=pid)
        r = await s.call("bench_replace", piece_id=pid, base_version=2, old="klmn", new="Q")
        refused(r, "unread")
        assert await s.body(pid) == PLAIN

    scenario(db_url, check)


def test_an_older_version_than_the_piece_has_is_stale_base_until_she_reads_it_again(db_url: str) -> None:
    async def check(s: Session) -> None:
        pid = await s.person_adds("doc", PLAIN)
        await s.call("bench_read_piece", piece_id=pid)
        theirs = Edit(By(s.owner.person_id), pid, 1, Text("t", "their new text: ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
        assert (await s.workshop.apply(s.owner, s.bench_id, theirs)).outcome == "accepted"
        before = await s.log_len()
        r = await s.call("bench_replace", piece_id=pid, base_version=1, old="klmn", new="Q")
        refused(r, "stale_base")
        assert await s.body(pid) == theirs.text.body and await s.log_len() == before
        again = await s.call("bench_read_piece", piece_id=pid)
        assert again.data["version"] == 2
        r = await s.call("bench_replace", piece_id=pid, base_version=2, old="KLMN", new="Q")
        assert not r.is_error, r.raw
        assert await s.body(pid) == theirs.text.body.replace("KLMN", "Q")

    scenario(db_url, check)


def test_a_piece_taken_off_the_bench_after_she_read_it_is_no_such_piece(db_url: str) -> None:
    async def check(s: Session) -> None:
        pid = await s.person_adds("doc", PLAIN)
        await s.call("bench_read_piece", piece_id=pid)
        assert (await s.workshop.apply(s.owner, s.bench_id, Remove(By(s.owner.person_id), pid))).outcome == "accepted"
        r = await s.call("bench_replace", piece_id=pid, base_version=1, old="klmn", new="Q")
        refused(r, "no_such_piece")

    scenario(db_url, check)


# --- it is an ordinary Edit ---------------------------------------------------------------------------------------------

def test_the_log_holds_an_ordinary_edit_by_her_with_the_whole_new_body(db_url: str) -> None:
    async def check(s: Session) -> None:
        pid = await s.person_adds("doc", PLAIN, title="the title")
        v = (await s.call("bench_read_piece", piece_id=pid)).data["version"]
        r = await s.call("bench_replace", piece_id=pid, base_version=v, old="klmn", new="Q")
        rows = await s.workshop.log(s.owner, s.bench_id)
        last = rows[-1]
        assert last.seq == r.data["seq"] and last.outcome == "accepted" and last.piece_id == pid
        assert last.command == Edit(HER, pid, v, Text("the title", PLAIN.replace("klmn", "Q")))

    scenario(db_url, check)


def test_undoing_a_replace_restores_the_exact_body(db_url: str) -> None:
    body = "é✓😀 " + PLAIN + "\r\n  trailing  "

    async def check(s: Session) -> None:
        pid = await s.person_adds("doc", body)
        v = (await s.call("bench_read_piece", piece_id=pid)).data["version"]
        r = await s.call("bench_replace", piece_id=pid, base_version=v, old="klmn", new="")
        assert not r.is_error and await s.body(pid) != body
        u = await s.call("bench_undo", seq=r.data["seq"])
        assert not u.is_error, u.raw
        piece = await s.piece(pid)
        assert piece.text == Text("t", body) and piece.version == v + 2

    scenario(db_url, check)


def test_a_replace_is_refused_by_the_same_undo_rule_once_something_changed_after_it(db_url: str) -> None:
    async def check(s: Session) -> None:
        pid = await s.person_adds("doc", PLAIN)
        v = (await s.call("bench_read_piece", piece_id=pid)).data["version"]
        r = await s.call("bench_replace", piece_id=pid, base_version=v, old="klmn", new="Q")
        later = Edit(By(s.owner.person_id), pid, v + 1, Text("t", "later"))
        assert (await s.workshop.apply(s.owner, s.bench_id, later)).outcome == "accepted"
        u = await s.call("bench_undo", seq=r.data["seq"])
        assert u.is_error and u.raw.startswith("changed_since:"), u.raw
        assert await s.body(pid) == "later"

    scenario(db_url, check)


# --- errors are results ------------------------------------------------------------------------------------------------------

def test_bad_arguments_never_reach_the_workshop_and_a_workshop_fault_is_an_error_result() -> None:
    piece = Piece(1, "document", Text("T", PLAIN), 1, Place(0, "small"), 1)
    fake = FakeWorkshop(pieces=(piece,))
    services.register(Workshop, fake)
    tools = BenchTools(1, 2, 3)

    async def call(**args: object) -> Result:
        out = await tools.call(ToolCall("c", "bench_replace", args))
        return Result(out.is_error, {}, out.content)

    async def go() -> None:
        await tools.call(ToolCall("r", "bench_read_piece", {"piece_id": 1}))
        for args in ({}, {"piece_id": "1", "base_version": 1, "old": "klmn", "new": "Q"},
                     {"piece_id": 1, "base_version": 1, "old": 5, "new": "Q"},
                     {"piece_id": 1, "base_version": 1, "old": "klmn"},
                     {"piece_id": 1, "base_version": 1, "old": "klmn", "new": "Q", "extra": 1},
                     {"piece_id": 1, "base_version": 1, "old": "", "new": "Q"},
                     {"piece_id": 1, "base_version": 1, "old": "nope", "new": "Q"}):
            r = await call(**args)
            assert r.is_error and r.raw.startswith("bad_arguments:"), (args, r.raw)
        assert fake.applied == []
        ok = await call(piece_id=1, base_version=1, old="klmn", new="Q")
        assert not ok.is_error
        assert [c for _, _, c in fake.applied] == [Edit(HER, 1, 1, Text("T", PLAIN.replace("klmn", "Q")))]
        for fault in (WorkshopUnavailable(), BenchClosed(), BenchNotFound()):
            fake.raises = fault
            assert (await call(piece_id=1, base_version=1, old="klmn", new="Q")).is_error

    run(go())


# --- the code kind ------------------------------------------------------------------------------------------------------------

def test_the_shipped_code_kind_is_a_stored_code_format_kind() -> None:
    kind = load_rules().kinds["code"]
    assert kind.family == "stored" and kind.format == "code" and kind.language is not None


def test_code_goes_in_through_bench_add_verbatim_and_can_be_changed_by_replace(db_url: str) -> None:
    source = "def f(x):\n    return x  # \"ok\" ```\n"

    async def check(s: Session) -> None:
        added = await s.call("bench_add", kind="code", title="f.py", body=source)
        assert not added.is_error, added.raw
        pid = added.data["piece_id"]
        assert (await s.piece(pid)).kind == "code" and await s.body(pid) == source
        v = added.data["version"]
        r = await s.call("bench_replace", piece_id=pid, base_version=v, old="return x", new="return x + 1")
        assert not r.is_error, r.raw
        assert await s.body(pid) == source.replace("return x", "return x + 1")

    scenario(db_url, check)
