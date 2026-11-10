"""A site piece whose host is YouTube or Vimeo is refused with the `bad_site` reason, naming the video kind that takes
it: `embed.site_well_formed` is false for such a body, an Add or Edit of one is refused over a real bench, and the
same URL is a video piece."""

import json

import pytest
from ashley.inference.model import ToolCall
from ashley.tools.bench_results import HINTS
from ashley.tools.bench_tools import BenchTools
from ashley.workshop.commands import Add, Edit
from ashley.workshop.embed import site_well_formed, video_well_formed
from ashley.workshop.model import By, Owner, Text
from ashley.workshop.workshop import Workshop
from ashley import services
from bhb_support import World, pods
from contract.conversations_support import run

VIDEO_PAGES = [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://youtube.com/watch?v=dQw4w9WgXcQ",
    "https://m.youtube.com/watch?v=dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ",
    "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ", "https://vimeo.com/76979871",
    "https://player.vimeo.com/video/76979871", "https://VIMEO.com/76979871",
    "https://www.YouTube.com/watch?v=dQw4w9WgXcQ", "  https://www.youtube.com/watch?v=dQw4w9WgXcQ  "]
SITES = ["https://en.wikipedia.org/wiki/Travelling_salesman_problem", "https://example.com/",
         "https://notyoutube.com/watch?v=x", "https://youtube.com.example.org/watch?v=x",
         "https://example.com/?next=https://www.youtube.com/watch?v=x", "https://example.com/vimeo.com/76979871",
         "https://vimeo.com.example.org/1", "https://myyoutube.com/"]


@pytest.mark.parametrize("body", VIDEO_PAGES)
def test_a_youtube_or_vimeo_page_is_no_site(body: str) -> None:
    assert site_well_formed(body) is False


@pytest.mark.parametrize("body", SITES)
def test_any_other_https_page_is_a_site_even_when_a_video_host_is_only_named_in_it(body: str) -> None:
    assert site_well_formed(body) is True


def test_the_site_check_still_refuses_what_it_always_refused_and_keeps_the_empty_draft() -> None:
    assert site_well_formed("") is True
    for body in ("http://example.com/", "example.com", "https://example.com/ and more", "ftp://example.com/",
                 "https://user:pw@example.com/"):
        assert site_well_formed(body) is False, body


def test_a_video_page_is_a_video_piece() -> None:
    assert video_well_formed(json.dumps({"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})) is True


def test_the_bad_site_hint_names_the_video_kind() -> None:
    assert "video" in HINTS["bad_site"].lower()


@pytest.mark.parametrize("url", ["https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://vimeo.com/76979871"])
def test_adding_a_video_page_as_a_site_is_refused_bad_site_and_adding_it_as_a_video_is_not(world: World,
                                                                                            url: str) -> None:
    async def go() -> None:
        async with pods(world):
            workshop = services.get(Workshop)
            owner = Owner(world.who.household_id, world.who.id)
            refused = await workshop.apply(owner, world.bench.id, Add(By(world.who.id), "site", Text("t", url), "medium"))
            assert (refused.outcome, refused.piece_id) == ("bad_site", None)
            video = await workshop.apply(owner, world.bench.id,
                                         Add(By(world.who.id), "video", Text("t", json.dumps({"url": url})), "medium"))
            assert video.outcome == "accepted"
            assert [p.kind for p in (await workshop.read(owner, world.bench.id)).pieces] == ["video"]

    run(go())


def test_editing_a_site_into_a_video_page_is_refused_and_the_site_keeps_its_body(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            workshop = services.get(Workshop)
            owner = Owner(world.who.household_id, world.who.id)
            made = await workshop.apply(owner, world.bench.id,
                                        Add(By(world.who.id), "site", Text("t", "https://example.com/"), "medium"))
            assert made.piece_id is not None
            edit = Edit(By(world.who.id), made.piece_id, 1, Text("t", "https://youtu.be/dQw4w9WgXcQ"))
            assert (await workshop.apply(owner, world.bench.id, edit)).outcome == "bad_site"
            placed = (await workshop.read(owner, world.bench.id)).pieces[0]
            assert placed.version == 1

    run(go())


def test_her_bench_add_of_a_video_page_as_a_site_comes_back_as_bad_site_naming_the_video_kind(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

            async def pasted() -> frozenset[str]:
                return frozenset({url})

            tools = BenchTools(world.who.household_id, world.who.id, world.bench.id, said=pasted)
            await tools.catalogue()
            got = await tools.call(ToolCall("c1", "bench_add", {"kind": "site", "title": "t", "body": url}))
            assert got.is_error and "bad_site" in got.content and "video" in got.content.lower()

    run(go())
