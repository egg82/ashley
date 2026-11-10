"""`ashley.looks.pictures`: an image is oriented, cropped from its original pixels, scaled to the longest side and
encoded under the byte limit; a region that is not inside the picture, a picture that is too large to decode and a file
that is no picture are refused."""

import dataclasses
import io
import struct
import zlib

import pytest
from PIL import Image

from ashley.looks import config as looks_config
from ashley.looks import pictures
from ashley.looks.pictures import CannotPrepare, Region
from look_pictures_support import REST, TOP_LEFT, corner, noise, photo, rgb, spread, stripes

CONFIG = looks_config.load()


@pytest.fixture(scope="module")
def big() -> bytes:
    return photo()


def opened(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def near(got: tuple[int, int, int], want: tuple[int, int, int]) -> bool:
    return all(abs(a - b) < 40 for a, b in zip(got, want))


def test_a_photo_over_the_byte_limit_comes_back_as_a_jpeg_at_the_longest_side_under_the_limit(big: bytes) -> None:
    assert len(big) > CONFIG.max_image_bytes and opened(big).size == (4000, 3000)
    made = pictures.prepare(big, None, CONFIG)
    got = opened(made.data)
    assert got.format == "JPEG" and got.size == (CONFIG.max_image_px, CONFIG.max_image_px * 3 // 4)
    assert made.px == CONFIG.max_image_px and len(made.data) <= CONFIG.max_image_bytes


def test_a_picture_that_cannot_fit_at_full_size_is_shrunk_until_it_does(big: bytes) -> None:
    tight = dataclasses.replace(CONFIG, max_image_bytes=120_000)
    made = pictures.prepare(big, None, tight)
    assert len(made.data) <= 120_000 and made.px < CONFIG.max_image_px


def test_a_picture_that_cannot_be_made_small_enough_is_refused_too_large() -> None:
    with pytest.raises(CannotPrepare) as e:
        pictures.prepare(noise((400, 300)), None, dataclasses.replace(CONFIG, max_image_bytes=100))
    assert e.value.outcome == "too_large"


def test_a_smaller_picture_is_never_scaled_up() -> None:
    assert pictures.prepare(noise((200, 100)), None, CONFIG).px == 200


def test_exif_orientation_is_applied_so_a_photo_comes_back_upright() -> None:
    made = pictures.prepare(corner((300, 200), orientation=6), None, CONFIG)
    got = opened(made.data)
    assert got.size == (200, 300)
    assert near(rgb(got, (190, 5)), TOP_LEFT) and near(rgb(got, (5, 5)), REST)


def test_a_region_is_cropped_from_the_original_pixels_before_the_scale(big: bytes) -> None:
    made = pictures.prepare(big, Region(0, 0, 0.5, 0.5), CONFIG)
    assert opened(made.data).size == (CONFIG.max_image_px, CONFIG.max_image_px * 3 // 4)
    small = pictures.prepare(noise((400, 300)), Region(0.25, 0.25, 0.5, 0.5), CONFIG)
    assert opened(small.data).size == (200, 150)


def test_a_region_is_oriented_before_it_is_cropped() -> None:
    made = pictures.prepare(corner((300, 200), orientation=6), Region(0.5, 0, 0.5, 0.2), CONFIG)
    got = opened(made.data)
    assert near(rgb(got, (got.width - 3, 3)), TOP_LEFT)


def test_a_region_shows_more_detail_than_the_same_area_of_the_whole() -> None:
    area = (0.5, 0.5, 0.25, 0.25)
    source = stripes((3200, 2400), area)
    whole = opened(pictures.prepare(source, None, CONFIG).data)
    scale = whole.width / 3200
    box = (round(0.5 * 3200 * scale) + 2, round(0.5 * 2400 * scale) + 2, round(0.75 * 3200 * scale) - 2, round(0.75 * 2400 * scale) - 2)
    zoomed = opened(pictures.prepare(source, Region(*area), CONFIG).data)
    assert spread(zoomed, (4, 4, zoomed.width - 4, zoomed.height - 4)) > spread(whole, box) + 80


@pytest.mark.parametrize("region", [
    Region(-0.1, 0, 0.5, 0.5), Region(0, -0.1, 0.5, 0.5), Region(0, 0, 0, 0.5), Region(0, 0, 0.5, 0),
    Region(0.6, 0, 0.5, 0.5), Region(0, 0.6, 0.5, 0.5), Region(0, 0, 1.2, 0.5), Region(1.1, 0, 0.1, 0.5),
    Region(0, 0, CONFIG.min_region / 2, 0.5), Region(0, 0, 0.5, CONFIG.min_region / 2),
])
def test_a_region_outside_the_picture_or_too_small_is_refused(region: Region) -> None:
    with pytest.raises(ValueError):
        pictures.check_region(region, CONFIG.min_region)


def test_a_region_at_the_edges_and_the_minimum_is_accepted() -> None:
    pictures.check_region(Region(0, 0, 1, 1), CONFIG.min_region)
    pictures.check_region(Region(1 - CONFIG.min_region, 1 - CONFIG.min_region, CONFIG.min_region, CONFIG.min_region), CONFIG.min_region)


def png_header_of(width: int, height: int) -> bytes:
    """A PNG's signature and header naming `width` by `height` and no pixels: what a decompression bomb opens as."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00")))


def test_a_picture_with_too_many_pixels_is_refused_before_it_is_decoded() -> None:
    with pytest.raises(CannotPrepare) as e:
        pictures.prepare(png_header_of(20000, 20000), None, CONFIG)
    assert e.value.outcome == "too_large"
    capped = dataclasses.replace(CONFIG, max_image_pixels=64 * 48 - 1)
    with pytest.raises(CannotPrepare) as again:
        pictures.prepare(noise((64, 48)), None, capped)
    assert again.value.outcome == "too_large"
    pictures.prepare(noise((64, 48)), None, dataclasses.replace(CONFIG, max_image_pixels=64 * 48))


def test_bytes_that_are_no_picture_are_refused_unreadable() -> None:
    with pytest.raises(CannotPrepare) as e:
        pictures.prepare(b"%PDF-1.7 not a picture", None, CONFIG)
    assert e.value.outcome == "unreadable"


def test_transparency_is_laid_over_white() -> None:
    clear = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    out = io.BytesIO()
    clear.save(out, "PNG")
    got = opened(pictures.prepare(out.getvalue(), None, CONFIG).data)
    assert near(rgb(got, (20, 20)), (255, 255, 255))
