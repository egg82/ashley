"""The look tunables: the shipped file loads, and `parse` refuses what its docstring says it refuses."""

import json
from pathlib import Path
from typing import Any

import pytest
from ashley import looks
from ashley.looks import config

SHIPPED: dict[str, Any] = json.loads((Path(looks.__file__).parent / "looks.json").read_text())


def changed(**edits: object) -> dict[str, Any]:
    return {**SHIPPED, **edits}


def test_the_shipped_tunables_load_and_equal_the_parsed_file() -> None:
    assert config.load() == config.parse(SHIPPED)


def test_every_field_of_the_config_is_a_key_of_the_file() -> None:
    assert set(config.load().__dataclass_fields__) == set(SHIPPED)


def test_the_shipped_values_are_what_parse_gives() -> None:
    loaded = config.load()
    assert all(getattr(loaded, k) == v for k, v in SHIPPED.items())


def test_a_missing_key_is_refused() -> None:
    short = dict(SHIPPED)
    del short["poll_s"]
    with pytest.raises(ValueError):
        config.parse(short)


def test_an_unknown_key_is_refused() -> None:
    with pytest.raises(ValueError):
        config.parse(changed(surprise=1))


@pytest.mark.parametrize("data", [None, [], "x", 3])
def test_something_that_is_no_object_is_refused(data: object) -> None:
    with pytest.raises(ValueError):
        config.parse(data)


@pytest.mark.parametrize("key", ["width", "height", "max_height", "jpeg_quality", "max_image_bytes", "max_looks_per_turn",
                                 "link_ttl_s", "pod_deadline_s", "ready_timeout_s", "shm_mib", "home_mib",
                                 "ephemeral_mib", "log_bytes", "poll_s"])
@pytest.mark.parametrize("bad", [0, -1])
def test_a_value_that_is_not_positive_is_refused(key: str, bad: int) -> None:
    with pytest.raises(ValueError):
        config.parse(changed(**{key: bad}))


@pytest.mark.parametrize("key", ["width", "max_looks_per_turn", "cpu", "memory"])
def test_a_value_of_the_wrong_type_is_refused(key: str) -> None:
    with pytest.raises(ValueError):
        config.parse(changed(**{key: [1]}))


def test_a_max_height_under_the_height_is_refused() -> None:
    with pytest.raises(ValueError):
        config.parse(changed(max_height=SHIPPED["height"] - 1))


def test_a_max_height_equal_to_the_height_is_taken() -> None:
    assert config.parse(changed(max_height=SHIPPED["height"])).max_height == SHIPPED["height"]


def test_a_jpeg_quality_over_100_is_refused_and_100_is_taken() -> None:
    with pytest.raises(ValueError):
        config.parse(changed(jpeg_quality=101))
    assert config.parse(changed(jpeg_quality=100)).jpeg_quality == 100


def test_ephemeral_storage_must_exceed_the_home() -> None:
    with pytest.raises(ValueError):
        config.parse(changed(ephemeral_mib=SHIPPED["home_mib"]))
    assert config.parse(changed(ephemeral_mib=SHIPPED["home_mib"] + 1)).ephemeral_mib == SHIPPED["home_mib"] + 1


def test_a_deadline_that_leaves_the_page_no_time_is_refused() -> None:
    with pytest.raises(ValueError):
        config.parse(changed(pod_deadline_s=SHIPPED["ready_timeout_s"]))
    with pytest.raises(ValueError):
        config.parse(changed(pod_deadline_s=1))


def test_a_log_without_room_for_a_base64_picture_is_refused() -> None:
    need = SHIPPED["max_image_bytes"] * 4 // 3
    with pytest.raises(ValueError):
        config.parse(changed(log_bytes=need - 1000))
    with pytest.raises(ValueError):
        config.parse(changed(log_bytes=SHIPPED["max_image_bytes"]))
    assert config.parse(changed(log_bytes=need * 2)).log_bytes == need * 2


@pytest.mark.parametrize("key", ["width", "max_looks_per_turn", "jpeg_quality"])
def test_a_boolean_is_no_integer(key: str) -> None:
    with pytest.raises(ValueError):
        config.parse(changed(**{key: True}))


@pytest.mark.parametrize("key", ["cpu", "cpu_request", "memory"])
def test_an_empty_quantity_is_refused(key: str) -> None:
    with pytest.raises(ValueError):
        config.parse(changed(**{key: ""}))
