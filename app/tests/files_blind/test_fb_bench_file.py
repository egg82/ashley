"""`add_file`: the bytes judged and kept, then an ordinary Add of an image or file piece that names them; and the
Workshop's refusals (`bad_file`) of a large piece made any other way or changed in its body."""

import dataclasses
import logging

import pytest
from ashley.files.intake import Refused, key_of
from ashley.files.store import StoreUnavailable
from ashley.workshop import rules as workshop_rules
from ashley.workshop.bench_file import add_file, needs_bytes
from ashley.workshop.commands import Add, Edit, Undo
from ashley.workshop.model import HER, Text
from ashley.workshop.stored_file import file_of
from files_blind_support import CONFIG, log_text, HTML, PNG, TEXT, PDF, FakeStore, by, env, go as run, sha

RULES = workshop_rules.load()


def test_only_the_large_kinds_need_bytes() -> None:
    assert needs_bytes(RULES, "image") and needs_bytes(RULES, "file")
    assert not any(needs_bytes(RULES, k) for k in ("note", "document", "code"))


def test_an_image_is_added_last_as_an_image_piece_titled_by_its_name(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = (await e.workshop.open(a, "b")).id
            first = await e.workshop.apply(a, bench, Add(by(a), "note", Text("n", "x"), "small"))
            stored, applied = await add_file(a, bench, by(a), PNG, "pic.png", "image/png", RULES)
            assert applied.outcome == "accepted" and applied.piece_id is not None
            view = await e.workshop.read(a, bench)
            assert [p.id for p in view.pieces] == [first.piece_id, applied.piece_id]
            piece = view.pieces[-1]
            assert (piece.kind, piece.text.title) == ("image", "pic.png")
            f = file_of(piece.text.body)
            assert f is not None and (f.sha256, f.size, f.media_type, f.name) == (sha(PNG), len(PNG), "image/png", "pic.png")
            assert (stored.sha256, stored.size, stored.media_type) == (f.sha256, f.size, f.media_type)
            assert e.store.held == {key_of(a.household_id, sha(PNG)): PNG}

    run(scenario())


@pytest.mark.parametrize(("data", "name", "declared", "media"), [(PDF, "r.pdf", "", "application/pdf"), (TEXT, "n.txt", "text/plain", "text/plain"),
                                                                  (HTML, "p.html", "text/html", "text/plain")])
def test_anything_else_is_a_file_piece_of_the_type_its_bytes_are(db_url: str, data: bytes, name: str, declared: str, media: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = (await e.workshop.open(a, "b")).id
            await add_file(a, bench, by(a), data, name, declared, RULES)
            piece = (await e.workshop.read(a, bench)).pieces[0]
            f = file_of(piece.text.body)
            assert piece.kind == "file" and f is not None and f.media_type == media and piece.text.title == name

    run(scenario())


def test_the_add_is_the_persons_or_hers_logged_live_and_undoable(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = (await e.workshop.open(a, "b")).id
            _, mine = await add_file(a, bench, by(a), PNG, "p.png", "", RULES)
            _, hers = await add_file(a, bench, HER, TEXT, "t.txt", "", RULES)
            rows = await e.workshop.log(a, bench)
            assert [(r.by.author, r.outcome) for r in rows] == [("person", "accepted"), ("ashley", "accepted")]
            assert len(e.live.published) >= 2
            await e.workshop.apply(a, bench, Undo(by(a), hers.seq))
            assert [p.id for p in (await e.workshop.read(a, bench)).pieces] == [mine.piece_id]

    run(scenario())


@pytest.mark.parametrize(("data", "reason"), [(b"", "empty"), (b"\x00\xff", "type_not_allowed")])
def test_a_refused_file_adds_no_piece_and_stores_nothing(db_url: str, data: bytes, reason: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = (await e.workshop.open(a, "b")).id
            with pytest.raises(Refused) as r:
                await add_file(a, bench, by(a), data, "x", "", RULES)
            assert r.value.reason == reason
            assert (await e.workshop.read(a, bench)).pieces == () or not (await e.workshop.read(a, bench)).pieces
            assert e.store.held == {} and await e.workshop.log(a, bench) == []

    run(scenario())


def test_a_mismatched_declared_type_is_refused(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = (await e.workshop.open(a, "b")).id
            with pytest.raises(Refused) as r:
                await add_file(a, bench, by(a), PNG, "x.pdf", "application/pdf", RULES)
            assert r.value.reason == "type_mismatch"

    run(scenario())


def test_the_limit_given_by_the_config_applies(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = (await e.workshop.open(a, "b")).id
            tiny = dataclasses.replace(CONFIG, max_bytes=len(TEXT) - 1)
            with pytest.raises(Refused) as r:
                await add_file(a, bench, by(a), TEXT, "t.txt", "", RULES, tiny)
            assert r.value.reason == "too_large"
            await add_file(a, bench, by(a), TEXT, "t.txt", "", RULES, dataclasses.replace(CONFIG, max_bytes=len(TEXT)))

    run(scenario())


def test_an_unreachable_store_adds_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url, FakeStore(down=True)) as e:
            a = e.world.alana
            bench = (await e.workshop.open(a, "b")).id
            with pytest.raises(StoreUnavailable):
                await add_file(a, bench, by(a), TEXT, "t.txt", "", RULES)
            assert not (await e.workshop.read(a, bench)).pieces

    run(scenario())


def test_a_full_bench_refuses_the_add_but_the_bytes_stay_for_a_retry(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = (await e.workshop.open(a, "b")).id
            for i in range(RULES.max_pieces):
                await e.workshop.apply(a, bench, Add(by(a), "note", Text(str(i), ""), "small"))
            _, applied = await add_file(a, bench, by(a), TEXT, "t.txt", "", RULES)
            assert applied.outcome == "full" and applied.piece_id is None
            assert key_of(a.household_id, sha(TEXT)) in e.store.held
            assert len((await e.workshop.read(a, bench)).pieces) == RULES.max_pieces

    run(scenario())


def test_a_bench_of_another_household_is_absent_and_nothing_is_added(db_url: str) -> None:
    from ashley.workshop.workshop import BenchNotFound

    async def scenario() -> None:
        async with env(db_url) as e:
            bench = (await e.workshop.open(e.world.alana, "b")).id
            with pytest.raises(BenchNotFound):
                await add_file(e.world.zed, bench, by(e.world.zed), TEXT, "t.txt", "", RULES)
            assert not (await e.workshop.read(e.world.alana, bench)).pieces

    run(scenario())


def test_the_same_file_added_twice_is_two_pieces_and_one_object(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = (await e.workshop.open(a, "b")).id
            await add_file(a, bench, by(a), PNG, "one.png", "", RULES)
            await add_file(a, bench, by(a), PNG, "two.png", "", RULES)
            assert len((await e.workshop.read(a, bench)).pieces) == 2 and len(e.store.held) == 1

    run(scenario())


def test_the_name_and_bytes_are_not_logged(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = (await e.workshop.open(a, "b")).id
            with caplog.at_level(logging.DEBUG):
                await add_file(a, bench, by(a), b"zebra-contents", "zebra-name.txt", "", RULES)

    run(scenario())
    assert "zebra" not in log_text(caplog)


# --- the Workshop's refusals: `bad_file` ---------------------------------------------------------------------------


def descriptor(data: bytes, media: str = "application/pdf", name: str = "d.pdf") -> str:
    from ashley.workshop.stored_file import StoredFile, body_of
    return body_of(StoredFile(sha(data), len(data), media, name))


@pytest.mark.parametrize(("kind", "text"), [("file", "not a descriptor"), ("image", ""), ("file", "{}"), ("image", "plain words")])
def test_an_add_of_a_large_kind_whose_body_is_not_a_stored_file_is_refused_bad_file(db_url: str, kind: str, text: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = (await e.workshop.open(a, "b")).id
            got = await e.workshop.apply(a, bench, Add(by(a), kind, Text("t", text), "small"))
            assert got.outcome == "bad_file" and got.piece_id is None
            assert not (await e.workshop.read(a, bench)).pieces

    run(scenario())


def test_an_image_piece_must_name_an_image_and_a_file_piece_may_name_any_type(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = (await e.workshop.open(a, "b")).id
            pdf = descriptor(b"p")
            assert (await e.workshop.apply(a, bench, Add(by(a), "image", Text("t", pdf), "small"))).outcome == "bad_file"
            assert (await e.workshop.apply(a, bench, Add(by(a), "file", Text("t", pdf), "small"))).outcome == "accepted"
            png = descriptor(b"q", "image/png", "q.png")
            assert (await e.workshop.apply(a, bench, Add(by(a), "image", Text("t", png), "small"))).outcome == "accepted"

    run(scenario())


def test_an_edit_may_retitle_a_large_piece_and_may_not_change_its_body(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = (await e.workshop.open(a, "b")).id
            _, added = await add_file(a, bench, by(a), PDF, "r.pdf", "", RULES)
            piece = (await e.workshop.read(a, bench)).pieces[0]
            body = piece.text.body
            other = descriptor(b"another")
            refused = await e.workshop.apply(a, bench, Edit(by(a), piece.id, piece.version, Text(piece.text.title, other)))
            assert refused.outcome == "bad_file"
            kept = await e.workshop.apply(a, bench, Edit(by(a), piece.id, piece.version, Text("new title", body)))
            assert kept.outcome == "accepted"
            now = (await e.workshop.read(a, bench)).pieces[0]
            assert (now.text.title, now.text.body) == ("new title", body)
            assert added.piece_id == piece.id

    run(scenario())


def test_a_bodyless_edit_of_a_large_piece_is_refused(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = (await e.workshop.open(a, "b")).id
            await add_file(a, bench, by(a), PDF, "r.pdf", "", RULES)
            piece = (await e.workshop.read(a, bench)).pieces[0]
            got = await e.workshop.apply(a, bench, Edit(by(a), piece.id, piece.version, Text(piece.text.title, "")))
            assert got.outcome == "bad_file"

    run(scenario())


def test_a_name_longer_than_a_title_may_be_still_adds_with_a_title_that_fits_and_the_whole_name_in_the_file(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = (await e.workshop.open(a, "b")).id
            name = "n" * (RULES.title_max_chars + 30) + ".txt"
            _, applied = await add_file(a, bench, by(a), TEXT, name, "", RULES)
            assert applied.outcome == "accepted"
            piece = (await e.workshop.read(a, bench)).pieces[0]
            f = file_of(piece.text.body)
            assert f is not None and f.name == name
            assert 0 < len(piece.text.title) <= RULES.title_max_chars and name.startswith(piece.text.title)

    run(scenario())


def test_a_kind_the_rules_do_not_know_needs_no_bytes() -> None:
    assert not needs_bytes(RULES, "nonesuch")
