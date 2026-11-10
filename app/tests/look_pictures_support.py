"""Pictures for the look suites: real files built with Pillow, so a test checks what the pixels did."""

import io
import random

from PIL import Image

TOP_LEFT = (220, 30, 30)
REST = (30, 30, 220)


def encode(picture: Image.Image, fmt: str, orientation: int | None = None) -> bytes:
    out = io.BytesIO()
    exif = Image.Exif()
    if orientation is not None:
        exif[0x0112] = orientation
    picture.save(out, fmt, exif=exif, quality=90)
    return out.getvalue()


def noise(size: tuple[int, int], fmt: str = "PNG") -> bytes:
    """A small noisy picture no format squeezes to nothing."""
    return encode(Image.frombytes("RGB", size, random.Random(1).randbytes(size[0] * size[1] * 3)), fmt)


def corner(size: tuple[int, int], orientation: int | None = None) -> bytes:
    """A JPEG of `size` stored with its top left a red block (a tenth of each side) on blue, tagged `orientation`."""
    picture = Image.new("RGB", size, REST)
    picture.paste(Image.new("RGB", (size[0] // 10, size[1] // 10), TOP_LEFT), (0, 0))
    return encode(picture, "JPEG", orientation)


def photo(size: tuple[int, int] = (4000, 3000)) -> bytes:
    """A JPEG of `size` far over the byte limit: noise over a gradient."""
    grain = Image.effect_noise(size, 80).convert("RGB")
    return encode(Image.blend(Image.linear_gradient("L").resize(size).convert("RGB"), grain, 0.6), "JPEG")


def stripes(size: tuple[int, int], inside: tuple[float, float, float, float]) -> bytes:
    """A JPEG of `size`, flat grey except one-pixel black and white stripes inside `inside` (x, y, w, h as fractions)."""
    picture = Image.new("RGB", size, (128, 128, 128))
    x, y, w, h = (round(inside[0] * size[0]), round(inside[1] * size[1]), round(inside[2] * size[0]), round(inside[3] * size[1]))
    for col in range(x, x + w, 2):
        picture.paste(Image.new("RGB", (1, h), (0, 0, 0)), (col, y))
        picture.paste(Image.new("RGB", (1, h), (255, 255, 255)), (col + 1, y))
    return encode(picture, "PNG")


def spread(picture: Image.Image, box: tuple[int, int, int, int]) -> float:
    """The range of grey levels in `box` of `picture`: how much detail it holds."""
    levels = [i for i, count in enumerate(picture.convert("L").crop(box).histogram()) if count]
    return float(levels[-1] - levels[0])


def rgb(picture: Image.Image, at: tuple[int, int]) -> tuple[int, int, int]:
    """The colour of `picture` at `at`."""
    found = picture.convert("RGB").getpixel(at)
    assert isinstance(found, tuple)
    return found[0], found[1], found[2]
