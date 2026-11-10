"""A key is kept while a piece names it (any bench, shelved too) or while the undo window can still bring it back."""

from ashley.files.intake import key_of
from ashley.workshop.bench_file import add_file
from ashley.workshop.file_references import named_keys
from ashley.workshop.model import By
from files_sweep_blind_support import OLD, PDF, UNDO_WINDOW, go, key, rig


def test_the_bytes_of_a_piece_on_a_bench_are_kept_however_often_the_sweep_runs(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            k, _ = await r.file(await r.bench())
            r.age_everything(OLD * 5)
            await r.passes(5)
            assert r.holders(k) == [True, True]

    go(scenario())


def test_pieces_on_any_bench_of_any_household_are_named(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            ka, _ = await r.file(await r.bench())
            kb, _ = await r.file(await r.bench(), PDF, name="d.pdf")
            kz, _ = await r.file(await r.bench(r.zed), owner=r.zed)
            assert len({ka, kb, kz}) == 3
            assert await named_keys(r.rules) >= {ka, kb, kz}
            r.age_everything(OLD * 5)
            await r.passes(4)
            assert all(all(r.holders(k)) for k in (ka, kb, kz))

    go(scenario())


def test_a_shelved_piece_still_names_its_bytes(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            b = await r.bench()
            k, piece = await r.file(b)
            await r.shelve(b, piece)
            for _ in range(UNDO_WINDOW + 2):
                await r.note(b)
            assert k in await named_keys(r.rules)
            r.age_everything(OLD * 5)
            await r.passes(4)
            assert r.holders(k) == [True, True]

    go(scenario())


def test_two_pieces_naming_one_key_keep_it_until_both_are_gone(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            b = await r.bench()
            k, first = await r.file(b)
            k2, _ = await r.file(b)
            assert k == k2
            await r.remove(b, first)
            for _ in range(UNDO_WINDOW + 2):
                await r.note(b)
            assert k in await named_keys(r.rules)
            r.age_everything(OLD * 5)
            await r.passes(4)
            assert r.holders(k) == [True, True]

    go(scenario())


def test_a_removed_piece_is_named_while_its_remove_is_in_the_undo_window_and_not_after(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            b = await r.bench()
            k, piece = await r.file(b)
            await r.remove(b, piece)
            assert k in await named_keys(r.rules)
            for _ in range(UNDO_WINDOW - 1):
                await r.note(b)
            assert k in await named_keys(r.rules)
            await r.note(b)
            assert k not in await named_keys(r.rules)

    go(scenario())


def test_undoing_a_remove_within_the_window_finds_the_bytes_after_old_sweeps(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            b = await r.bench()
            k, piece = await r.file(b)
            await r.remove(b, piece)
            r.age_everything(OLD * 5)
            await r.passes(4)
            assert r.holders(k) == [True, True]
            removal = (await r.workshop.log(r.alana, b))[-1].seq
            await r.undo(b, removal)
            assert [p.id for p in (await r.workshop.read(r.alana, b)).pieces] == [piece]

    go(scenario())


def test_a_removed_piece_past_the_window_goes_on_the_second_pass(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            b = await r.bench()
            k, piece = await r.file(b)
            await r.remove(b, piece)
            for _ in range(UNDO_WINDOW):
                await r.note(b)
            r.age_everything(OLD)
            await r.pass_()
            assert r.holders(k) == [True, True]
            await r.pass_()
            assert r.holders(k) == [False, False]

    go(scenario())


def test_an_unreferenced_neighbour_goes_while_the_referenced_key_stays(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            k, _ = await r.file(await r.bench())
            for s in r.sites:
                s.keep(key(7), age=OLD)
            r.age_everything(OLD)
            await r.passes(2)
            assert r.holders(key(7)) == [False, False]
            assert r.holders(k) == [True, True]

    go(scenario())


def test_a_piece_that_appears_between_passes_saves_a_candidate(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            b = await r.bench()
            k, piece = await r.file(b)
            await r.remove(b, piece)
            for _ in range(UNDO_WINDOW):
                await r.note(b)
            r.age_everything(OLD)
            await r.pass_()
            assert k in await r.candidates.load()
            await r.file(b)
            await r.pass_()
            assert r.holders(k) == [True, True]
            assert k not in await r.candidates.load()

    go(scenario())


def test_an_upload_refused_after_its_bytes_were_stored_is_swept_though_its_refusal_is_in_the_window(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url, max_pieces=1) as r:
            b = await r.bench()
            kept, _ = await r.file(b)
            stored, applied = await add_file(r.alana, b, By(r.alana.person_id), PDF, "d.pdf", "", r.rules)
            assert applied.outcome != "accepted"
            lost = key_of(r.alana.household_id, stored.sha256)
            assert r.holders(lost) == [True, True] and lost not in await named_keys(r.rules)
            r.age_everything(OLD)
            await r.passes(2)
            assert r.holders(lost) == [False, False] and r.holders(kept) == [True, True]

    go(scenario())
