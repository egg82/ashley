"""The look tunables (`ashley.looks.config`) and the page link (`ashley.looks.links`)."""

import json

import pytest
from ashley.files import links as file_links
from ashley.looks import config, links

KEY = b"k" * 32
GRANT = links.Grant(household_id=3, person_id=5, bench_id=9, piece_id=12, expires_at=2000)


def shipped() -> dict[str, object]:
    loaded: dict[str, object] = json.loads(config.FILE.read_text())
    return loaded


def test_the_shipped_file_loads_with_room_in_the_log_for_a_picture_in_base64() -> None:
    loaded = config.load()
    assert loaded.max_image_bytes * 4 // 3 < loaded.log_bytes
    assert loaded.ready_timeout_s < loaded.pod_deadline_s


@pytest.mark.parametrize("change", [
    {"pod_deadline_s": 20}, {"log_bytes": 1_000_000}, {"jpeg_quality": 101}, {"max_height": 100}, {"width": 0},
    {"poll_s": "fast"}, {"cpu": ""}, {"extra": 1}, {"warm_tick_s": 0}, {"warm_max_age_s": 1.5}, {"warm_connect_s": "2"},
    {"ephemeral_mib": 16}])
def test_a_bad_file_is_refused(change: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        config.parse({**shipped(), **change})


def test_a_missing_key_is_refused() -> None:
    data = shipped()
    del data["memory"]
    with pytest.raises(ValueError):
        config.parse(data)


def test_a_link_round_trips_its_grant_with_and_without_a_piece() -> None:
    assert links.check(KEY, links.mint(KEY, GRANT), now=1999) == GRANT
    whole = links.Grant(3, 5, 9, None, 2000)
    assert links.check(KEY, links.mint(KEY, whole), now=0) == whole


def test_a_link_stops_working_at_its_end() -> None:
    token = links.mint(KEY, GRANT)
    assert links.check(KEY, token, now=2000) is None


def test_a_forged_or_other_keyed_or_damaged_link_is_refused() -> None:
    token = links.mint(KEY, GRANT)
    payload, _, mac = token.partition(".")
    assert links.check(b"x" * 32, token, now=0) is None
    assert links.check(KEY, payload + "." + mac[:-2] + "AA", now=0) is None
    assert links.check(KEY, payload, now=0) is None
    assert links.check(KEY, "", now=0) is None
    assert links.check(KEY, "!!." + mac, now=0) is None


def test_a_file_link_is_not_a_look_link_nor_the_other_way() -> None:
    file_token = file_links.mint(KEY, file_links.Grant(3, "a" * 64, "image/png", True, 2000)).url.rsplit("/", 1)[1]
    assert links.check(KEY, file_token, now=0) is None
    look_token = links.mint(KEY, GRANT)
    assert file_links.check(KEY, look_token, now=0) is None
