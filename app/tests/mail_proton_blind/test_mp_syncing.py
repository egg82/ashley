"""A Proton mailbox whose account has not finished its sync in the current epoch answers `syncing`, never an empty list
(design: "A Proton mailbox whose account's `synced_epoch` is not the current epoch answers every read `syncing` with the
progress Bridge last reported, never an empty mailbox"; "Rejected: telling 'still syncing' from message counts"), and an
account Bridge signed out answers `needs_reconnect`."""

from ashley.inference.model import ToolResult
from mail_proton_blind_support import (ALANA_ADDRESS, BOXES, LABEL, LABELS, M1, READ, SEARCH, SUBJECTS, Box, World, data,
                                       failed, rows, snapshot, stock, target)

SAM = "sam@proton.test"


def reads(world: World, ident: str = "<m1@school.test>", mailbox: str = ALANA_ADDRESS) -> list[ToolResult]:
    turn = world.turn()
    return [turn.call(LABELS, mailbox=mailbox), turn.call(SEARCH, mailbox=mailbox), turn.call(READ, mailbox=mailbox, id=ident)]


def test_a_mailbox_not_synced_in_this_epoch_answers_syncing_to_every_read_though_bridge_holds_mail(world: World) -> None:
    box = world.box(synced=False)
    stock(box)
    for got in reads(world):
        failed(got, "syncing")
        assert '"messages"' not in got.content and '"labels"' not in got.content


def test_a_mailbox_that_is_syncing_is_listed_as_syncing(world: World) -> None:
    world.box(synced=False)
    (row,) = data(world.turn().call(BOXES))["mailboxes"]
    assert row["address"] == ALANA_ADDRESS and row["syncing"] is True


def test_the_answers_are_full_once_the_sync_finishes_and_ids_still_resolve(world: World) -> None:
    box = world.box(synced=False)
    stock(box)
    failed(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS), "syncing")
    world.sync(box, "progress", 0.5)
    failed(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS), "syncing")
    world.sync(box, "finished")
    got = rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS))
    assert len(got) == 5
    assert data(world.turn().call(BOXES))["mailboxes"][0]["syncing"] is False
    assert "ten dollars" in data(world.turn().call(READ, mailbox=ALANA_ADDRESS, id=got[1]["id"]))["text"]


def test_a_new_epoch_makes_a_synced_mailbox_syncing_again_until_it_finishes(world: World, alana: Box) -> None:
    stock(alana)
    before = {r["subject"]: r["id"] for r in rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS))}
    world.start_epoch()
    alana.account.renumber()
    for got in reads(world):
        failed(got, "syncing")
    world.sync(alana, "finished")
    after = {r["subject"]: r["id"] for r in rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS))}
    assert after == before


def test_a_sync_that_starts_again_makes_the_mailbox_syncing(world: World, alana: Box) -> None:
    stock(alana)
    assert rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS))
    world.sync(alana, "started")
    failed(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS), "syncing")


def test_syncing_is_per_account(world: World) -> None:
    done, still = world.box(ALANA_ADDRESS), world.box(SAM, synced=False, label="second")
    stock(done)
    stock(still, to=SAM)
    assert len(rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS))) == 5
    failed(world.turn().call(SEARCH, mailbox=SAM), "syncing")
    flags = {r["address"]: r["syncing"] for r in data(world.turn().call(BOXES))["mailboxes"]}
    assert flags == {ALANA_ADDRESS: False, SAM: True}
    world.sync(still)
    assert len(rows(world.turn().call(SEARCH, mailbox=SAM))) == 5


def test_an_empty_mailbox_that_has_synced_answers_an_empty_list(world: World, alana: Box) -> None:
    assert data(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS))["messages"] == []
    assert data(world.turn().call(LABELS, mailbox=ALANA_ADDRESS))["labels"]


def test_a_change_on_a_mailbox_that_is_syncing_is_refused_and_changes_nothing(world: World) -> None:
    box = world.box()
    stock(box)
    row = next(r for r in rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS)) if r["subject"] == SUBJECTS[M1])
    world.sync(box, "started")
    before = snapshot(box)
    failed(world.turn().call(LABEL, mailbox=ALANA_ADDRESS, messages=[target(row)], add=["Receipts"]))
    assert snapshot(box) == before


def test_an_account_bridge_signed_out_answers_needs_reconnect_not_an_empty_list(world: World, alana: Box) -> None:
    stock(alana)
    world.sign_out(alana)
    for got in reads(world):
        failed(got, "needs_reconnect")
    (row,) = data(world.turn().call(BOXES))["mailboxes"]
    assert row["unavailable"] == "signed_out"


def test_a_signed_out_account_does_not_hide_its_siblings(world: World) -> None:
    gone, fine = world.box(ALANA_ADDRESS), world.box(SAM, label="second")
    stock(fine, to=SAM)
    world.sign_out(gone)
    failed(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS), "needs_reconnect")
    assert len(rows(world.turn().call(SEARCH, mailbox=SAM))) == 5
