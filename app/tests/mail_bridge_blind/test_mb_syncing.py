"""Sync state as a field (design: "A Proton mailbox whose account's `synced_epoch` is not the current epoch answers every
read `syncing` with the progress Bridge last reported, never an empty mailbox; the room shows the same", and "A pod of
the other site ... one full resync"). Part 4 builds the state; the mailbox that answers from it is part 5, so the tests
read it from the record."""

from mail_bridge_blind_support import World


def test_an_account_added_in_this_epoch_is_syncing_until_its_sync_finishes(world: World) -> None:
    pod = world.begin()
    world.account("u1")
    (account,) = world.accounts()
    assert account.syncing is True and account.synced_epoch is None
    assert world.event(pod, "sync_finished", "u1").status_code == 200
    (account,) = world.accounts()
    assert account.syncing is False and account.synced_epoch == pod.epoch


def test_a_new_epoch_makes_every_synced_account_syncing_again(world: World) -> None:
    first = world.begin(name="first")
    world.account("u1")
    world.account("u2")
    world.event(first, "sync_finished", "u1")
    world.event(first, "sync_finished", "u2")
    assert [a.syncing for a in world.accounts()] == [False, False]
    world.begin(name="second")
    got = world.accounts()
    assert [a.syncing for a in got] == [True, True]
    assert {a.synced_epoch for a in got} == {first.epoch}


def test_each_account_is_synced_on_its_own_finish(world: World) -> None:
    pod = world.begin()
    world.account("u1")
    world.account("u2")
    world.event(pod, "sync_finished", "u2")
    by_user = {a.user_id: a.syncing for a in world.accounts()}
    assert by_user == {"u1": True, "u2": False}


def test_progress_is_stored_with_the_syncing_state(world: World) -> None:
    pod = world.begin()
    world.account("u1")
    assert world.event(pod, "sync_started", "u1").status_code == 200
    assert world.event(pod, "sync_progress", "u1", progress=0.42).status_code == 200
    (account,) = world.accounts()
    assert account.syncing is True and abs(float(account.progress) - 0.42) < 1e-9


def test_a_sync_finished_event_from_a_retired_epoch_is_refused_and_marks_nothing(world: World) -> None:
    old = world.begin(name="old")
    world.account("u1")
    world.begin(name="new")
    got = world.event(old, "sync_finished", "u1")
    assert got.status_code in (401, 403, 409)
    (account,) = world.accounts()
    assert account.syncing is True and account.synced_epoch != old.epoch


def test_a_sync_finished_event_naming_an_older_epoch_than_the_current_is_refused_409(world: World) -> None:
    old = world.begin(name="old")
    new = world.begin(name="new")
    world.account("u1")
    assert world.event(new, "sync_finished", "u1", epoch=old.epoch).status_code == 409
    assert world.accounts()[0].syncing is True


def test_a_signed_out_account_is_marked_and_its_connection_needs_a_login(world: World) -> None:
    pod = world.begin()
    connection = world.account("u1")
    assert world.needs(connection) is None
    assert world.event(pod, "user_signed_out", "u1").status_code == 200
    (account,) = world.accounts()
    assert account.state == "signed_out"
    assert world.needs(connection) == "login"


def test_a_signed_out_event_for_one_account_leaves_the_other_connected(world: World) -> None:
    pod = world.begin()
    one, two = world.account("u1"), world.account("u2")
    world.event(pod, "user_signed_out", "u1")
    assert world.needs(one) == "login" and world.needs(two) is None
    assert {a.user_id: a.state for a in world.accounts()} == {"u1": "signed_out", "u2": "connected"}


def test_an_event_of_an_unknown_kind_is_refused_and_changes_nothing(world: World) -> None:
    pod = world.begin()
    world.account("u1")
    got = world.event(pod, "something_else", "u1")
    assert 400 <= got.status_code < 500 and got.status_code not in (401, 403, 409)
    assert world.accounts()[0].syncing is True
