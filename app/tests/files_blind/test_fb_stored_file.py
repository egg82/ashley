"""A large piece's body: one JSON object of exactly sha256, size, media_type and name; anything else names no file."""

import json

import pytest
from ashley.workshop.stored_file import MAX_NAME, StoredFile, body_of, file_of, file_well_formed, image_well_formed
from files_blind_support import sha

GOOD = {"sha256": sha(b"x"), "size": 1, "media_type": "image/png", "name": "x.png"}


def body(**changes: object) -> str:
    return json.dumps({**GOOD, **changes})


def test_a_well_formed_body_names_its_file() -> None:
    assert file_of(body()) == StoredFile(sha(b"x"), 1, "image/png", "x.png")


def test_body_of_and_file_of_are_inverse() -> None:
    f = StoredFile(sha(b"yy"), 2, "application/pdf", "café \"quoted\" ☃.pdf")
    assert file_of(body_of(f)) == f
    assert json.loads(body_of(f)) == {"sha256": f.sha256, "size": 2, "media_type": "application/pdf", "name": f.name}


@pytest.mark.parametrize("bad", [
    "", "null", "[]", "{}", "3", '"s"', "not json", "{", body()[:-1],
    json.dumps({k: v for k, v in GOOD.items() if k != "name"}),
    json.dumps({k: v for k, v in GOOD.items() if k != "sha256"}),
    json.dumps({k: v for k, v in GOOD.items() if k != "size"}),
    json.dumps({k: v for k, v in GOOD.items() if k != "media_type"}),
    json.dumps({**GOOD, "extra": 1}),
    body(sha256=sha(b"x").upper()), body(sha256=sha(b"x")[:63]), body(sha256=sha(b"x") + "0"), body(sha256="g" * 64), body(sha256=7),
    body(size=0), body(size=-5), body(size="1"), body(size=1.5), body(size=None),
    body(media_type="png"), body(media_type=""), body(media_type="image/"), body(media_type="/png"), body(media_type="a b/c"),
    body(media_type=3), body(name="x" * (MAX_NAME + 1)), body(name=5), body(name=None)])
def test_a_body_not_of_the_shape_names_no_file_and_is_not_well_formed(bad: str) -> None:
    assert file_of(bad) is None
    assert not file_well_formed(bad) and not image_well_formed(bad)


def test_a_name_of_the_largest_length_is_accepted() -> None:
    assert file_of(body(name="n" * MAX_NAME)) is not None


@pytest.mark.parametrize(("media", "image"), [("image/png", True), ("image/jpeg", True), ("image/webp", True),
                                              ("application/pdf", False), ("text/plain", False), ("application/zip", False)])
def test_a_file_body_is_well_formed_and_an_image_body_only_when_the_type_is_an_image(media: str, image: bool) -> None:
    assert file_well_formed(body(media_type=media))
    assert image_well_formed(body(media_type=media)) is image
