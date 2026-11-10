"""Who may use a Proton mailbox is the resource's to say, as for Gmail (design: "The gate is by resource": a kept mailbox
reaches its owner alone, a shared one the household; a change on a shared one needs a speaker the channel names)."""

from mail_proton_blind_support import ALANA_ADDRESS, BOXES, DRAFT, LABEL, SEARCH, SEND, Box, World, data, failed, rows, stock

SAM_ADDRESS = "sam@proton.test"


def test_a_kept_mailbox_is_offered_to_its_owner_alone(world: World, alana: Box) -> None:
    assert "mail_search" in world.turn("alana").names()
    assert world.turn("sam").names() == set()
    assert world.turn("alana", audience="household").names() == set()
    assert world.turn("alana", shared=True).names() == set()


def test_a_shared_mailbox_is_read_by_any_member_and_changed_only_by_a_named_speaker(world: World, alana: Box) -> None:
    stock(alana)
    world.share(alana)
    aloud = world.turn("sam", audience="present", shared=True, speaker=False)
    assert {"mail_boxes", "mail_search", "mail_read"} <= aloud.names() and not {SEND, DRAFT, LABEL} & aloud.names()
    assert [r["subject"] for r in rows(aloud.call(SEARCH, mailbox=ALANA_ADDRESS))][:1] == ["Re: Trip money"]
    named = world.turn("sam")
    assert {SEND, DRAFT, LABEL} <= named.names()
    data(named.call(SEND, mailbox=ALANA_ADDRESS, to=["dana@club.test"], subject="From Sam", body="Hi"))
    (done,) = world.bridge.smtp.delivered
    assert done.user == ALANA_ADDRESS and done.mail_from == ALANA_ADDRESS


def test_a_housemate_cannot_name_a_kept_mailbox_and_reaches_nothing(world: World, alana: Box) -> None:
    stock(alana)
    got = world.turn("sam").call(SEARCH, mailbox=ALANA_ADDRESS)
    failed(got)
    assert alana.account.logins == 0


def test_each_person_reaches_only_their_own_mailbox_and_names_it_by_address(world: World, alana: Box) -> None:
    sam = world.box(SAM_ADDRESS, who="sam")
    stock(alana)
    stock(sam, to=SAM_ADDRESS)
    assert [m["address"] for m in data(world.turn("alana").call(BOXES))["mailboxes"]] == [ALANA_ADDRESS]
    assert [m["address"] for m in data(world.turn("sam").call(BOXES))["mailboxes"]] == [SAM_ADDRESS]
    failed(world.turn("alana").call(SEARCH, mailbox=SAM_ADDRESS))
    assert sam.account.logins == 0 and len(rows(world.turn("sam").call(SEARCH, mailbox=SAM_ADDRESS))) == 5


def test_a_person_with_two_proton_mailboxes_must_name_one_and_each_is_its_own_login(world: World, alana: Box) -> None:
    second = world.box("alana.work@proton.test", label="work")
    stock(alana)
    stock(second, to="alana.work@proton.test")
    failed(world.turn().call(SEARCH))
    assert len(rows(world.turn().call(SEARCH, mailbox="alana.work@proton.test"))) == 5
    assert second.account.logins >= 1 and alana.account.logins == 0
    data(world.turn().call(SEND, mailbox="alana.work@proton.test", to=["dana@club.test"], subject="s", body="b"))
    assert world.bridge.smtp.delivered[0].user == "alana.work@proton.test"
