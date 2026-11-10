"""What a file is is decided by its bytes: the signatures `files.json` names, UTF-8 text without control characters,
nothing else. The type the client says is only checked against that: a file that says it is a known type must be it."""

import io
import struct
import zipfile

import pytest
from files_support import AVI, CSV, ELF, GIF, HEIC, HTML, JPEG, M4A, MP3, MP4, OGG, PDF, PNG, WAV, WEBM, WEBP, ZIP
from ashley.files import config as files_config
from ashley.files.sniff import sniff

CONFIG = files_config.load()


@pytest.mark.parametrize("data,expected", [(PNG, "image/png"), (JPEG, "image/jpeg"), (GIF, "image/gif"),
                                           (WEBP, "image/webp"), (PDF, "application/pdf"), (ZIP, "application/zip")])
def test_a_signature_names_the_type_whatever_the_client_said_when_it_said_nothing_specific(data: bytes, expected: str) -> None:
    for said in ("", "application/octet-stream", expected):
        assert sniff(data, said, CONFIG).media_type == expected


def test_a_riff_file_that_is_neither_webp_nor_wav_is_not_taken() -> None:
    assert sniff(AVI, "", CONFIG).why == "type_not_allowed"


@pytest.mark.parametrize("data,expected", [(MP4, "video/mp4"), (WEBM, "video/webm"), (M4A, "audio/mp4"),
                                           (MP3, "audio/mpeg"), (OGG, "audio/ogg"), (WAV, "audio/wav")])
def test_a_video_or_audio_file_is_named_by_its_signature(data: bytes, expected: str) -> None:
    assert sniff(data, "", CONFIG).media_type == expected


def test_an_iso_media_file_of_another_brand_is_not_taken_as_video() -> None:
    assert sniff(HEIC, "", CONFIG).why == "type_not_allowed"
    assert sniff(MP4, "audio/mp4", CONFIG).why == "type_mismatch"


def test_text_is_plain_unless_the_client_named_one_of_the_text_types() -> None:
    assert sniff(CSV, "", CONFIG).media_type == "text/plain"
    assert sniff(CSV, "text/csv; charset=utf-8", CONFIG).media_type == "text/csv"
    assert sniff(b'{"a": 1}', "application/json", CONFIG).media_type == "application/json"
    assert sniff(b"print(1)", "text/x-python", CONFIG).media_type == "text/plain"


def test_a_file_that_says_it_is_a_known_type_must_be_it() -> None:
    assert sniff(CSV, "image/png", CONFIG).why == "type_mismatch"
    assert sniff(PNG, "image/jpeg", CONFIG).why == "type_mismatch"
    assert sniff(PNG, "application/pdf", CONFIG).why == "type_mismatch"
    assert sniff(HTML, "application/pdf", CONFIG).why == "type_mismatch"


def test_a_png_that_calls_itself_html_is_still_a_png() -> None:
    """HTML is no type of the config, so the client's word about it is not checked, and the bytes decide."""
    assert sniff(PNG, "text/html", CONFIG).media_type == "image/png"


def test_markup_is_text_and_so_never_served_as_html() -> None:
    verdict = sniff(HTML, "text/html", CONFIG)
    assert verdict.media_type == "text/plain"


@pytest.mark.parametrize("data", [ELF, b"abc\x00def", b"\xff\xfe\x00\x01", b"ok\x1b[31mred", bytes(range(1, 9))])
def test_binary_with_no_signature_is_not_taken(data: bytes) -> None:
    assert sniff(data, "", CONFIG).why == "type_not_allowed"


def test_every_signature_of_the_config_is_matched_by_a_sample() -> None:
    """The control: a file built from each listed signature is that type, so a typo'd or shadowed signature fails here
    (and the list is not empty)."""
    assert len(CONFIG.types) > 20
    for kind in CONFIG.types:
        sample = bytearray(32)
        for offset, want in kind.magic:
            sample[offset:offset + len(want)] = want
        data = bytes(sample)
        if kind.member is not None:
            data = zipped({kind.member: b"<model/>"})
        if kind.binary_stl:
            data = stl(2)
        assert sniff(data, "", CONFIG).media_type == kind.media_type, kind.magic


def zipped(members: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return out.getvalue()


def stl(triangles: int, size: int | None = None) -> bytes:
    body = b"\0" * 80 + struct.pack("<I", triangles) + b"\x01" * (50 * triangles)
    return body if size is None else body[:size].ljust(size, b"\0")


def glb(version: int = 2) -> bytes:
    return b"glTF" + struct.pack("<I", version) + b"\0" * 20


def test_a_zip_holding_a_3d_model_is_a_3mf_and_any_other_zip_is_a_zip() -> None:
    assert sniff(zipped({"3D/3dmodel.model": b"<model/>", "[Content_Types].xml": b"x"}), "", CONFIG).media_type == "model/3mf"
    assert sniff(zipped({"3dmodel.model": b"x"}), "", CONFIG).media_type == "application/zip"
    assert sniff(b"PK\x03\x04 not really a zip", "", CONFIG).media_type == "application/zip"


def test_a_binary_stl_is_a_file_whose_size_is_what_its_triangle_count_gives() -> None:
    assert sniff(stl(3), "", CONFIG).media_type == "model/stl"
    assert sniff(stl(3)[:-1], "", CONFIG).why == "type_not_allowed"
    assert sniff(stl(3) + b"\0", "", CONFIG).why == "type_not_allowed"
    assert sniff(stl(0), "", CONFIG).why == "type_not_allowed"
    assert sniff(b"\0" * 84, "", CONFIG).why == "type_not_allowed"


def test_a_glb_is_a_gltf_header_of_version_two() -> None:
    assert sniff(glb(), "", CONFIG).media_type == "model/gltf-binary"
    assert sniff(glb(1), "", CONFIG).why == "type_not_allowed"


def test_a_declared_3d_type_that_is_not_the_bytes_is_a_mismatch() -> None:
    assert sniff(stl(1), "model/stl", CONFIG).media_type == "model/stl"
    assert sniff(glb(), "model/stl", CONFIG).why == "type_mismatch"
