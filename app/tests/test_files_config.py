"""`files.json` is read strictly, and the shipped file is a valid one."""

import pytest
from ashley.files import config as files_config

GOOD: dict[str, object] = {"max_bytes": 10, "link_ttl_s": 60, "repair_interval_s": 5, "sweep_interval_s": 6,
        "sweep_grace_s": 7, "text_types": ["text/plain"],
        "types": [{"media_type": "image/png", "image": True, "magic": [[0, "89504e47"]]}]}


def test_the_shipped_config_parses_and_knows_images_from_other_files() -> None:
    config = files_config.load()
    assert config.is_image("image/png") and not config.is_image("application/pdf") and not config.is_image("text/plain")
    assert config.knows("text/csv") and config.knows("application/zip") and not config.knows("text/html")


def test_each_media_type_is_a_piece_of_the_kind_that_shows_it() -> None:
    config = files_config.load()
    named = {m: config.piece_kind(m) for m in ("image/png", "video/mp4", "video/webm", "audio/mpeg", "audio/mp4",
                                               "application/pdf", "text/plain", "unheard/of")}
    assert named == {"image/png": "image", "video/mp4": "clip", "video/webm": "clip", "audio/mpeg": "audio",
                     "audio/mp4": "audio", "application/pdf": "file", "text/plain": "file", "unheard/of": "file"}
    assert config.plays("video/mp4") and config.plays("audio/ogg") and not config.plays("image/png")
    assert not config.plays("application/pdf")


def test_a_good_config_parses() -> None:
    assert files_config.parse(GOOD).types[0].magic == ((0, bytes.fromhex("89504e47")),)


def test_a_type_may_ask_for_a_zip_member_or_a_binary_stl_size_and_a_stl_needs_no_signature() -> None:
    entries: list[dict[str, object]] = [
        {"media_type": "model/3mf", "image": False, "member": "3D/3dmodel.model", "magic": [[0, "504b0304"]]},
        {"media_type": "model/stl", "image": False, "binary_stl": True, "magic": []}]
    types = files_config.parse({**GOOD, "types": entries}).types
    assert (types[0].member, types[0].binary_stl, types[1].member, types[1].binary_stl, types[1].magic) == (
        "3D/3dmodel.model", False, None, True, ())


CHANGES: list[dict[str, object]] = [
    {"max_bytes": 0}, {"link_ttl_s": True}, {"repair_interval_s": "5"}, {"sweep_interval_s": 0}, {"sweep_grace_s": 1.5}, {"types": []}, {"text_types": ["Text/Plain"]},
    {"text_types": ["plain"]}, {"extra": 1},
    {"types": [{"media_type": "image/png", "image": True, "magic": []}]},
    {"types": [{"media_type": "image/png", "image": 1, "magic": [[0, "89"]]}]},
    {"types": [{"media_type": "image/png", "image": True, "magic": [[-1, "89"]]}]},
    {"types": [{"media_type": "image/png", "image": True, "magic": [[0, ""]]}]},
    {"types": [{"media_type": "video/mp4", "image": False, "piece": "movie", "magic": [[0, "89"]]}]},
    {"types": [{"media_type": "image/png", "image": True, "piece": "clip", "magic": [[0, "89"]]}]},
    {"types": [{"media_type": "model/3mf", "image": False, "member": "", "magic": [[0, "89"]]}]},
    {"types": [{"media_type": "model/3mf", "image": False, "member": 3, "magic": [[0, "89"]]}]},
    {"types": [{"media_type": "model/stl", "image": False, "binary_stl": 1, "magic": []}]},
    {"types": [{"media_type": "model/stl", "image": False, "binary_stl": False, "magic": []}]}]


@pytest.mark.parametrize("change", CHANGES)
def test_a_malformed_config_is_refused(change: dict[str, object]) -> None:
    bad: dict[str, object] = {**GOOD, **change}
    with pytest.raises(ValueError):
        files_config.parse(bad)


def test_a_missing_key_is_refused() -> None:
    with pytest.raises(ValueError):
        files_config.parse({k: v for k, v in GOOD.items() if k != "types"})
