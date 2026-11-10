"""`sniff` judges a file by its bytes: the media type a signature names, else UTF-8 text, else a refusal; the type the
client declared is only checked against it, and markup (HTML, SVG) is never a type a file can be."""

import dataclasses

import pytest
from ashley.files.sniff import sniff
from files_blind_support import CONFIG, GIF87, GIF89, HTML, JPEG, PDF, PNG, SIGNED, SVG, TEXT, WEBP, ZIP
from hypothesis import given, settings
from hypothesis import strategies as st

MARKUP_TYPES = {"text/html", "image/svg+xml", "application/xhtml+xml", "application/xml", "text/xml"}
ALLOWED = {t.media_type for t in CONFIG.types} | set(CONFIG.text_types)


@pytest.mark.parametrize(("data", "media_type"), [
    (PNG, "image/png"), (JPEG, "image/jpeg"), (GIF87, "image/gif"), (GIF89, "image/gif"), (WEBP, "image/webp"),
    (PDF, "application/pdf"), (ZIP, "application/zip")])
@pytest.mark.parametrize("declared", ["", "application/octet-stream", "binary/octet-stream", "application/x-unknown"])
def test_a_signature_names_the_type_whatever_generic_or_unknown_thing_was_declared(data: bytes, media_type: str, declared: str) -> None:
    v = sniff(data, declared, CONFIG)
    assert (v.media_type, v.why) == (media_type, None)


@pytest.mark.parametrize(("data", "media_type"), [(PNG, "image/png"), (PDF, "application/pdf"), (ZIP, "application/zip")])
def test_the_right_declared_type_with_parameters_is_accepted(data: bytes, media_type: str) -> None:
    assert sniff(data, f"{media_type}; charset=binary", CONFIG).media_type == media_type


def test_signatures_match_at_their_offset_and_all_pairs_of_a_type_must_match() -> None:
    not_webp = b"RIFF\x24\x00\x00\x00AVI LIST"
    v = sniff(not_webp, "", CONFIG)
    assert v.media_type is None and v.why == "type_not_allowed"
    assert sniff(b"x" + PNG, "", CONFIG).media_type != "image/png"
    assert sniff(b"GIF88a\x01\x00", "", CONFIG).media_type is None


@pytest.mark.parametrize("declared", ["image/jpeg", "application/pdf", "text/plain", "text/csv", "application/zip"])
def test_a_known_type_that_is_not_what_the_bytes_are_is_a_mismatch(declared: str) -> None:
    v = sniff(PNG, declared, CONFIG)
    assert (v.media_type, v.why) == (None, "type_mismatch")


@pytest.mark.parametrize("declared", ["image/png", "application/pdf", "image/gif"])
def test_text_declared_as_a_known_binary_type_is_a_mismatch(declared: str) -> None:
    v = sniff(TEXT, declared, CONFIG)
    assert (v.media_type, v.why) == (None, "type_mismatch")


@pytest.mark.parametrize("declared", ["", "application/octet-stream", "text/plain", "text/plain; charset=utf-8"])
def test_utf8_text_is_text_plain_unless_the_client_named_another_text_type(declared: str) -> None:
    assert sniff(TEXT, declared, CONFIG).media_type == "text/plain"


@pytest.mark.parametrize("declared", ["text/csv", "text/markdown", "application/json", "text/csv; charset=utf-8"])
def test_text_may_take_a_text_type_the_client_named_for_it(declared: str) -> None:
    assert sniff(b'{"a": 1}\n', declared, CONFIG).media_type == declared.split(";")[0]


@pytest.mark.parametrize("declared", ["text/html", "image/svg+xml", "application/xhtml+xml", "text/xml", "image/svg+xml; charset=utf-8"])
@pytest.mark.parametrize("data", [HTML, SVG])
def test_markup_is_text_plain_whatever_it_was_declared_as(data: bytes, declared: str) -> None:
    v = sniff(data, declared, CONFIG)
    assert (v.media_type, v.why) == ("text/plain", None)


@pytest.mark.parametrize("data", [b"\x00\x01\x02binary", b"abc\x00def", b"bell\x07", b"esc\x1b[0m", b"\xff\xfe\xfa invalid", b"\xc3\x28"])
def test_bytes_that_are_neither_signed_nor_clean_utf8_text_are_not_allowed(data: bytes) -> None:
    v = sniff(data, "", CONFIG)
    assert (v.media_type, v.why) == (None, "type_not_allowed")


def test_tab_newline_carriage_return_and_form_feed_are_allowed_in_text() -> None:
    assert sniff(b"a\tb\r\nc\x0cd\n", "", CONFIG).media_type == "text/plain"


def test_a_refusal_carries_no_type_and_an_acceptance_no_reason() -> None:
    for data in (PNG, TEXT, b"\x00\x00"):
        v = sniff(data, "", CONFIG)
        assert (v.media_type is None) == (v.why is not None)


def test_the_config_decides_what_is_a_signature() -> None:
    narrowed = dataclasses.replace(CONFIG, types=tuple(t for t in CONFIG.types if t.media_type != "application/pdf"))
    assert sniff(PDF, "", CONFIG).media_type == "application/pdf"
    assert sniff(PDF, "", narrowed).media_type == "text/plain" or sniff(PDF, "", narrowed).media_type is None


MARKUP_HEADS = st.sampled_from([b"<!DOCTYPE html>", b"<html>", b"<HTML>", b"<svg xmlns='http://www.w3.org/2000/svg'>",
                                b"<?xml version='1.0'?><svg>", b"  <script>", b"<!-- c --><html>", b"<body onload=x>"])
DECLARED = st.one_of(st.sampled_from(["", "text/html", "image/svg+xml", "application/xhtml+xml", "image/png", "text/plain",
                                      "application/pdf", "application/octet-stream", "text/csv"]),
                     st.text(max_size=30))


@settings(max_examples=60)
@given(head=MARKUP_HEADS, tail=st.binary(max_size=40), declared=DECLARED)
def test_property_leading_markup_is_never_accepted_as_markup_or_an_image(head: bytes, tail: bytes, declared: str) -> None:
    v = sniff(head + tail, declared, CONFIG)
    assert v.media_type not in MARKUP_TYPES
    assert v.media_type is None or v.media_type == "text/plain" or v.media_type in ALLOWED - MARKUP_TYPES
    assert v.media_type is None or not CONFIG.is_image(v.media_type)


@settings(max_examples=60)
@given(data=st.binary(max_size=60), declared=DECLARED)
def test_property_a_verdict_is_a_configured_type_or_a_reason_and_never_both(data: bytes, declared: str) -> None:
    v = sniff(data, declared, CONFIG)
    assert (v.media_type is None) != (v.why is None)
    assert v.media_type is None or v.media_type in ALLOWED


@settings(max_examples=40)
@given(media_type=st.sampled_from(sorted(SIGNED)), tail=st.binary(max_size=40), declared=st.text(max_size=20))
def test_property_a_signed_file_is_never_judged_by_what_the_client_said(media_type: str, tail: bytes, declared: str) -> None:
    v = sniff(SIGNED[media_type] + tail, declared, CONFIG)
    assert v.media_type in (media_type, None)
    if v.media_type is None:
        assert v.why == "type_mismatch"


@pytest.mark.parametrize("declared", ["application/pdf; charset=binary", " Application/PDF ", "APPLICATION/PDF;x=y"])
def test_a_wrong_declared_type_is_a_mismatch_whatever_its_case_spacing_or_parameters(declared: str) -> None:
    assert sniff(PNG, declared, CONFIG).why == "type_mismatch"


def test_a_declared_type_in_any_case_is_still_the_right_one() -> None:
    assert sniff(PNG, "IMAGE/PNG", CONFIG).media_type == "image/png"
    assert sniff(b"a,b\n", "Text/CSV", CONFIG).media_type == "text/csv"


@pytest.mark.parametrize("control", [b"\x7f", b"\x1f", b"\x01", b"\x08", b"\x0e", b"\x0b"])
def test_each_other_control_character_makes_text_not_allowed(control: bytes) -> None:
    assert sniff(b"ab" + control + b"cd", "", CONFIG).why == "type_not_allowed"
