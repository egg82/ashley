"""The gate by resource: which resources a turn may use, reading and changing (decisions.md's table). A shared one is
offered on any turn of its household for reads and where the channel names a member for changes; a kept one only where
the reply reaches its owner alone, and the speaker is the owner."""

import psycopg
from ashley.channels.model import Inbound
from fastapi.testclient import TestClient
from mail_holders_blind_support import (HOME, Boxes, People, as_, hand, make, refs, share, shared_channel,
                                        shared_with_alana_kept, satellite, tablet, usable, web)

KEPT, SHARED, HOUSE = "kept@a.test", "shared@a.test", "house@h.test"


def household_box(client: TestClient, boxes: Boxes) -> int:
    saved = boxes.refs
    boxes.refs = [HOUSE]
    cid = make(client, HOME, "house")
    boxes.refs = saved
    return cid


def setup(client: TestClient, boxes: Boxes) -> None:
    shared_with_alana_kept(client, boxes)
    household_box(client, boxes)


def test_the_owner_alone_reads_and_changes_all_three(client: TestClient, boxes: Boxes, people: People) -> None:
    setup(client, boxes)
    inbound = web(people.home, people.alana)
    assert refs(client, inbound) == {KEPT, SHARED, HOUSE}
    assert refs(client, inbound, changing=True) == {KEPT, SHARED, HOUSE}


def test_another_member_on_their_own_chat_gets_the_shared_ones_not_the_kept(client: TestClient, boxes: Boxes,
                                                                          people: People) -> None:
    setup(client, boxes)
    inbound = web(people.home, people.sam)
    assert refs(client, inbound) == {SHARED, HOUSE}
    assert refs(client, inbound, changing=True) == {SHARED, HOUSE}


def test_a_satellite_reads_the_shared_ones_and_changes_nothing(client: TestClient, boxes: Boxes,
                                                               people: People) -> None:
    setup(client, boxes)
    inbound = satellite(people.home)
    assert refs(client, inbound) == {SHARED, HOUSE}
    assert refs(client, inbound, changing=True) == set()


def test_a_voice_match_never_makes_anyone_the_speaker_of_a_change_or_the_reader_of_a_kept_one(
        client: TestClient, boxes: Boxes, people: People) -> None:
    setup(client, boxes)
    inbound = satellite(people.home, heard_as=people.alana)
    assert refs(client, inbound) == {SHARED, HOUSE}
    assert refs(client, inbound, changing=True) == set()


def test_the_hallway_tablet_reads_the_shared_ones_and_changes_nothing(client: TestClient, boxes: Boxes,
                                                                      people: People) -> None:
    setup(client, boxes)
    assert refs(client, tablet(people.home)) == {SHARED, HOUSE}
    assert refs(client, tablet(people.home), changing=True) == set()


def test_a_shared_channel_naming_a_member_changes_the_shared_ones_but_never_reaches_the_kept(
        client: TestClient, boxes: Boxes, people: People) -> None:
    setup(client, boxes)
    for who in (people.sam, people.alana):
        inbound = shared_channel(people.home, who)
        assert refs(client, inbound) == {SHARED, HOUSE}
        assert refs(client, inbound, changing=True) == {SHARED, HOUSE}


def test_a_shared_channel_naming_nobody_changes_nothing(client: TestClient, boxes: Boxes, people: People) -> None:
    setup(client, boxes)
    inbound = shared_channel(people.home, None)
    assert refs(client, inbound) == {SHARED, HOUSE}
    assert refs(client, inbound, changing=True) == set()


def test_the_owners_chat_with_a_screen_showing_it_does_not_reach_the_kept_ones(client: TestClient, boxes: Boxes,
                                                                             people: People) -> None:
    setup(client, boxes)
    inbound = web(people.home, people.alana, device_id=7)
    assert refs(client, inbound) == {SHARED, HOUSE}
    assert refs(client, inbound, changing=True) == {SHARED, HOUSE}


def test_a_speaker_who_is_not_of_the_household_changes_nothing_there(client: TestClient, boxes: Boxes,
                                                                    people: People) -> None:
    setup(client, boxes)
    inbound = shared_channel(people.home, people.kim)
    assert refs(client, inbound) == {SHARED, HOUSE}
    assert refs(client, inbound, changing=True) == set()


def test_another_household_reaches_none_of_it(client: TestClient, boxes: Boxes, people: People) -> None:
    setup(client, boxes)
    for inbound in (web(people.other, people.kim), satellite(people.other), tablet(people.other)):
        assert refs(client, inbound) == set() and refs(client, inbound, changing=True) == set()


def test_sharing_offers_it_to_the_satellite_and_keeping_it_again_withdraws_it(client: TestClient, boxes: Boxes,
                                                                             people: People) -> None:
    boxes.refs = [KEPT]
    cid = make(client)
    assert refs(client, satellite(people.home)) == set()
    share(client, cid, KEPT)
    assert refs(client, satellite(people.home)) == {KEPT}
    assert refs(client, web(people.home, people.sam), changing=True) == {KEPT}
    share(client, cid, KEPT, False)
    assert refs(client, satellite(people.home)) == set()
    assert refs(client, web(people.home, people.sam)) == set()


def test_handing_the_connection_over_offers_all_its_resources_on_every_turn_of_the_household(
        client: TestClient, boxes: Boxes, people: People) -> None:
    boxes.refs = [KEPT, SHARED]
    cid = make(client)
    hand(client, cid, "household")
    assert refs(client, satellite(people.home)) == {KEPT, SHARED}
    assert refs(client, web(people.home, people.sam), changing=True) == {KEPT, SHARED}


def test_a_household_connection_is_shared_whatever_its_stored_flag(client: TestClient, boxes: Boxes, people: People,
                                                                    db_url: str) -> None:
    household_box(client, boxes)
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("UPDATE connection_resources SET shared = false")
    assert refs(client, satellite(people.home)) == {HOUSE}
    assert refs(client, web(people.home, people.sam), changing=True) == {HOUSE}


def test_the_connection_that_shares_a_ref_is_the_one_offered(client: TestClient, boxes: Boxes, people: People) -> None:
    boxes.refs = ["same@x.test"]
    kept, shared = make(client, label="kept"), make(client, label="shared")
    share(client, shared, "same@x.test")
    assert usable(client, satellite(people.home)) == {(shared, "same@x.test")}
    assert usable(client, web(people.home, people.alana)) == {(kept, "same@x.test"), (shared, "same@x.test")}


def test_a_resource_that_disappeared_from_the_service_is_no_longer_offered(client: TestClient, boxes: Boxes,
                                                                          people: People) -> None:
    boxes.refs = [KEPT, SHARED]
    cid = make(client)
    share(client, cid, SHARED)
    boxes.refs = [KEPT]
    client.get("/api/connections")
    assert refs(client, satellite(people.home)) == set()
    assert refs(client, web(people.home, people.alana)) == {KEPT}


def test_a_removed_connection_offers_nothing(client: TestClient, boxes: Boxes, people: People) -> None:
    cid = shared_with_alana_kept(client, boxes)
    client.delete(f"/api/connections/{cid}", headers={"origin": "https://ashley.test"})
    assert refs(client, satellite(people.home)) == set()
    assert refs(client, web(people.home, people.alana)) == set()


def test_no_connections_offers_nothing(client: TestClient, people: People) -> None:
    inbound: Inbound = web(people.home, people.alana)
    assert usable(client, inbound) == set() and usable(client, inbound, changing=True) == set()


def test_the_gate_reads_who_the_channel_names_not_who_signed_in_last(client: TestClient, boxes: Boxes,
                                                                     people: People) -> None:
    setup(client, boxes)
    as_(client, people, "sam")
    assert refs(client, web(people.home, people.alana)) == {KEPT, SHARED, HOUSE}
    assert refs(client, web(people.home, people.sam)) == {SHARED, HOUSE}
