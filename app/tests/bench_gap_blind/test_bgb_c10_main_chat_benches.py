"""Contract 10: main chat lists the speaker's open benches (`Catalogue.now` of move_page); a message about one of them
moves the page there, and the turn goes on on that bench."""

import asyncio
from dataclasses import dataclass, field, replace

import pytest
from ashley import services
from ashley.channels.respond import respond
from ashley.channels.turn_tools import for_turn
from ashley.inference.model import ToolCall, ToolCalls
from ashley.inference.reply import Reply
from ashley.live.live import Live
from ashley.tools.move_page import MovePageTools
from ashley.tools.tools import Catalogue
from ashley.workshop.model import Bench, Owner
from ashley.workshop.workshop import Workshop, WorkshopUnavailable
from bench_tools_support import EPOCH, FakeWorkshop
from bgb_bench_support import NOTE
from live_support import FakeLive
from respond_support import ALANA, HOME, Fakes, inbound, wired as wired

CLIP, GATE, CLOSED = 23, 31, 4417
TITLES = {CLIP: "Clip holder for the lid", GATE: "Garden gate latch", CLOSED: "CLOSED-BENCH-MARK"}
SENTENCE = ("When their message is about the work on one of these benches, take them there with move_page and do the "
            "work in this turn. Never tell them to go there themselves.")
REPLY = Reply(spoken="Built it.", text="Built it.")
CHAT = replace(inbound("Yes, go", thread="person:1:web", speaker_id=ALANA.id, kind="chat"), audience="owner",
               shared=False, place=None, channel="web", later=True, later_by="turn", opens_benches=True, on_page=True)
DM = replace(CHAT, thread="discord:dm:1", channel="discord", on_page=False, opens_benches=False)


def bench(bid: int, owner: Owner, closed: bool = False) -> Bench:
    return Bench(bid, owner.household_id, owner.person_id, TITLES[bid], EPOCH, EPOCH if closed else None, work="3d")


@dataclass
class Benches(FakeWorkshop):
    """The speaker's open benches 23 and 31; a closed one is only in `closed_benches`."""

    down: bool = False
    asked: list[Owner] = field(default_factory=list[Owner])

    async def open_benches(self, owner: Owner) -> list[Bench]:
        self.asked.append(owner)
        if self.down:
            raise WorkshopUnavailable()
        return [bench(CLIP, owner), bench(GATE, owner)]

    async def closed_benches(self, owner: Owner) -> list[Bench]:
        return [bench(CLOSED, owner, closed=True)]


def catalogue() -> Catalogue:
    return asyncio.run(MovePageTools(HOME.id, ALANA.id).catalogue())


@pytest.fixture
def shop(wired: Fakes) -> Benches:
    fake = Benches(pieces=(NOTE,))
    services.register(Workshop, fake)
    services.register(Live, FakeLive())
    wired.tools.specs = ()
    return fake


def test_c10_the_catalogue_names_each_open_bench_by_id_title_and_kind(shop: Benches) -> None:
    now = catalogue().now
    assert now is not None
    for bid in (CLIP, GATE):
        assert str(bid) in now and TITLES[bid] in now
    assert "3d" in now


def test_c10_a_closed_bench_is_not_listed(shop: Benches) -> None:
    now = catalogue().now
    assert now is not None and str(CLOSED) not in now and TITLES[CLOSED] not in now


def test_c10_the_benches_asked_after_are_the_speakers_own(shop: Benches) -> None:
    catalogue()
    assert shop.asked and set(shop.asked) == {Owner(HOME.id, ALANA.id)}


def test_c10_an_unavailable_workshop_gives_no_now(shop: Benches) -> None:
    shop.down = True
    assert catalogue().now is None


def test_c10_the_instructions_tell_her_to_move_and_never_to_send_them(shop: Benches) -> None:
    assert catalogue().instructions is not None and SENTENCE in str(catalogue().instructions)


def test_c10_main_chat_offers_the_benches_and_a_thread_without_move_page_has_none(shop: Benches) -> None:
    assert asyncio.run(for_turn(CHAT).catalogue()).now is not None
    assert asyncio.run(for_turn(DM).catalogue()).now is None


def test_c10_a_message_about_a_bench_moves_the_page_and_the_work_is_done_on_that_bench(
        wired: Fakes, shop: Benches) -> None:
    move = ToolCalls((ToolCall("m", "move_page", {"to": "bench", "bench_id": CLIP}),))
    add = ToolCalls((ToolCall("a", "bench_add", {"kind": "note", "title": "Clip", "body": "b"}),))
    wired.inference.script = [move, add, REPLY]
    asyncio.run(respond(CHAT))
    first = wired.contexts[0].tools_now
    assert first is not None and str(CLIP) in first and TITLES[CLIP] in first and NOTE.text.title not in first
    before, after = ([s.name for s in p.tools] for p in (wired.inference.prompts[0], wired.inference.prompts[2]))
    assert "move_page" in before and "bench_add" not in before and "bench_add" in after
    assert [(o, b) for o, b, _ in shop.applied] == [(Owner(HOME.id, ALANA.id), CLIP)]
    now_on_bench = wired.inference.prompts[2].system["default"].moment
    assert NOTE.text.title in now_on_bench
    talk = asyncio.run(wired.conversations.on_thread(HOME.id, f"bench:{CLIP}"))
    assert talk is not None and talk.turns[-1].text == REPLY.text
