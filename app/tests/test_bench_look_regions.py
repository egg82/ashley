"""`bench_look`'s `region` and `view`: a region crops the image from its own pixels or the screenshot, a view names the
side a model is drawn from, bad ones are refused as bad_arguments, and the log says how, region, view, bytes and the
longest side, never the picture."""

import dataclasses
import io
from dataclasses import dataclass
from typing import Any

import pytest
from PIL import Image as PilImage

from ashley import services
from ashley.looks.looker import Shot, Target
from ashley.looks.views import VIEWS
from ashley.tools import bench_look
from ashley.workshop.bench_file import add_file
from ashley.workshop.commands import Add
from ashley.workshop.model import HER, Text
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from files_support import sync
from look_pictures_support import corner, noise, photo, spread, stripes
from test_bench_look import RULES, Browser, World, seen, world


@dataclass
class Drawing(Browser):
    """A browser whose screenshots are `picture`."""

    picture: bytes = b""

    async def look(self, name: str, target: Target) -> Shot:
        await super().look(name, target)
        return Shot(self.picture)


async def added(w: World, data: bytes, name: str = "p.png", media: str = "image/png") -> int:
    _, done = await add_file(w.owner, w.bench, HER, data, name, media, RULES)
    assert done.piece_id is not None
    return done.piece_id


async def model_piece(w: World) -> int:
    done = await services.get(Workshop).apply(w.owner, w.bench, Add(HER, "model", Text("bracket", "x = 1"), "medium"))
    assert done.piece_id is not None
    return done.piece_id


def sized(data: bytes) -> tuple[int, int]:
    return PilImage.open(io.BytesIO(data)).size


@sync
async def test_a_photo_over_the_byte_limit_is_looked_at_from_its_own_bytes_without_a_browser(db_url: str) -> None:
    async with world(db_url) as w:
        piece = await added(w, photo(), "p.jpg", "image/jpeg")
        got = await w.look(piece_id=piece)
        assert not got.is_error, got.content
        (shown,) = got.images
        assert seen(got)["how"] == "piece" and w.browser.looked == []
        assert sized(shown.data)[0] == 1568 and len(shown.data) <= 1_000_000


@sync
async def test_an_exif_rotated_photo_comes_back_upright(db_url: str) -> None:
    async with world(db_url) as w:
        piece = await added(w, corner((300, 200), orientation=6), "p.jpg", "image/jpeg")
        got = await w.look(piece_id=piece)
        assert sized(got.images[0].data) == (200, 300)


@sync
async def test_a_region_returns_the_crop_at_more_detail_than_the_same_area_of_the_whole(db_url: str) -> None:
    area = {"x": 0.5, "y": 0.5, "w": 0.25, "h": 0.25}
    async with world(db_url) as w:
        piece = await added(w, stripes((3200, 2400), (0.5, 0.5, 0.25, 0.25)))
        whole = PilImage.open(io.BytesIO((await w.look("a", piece_id=piece)).images[0].data))
        zoomed = PilImage.open(io.BytesIO((await w.look("b", piece_id=piece, region=area)).images[0].data))
        scale = whole.width / 3200
        box = (round(1600 * scale) + 2, round(1200 * scale) + 2, round(2400 * scale) - 2, round(1800 * scale) - 2)
        assert zoomed.size == (800, 600)
        assert spread(zoomed, (4, 4, 796, 596)) > spread(whole, box) + 80
        assert w.browser.looked == []


@sync
@pytest.mark.parametrize("region", [
    {"x": 0.5, "y": 0, "w": 0.6, "h": 0.5}, {"x": -0.1, "y": 0, "w": 0.5, "h": 0.5}, {"x": 0, "y": 0, "w": 0, "h": 0.5},
    {"x": 0, "y": 0, "w": 0.001, "h": 0.5}, {"x": 0, "y": 0, "w": 0.5}, {"x": 0, "y": 0, "w": 0.5, "h": 0.5, "z": 1},
    {"x": "0", "y": 0, "w": 0.5, "h": 0.5}, {"x": True, "y": 0, "w": 0.5, "h": 0.5}, [0, 0, 1, 1], "all",
    {"x": float("nan"), "y": 0, "w": 0.5, "h": 0.5},
])
async def test_a_bad_region_is_refused_and_looks_at_nothing(db_url: str, region: object) -> None:
    async with world(db_url) as w:
        piece = await added(w, noise((64, 48)))
        got = await w.look(piece_id=piece, region=region)
        assert got.is_error and got.content.startswith("bad_arguments:") and got.images == ()
        assert w.rows() == [] and w.browser.looked == []


@sync
async def test_a_bomb_of_a_picture_fails_too_large_plainly(db_url: str) -> None:
    from test_look_pictures import png_header_of

    async with world(db_url) as w:
        piece = await added(w, png_header_of(30000, 30000))
        got = await w.look(piece_id=piece)
        assert got.is_error and got.content.startswith("too_large:") and w.browser.looked == []


@sync
async def test_a_model_look_passes_its_view_to_the_look_render(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bench_look, "CONFIG", dataclasses.replace(bench_look.CONFIG, max_looks_per_turn=len(VIEWS) + 1))
    async with world(db_url) as w:
        piece = await model_piece(w)
        for view in VIEWS:
            assert not (await w.look(f"c-{view}", piece_id=piece, view=view)).is_error
        await w.look("sheet", piece_id=piece)
        looked = [t.view for _, t in w.browser.looked]
        assert looked == [*VIEWS, None]


@sync
@pytest.mark.parametrize("view", ["sideways", "", 3, None])
async def test_a_view_that_is_not_one_of_the_sides_is_refused(db_url: str, view: object) -> None:
    async with world(db_url) as w:
        got = await w.look(piece_id=await model_piece(w), view=view)
        assert got.is_error and got.content.startswith("bad_arguments:") and w.browser.looked == []


@sync
async def test_a_view_of_anything_but_a_model_is_refused(db_url: str) -> None:
    async with world(db_url) as w:
        for piece in (w.note_piece, w.image_piece, None):
            got = await (w.look(view="top") if piece is None else w.look(piece_id=piece, view="top"))
            assert got.is_error and got.content.startswith("bad_arguments:")
        assert w.browser.looked == []


@sync
async def test_a_region_crops_a_screenshot(db_url: str) -> None:
    async with world(db_url, Drawing(picture=corner((1200, 800)))) as w:
        got = await w.look(piece_id=await model_piece(w), view="top", region={"x": 0, "y": 0, "w": 0.5, "h": 0.5})
        assert sized(got.images[0].data) == (600, 400) and seen(got)["how"] == "screenshot"
        assert [t.view for _, t in w.browser.looked] == ["top"]


@sync
async def test_the_log_says_how_region_view_bytes_and_size_and_never_content(db_url: str,
                                                                          caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    async with world(db_url, Drawing(picture=corner((1200, 800)))) as w:
        got = await w.look("a", piece_id=await added(w, noise((64, 48))), region={"x": 0, "y": 0, "w": 0.5, "h": 0.5})
        await w.look("b", piece_id=await model_piece(w), view="top")
    first, second = [dict(getattr(r, "fields", {})) for r in caplog.records if r.getMessage() == "tools.call"]
    assert (first["how"], first["region"], first["view"], first["bytes"], first["px"]) == (
        "piece", 1, "-", len(got.images[0].data), 32)
    assert (second["how"], second["region"], second["view"], second["px"]) == ("screenshot", 0, "top", 1200)


@sync
async def test_the_spec_describes_the_shape_and_gives_no_sentence_to_copy(db_url: str) -> None:
    async with world(db_url) as w:
        (spec,) = (await w.tools().catalogue()).specs
        properties: Any = spec.parameters["properties"]
        assert set(properties) == {"piece_id", "region", "view"}
        assert all(side in spec.description for side in VIEWS) and "e.g." not in spec.description
