"""Making a picture fit to be looked at (`bench_look`): an image piece's own bytes, or a screenshot, oriented as its
EXIF says, cropped to a region of it, scaled down to `max_image_px` on its longest side and encoded as a JPEG small
enough to give her. The crop is taken from the full-size pixels before the scale, so a region is more detail, not a
bigger copy of the same pixels. Pure and synchronous; callers run it off the event loop."""

import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from .config import LooksConfig

QUALITY_STEP = 15
QUALITY_FLOOR = 30
SHRINK = 0.75
SHRINKS = 4


class CannotPrepare(Exception):
    """The picture cannot be made fit; `outcome` is the tool outcome and `reason` what she is told."""

    def __init__(self, outcome: str, reason: str) -> None:
        super().__init__(outcome)
        self.outcome = outcome
        self.reason = reason


@dataclass(frozen=True)
class Region:
    """A rectangle as fractions of the oriented picture's width and height: from (`x`, `y`) at the top left, `w` wide and
    `h` tall."""

    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class Prepared:
    data: bytes
    px: int
    """The longest side, in pixels."""


def check_region(region: Region, minimum: float) -> None:
    """Raises ValueError, naming what is wrong, unless the region lies inside the picture and is at least `minimum` of
    each side."""
    if not all(0 <= v <= 1 for v in (region.x, region.y)) or not all(0 < v <= 1 for v in (region.w, region.h)):
        raise ValueError("region is fractions of the picture: x and y from 0 to 1, w and h over 0 and up to 1")
    if region.x + region.w > 1 or region.y + region.h > 1:
        raise ValueError("region reaches outside the picture")
    if region.w < minimum or region.h < minimum:
        raise ValueError(f"region is at least {minimum} of each side")


def prepare(data: bytes, region: Region | None, config: LooksConfig) -> Prepared:
    """`data` as a JPEG within `config.max_image_bytes` and `max_image_px`. Raises CannotPrepare: `unreadable` when it
    is no picture Pillow can read, `too_large` when it holds more than `max_image_pixels` (refused before it is decoded)
    or cannot be made small enough."""
    try:
        source = Image.open(io.BytesIO(data))
        if source.width * source.height > config.max_image_pixels:
            raise CannotPrepare("too_large", "that image holds too many pixels to look at here")
        upright = ImageOps.exif_transpose(source)
        picture = _flat(upright)
    except Image.DecompressionBombError as e:
        raise CannotPrepare("too_large", "that image holds too many pixels to look at here") from e
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise CannotPrepare("unreadable", "that image could not be read as a picture") from e
    if region is not None:
        picture = picture.crop(_box(region, picture.width, picture.height))
    return _encoded(_fitted(picture, config.max_image_px), config)


def longest_side(data: bytes) -> int | None:
    """The longest side of the picture `data` holds, read from its header; None when it is no picture."""
    try:
        return max(Image.open(io.BytesIO(data)).size)
    except (UnidentifiedImageError, OSError):
        return None


def _flat(picture: Image.Image) -> Image.Image:
    """RGB, with any transparency laid over white, which JPEG cannot hold."""
    if picture.mode in ("RGBA", "LA") or (picture.mode == "P" and "transparency" in picture.info):
        rgba = picture.convert("RGBA")
        base = Image.new("RGB", rgba.size, "white")
        base.paste(rgba, mask=rgba.getchannel("A"))
        return base
    return picture.convert("RGB")


def _box(region: Region, width: int, height: int) -> tuple[int, int, int, int]:
    left = min(round(region.x * width), width - 1)
    top = min(round(region.y * height), height - 1)
    right = max(left + 1, min(round((region.x + region.w) * width), width))
    bottom = max(top + 1, min(round((region.y + region.h) * height), height))
    return left, top, right, bottom


def _fitted(picture: Image.Image, longest: int) -> Image.Image:
    """`picture` scaled down, never up, so its longest side is at most `longest`."""
    scale = longest / max(picture.size)
    if scale >= 1:
        return picture
    return picture.resize((max(1, round(picture.width * scale)), max(1, round(picture.height * scale))), Image.Resampling.LANCZOS)


def _encoded(picture: Image.Image, config: LooksConfig) -> Prepared:
    """JPEG bytes within the limit: quality steps down, then the picture shrinks and tries again."""
    for _ in range(SHRINKS + 1):
        quality = config.image_jpeg_quality
        while True:
            out = io.BytesIO()
            picture.save(out, "JPEG", quality=quality, optimize=True)
            if out.tell() <= config.max_image_bytes:
                return Prepared(out.getvalue(), max(picture.size))
            if quality <= QUALITY_FLOOR:
                break
            quality = max(QUALITY_FLOOR, quality - QUALITY_STEP)
        picture = _fitted(picture, round(max(picture.size) * SHRINK))
    raise CannotPrepare("too_large", "that image cannot be made small enough to look at here")
