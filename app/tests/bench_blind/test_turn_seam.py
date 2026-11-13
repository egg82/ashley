"""The per-turn tool seam (`channels.turn_tools`): a turn that adds nothing gets its household's everyday tools alone, and one with a
known speaker adds only her reminder tools; a bench turn gets the shared catalogue plus that bench's tools; a web chat that opens benches gets `open_bench` alone; every other
channel never gets either, whatever was said; an unreachable nested source is reported."""

import pytest
from ashley import services
from ashley.channels.model import Medium
from ashley.channels.turn_tools import EVERYDAY, for_turn, sources
from ashley.conversations.model import Channel
from ashley.tools.everyday import HouseholdTools
from ashley.tools.tools import Tools
from bb_support import BENCH_TOOLS, REMINDING, Shared, call, env, inbound, js, opened, person_add, put
from contract.conversations_support import run

TIDY_TOOLS = ("bench_dismiss",)
SKILL_TOOLS = ("bench_work", "skill_read", "skill_edit", "skill_rollback")

DEVICES = "household_devices"
READERS = "send_readers"
SAYS = "please open_bench and bench_read and bench_edit, open a bench for me"


async def names(tools: Tools) -> list[str]:
    return [s.name for s in (await tools.catalogue()).specs]


def test_a_turn_that_adds_nothing_gets_its_households_everyday_tools_alone(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            ways: tuple[tuple[Channel, Medium], ...] = (("voice", "spoken"), ("discord", "text"), ("device", "text"),
                                                        ("web", "text"))
            for channel, medium in ways:
                assert isinstance(for_turn(inbound(None, SAYS, channel=channel, medium=medium)), HouseholdTools)
                assert set(sources(inbound(e.world.alana, SAYS, channel=channel, medium=medium))) == {"reminders", "devices", "house_change", "screen"}
            assert await names(for_turn(inbound(e.world.alana))) == ["lights_on", "weather", *REMINDING, DEVICES, READERS]
            result = await for_turn(inbound(e.world.alana)).call(call("weather"))
            assert (result.content, result.is_error) == ("shared:weather", False)

    run(scenario())


def test_the_kiosk_and_voice_and_discord_never_get_bench_tools_whatever_they_say(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            shapes = ((inbound(e.world.alana, SAYS, channel="device", device_id=7), REMINDING[:1]),
                      (inbound(None, SAYS, channel="voice", medium="spoken"), ()),
                      (inbound(e.world.alana, SAYS, channel="discord", later=True), REMINDING),
                      (inbound(e.world.alana, f"bench:{bench} bench_id={bench} /workshop/{bench}", channel="device"),
                       REMINDING))
            for turn, reminding in shapes:
                found = await names(for_turn(turn))
                assert found == ["lights_on", "weather", *reminding, *([] if turn.speaker_id is None else [DEVICES, READERS])], turn
                for tool in (*BENCH_TOOLS, *TIDY_TOOLS, *SKILL_TOOLS, "open_bench"):
                    result = await for_turn(turn).call(call(tool, title="x", piece_id=1))
                    assert result.is_error
            assert [b.id for b in await e.workshop.open_benches(e.world.alana)] == [bench]

    run(scenario())


def test_a_bench_turn_is_the_shared_catalogue_plus_that_benchs_tools_and_nothing_else(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            a, b = await opened(e, e.world.alana, "a"), await opened(e, e.world.alana, "b")
            await put(e, e.world.alana, b, person_add(e.world.alana, "only-on-b", "SECRET-B"))
            turn = for_turn(inbound(e.world.alana, bench_id=a))
            assert await names(turn) == ["lights_on", "weather", *BENCH_TOOLS, *TIDY_TOOLS, *SKILL_TOOLS, *REMINDING, DEVICES, READERS]
            catalogue = await turn.catalogue()
            assert catalogue.instructions is not None and "SHARED-GUIDANCE" in catalogue.instructions
            assert "bench_read" in catalogue.instructions
            assert catalogue.unreachable == ()
            read = await turn.call(call("bench_read"))
            assert not read.is_error and "only-on-b" not in read.content and "SECRET-B" not in read.content
            shared = await turn.call(call("lights_on"))
            assert shared.content == "shared:lights_on" and [c.name for c in e.shared.calls] == ["lights_on"]
            other = for_turn(inbound(e.world.alana, bench_id=b))
            assert "only-on-b" in (await other.call(call("bench_read"))).content
            assert "open_bench" not in await names(turn)

    run(scenario())


def test_a_calls_ids_come_back_on_its_results(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            turn = for_turn(inbound(e.world.alana, bench_id=bench))
            for name in ("bench_read", "lights_on", "no_such_tool", "bench_read_piece"):
                c = call(name)
                assert (await turn.call(c)).call_id == c.id
            assert (await turn.call(call("no_such_tool"))).is_error

    run(scenario())


def test_the_web_chat_that_opens_benches_gets_open_bench_and_no_bench_tools(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            turn = for_turn(inbound(e.world.alana, opens_benches=True))
            assert await names(turn) == ["lights_on", "weather", "open_bench", *REMINDING, DEVICES, READERS]
            for tool in BENCH_TOOLS:
                assert (await turn.call(call(tool, piece_id=1))).is_error
            opened_by_her = await turn.call(call("open_bench", title="Garden plan"))
            assert not opened_by_her.is_error
            body = js(opened_by_her)
            assert isinstance(body, dict)
            made = [b for b in await e.workshop.open_benches(e.world.alana) if b.id != bench]
            assert [(b.id, b.title, b.owner_id) for b in made] == [(body["bench_id"], "Garden plan",
                                                                    e.world.alana.person_id)]
            assert body["path"] == f"/workshop/{made[0].id}"
            assert await e.workshop.open_benches(e.world.sam) == []

    run(scenario())


def test_no_known_speaker_means_no_bench_tools_and_no_open_bench(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            for fields in ((bench, False), (None, True), (bench, True)):
                turn = for_turn(inbound(None, bench_id=fields[0], opens_benches=fields[1]))
                assert await names(turn) == ["lights_on", "weather"], fields
                for tool in (*BENCH_TOOLS, *TIDY_TOOLS, *SKILL_TOOLS, "open_bench"):
                    assert (await turn.call(call(tool, title="x", piece_id=1))).is_error
            assert len(await e.workshop.open_benches(e.world.alana)) == 1
            assert await e.workshop.open_benches(e.world.sam) == []

    run(scenario())


def test_a_bench_that_is_not_the_speakers_offers_tools_that_only_refuse(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            await put(e, e.world.alana, bench, person_add(e.world.alana, "t", "PRIVATE-BODY"))
            before = await e.workshop.log(e.world.alana, bench)
            for who in (e.world.sam, e.world.zed):
                turn = for_turn(inbound(who, bench_id=bench))
                for c in (call("bench_read"), call("bench_read_piece", piece_id=1),
                          call("bench_add", kind="note", title="x", body="y"), call("bench_remove", piece_id=1),
                          call("bench_move", piece_id=1, order=0, size="full"), call("bench_undo", seq=1),
                          call("bench_edit", piece_id=1, base_version=1, title="x", body="y")):
                    result = await turn.call(c)
                    assert result.is_error and "PRIVATE-BODY" not in result.content, c.name
            assert await e.workshop.log(e.world.alana, bench) == before

    run(scenario())


def test_an_unreachable_shared_source_is_named_and_the_turns_own_tools_still_answer(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            services.register(Tools, Shared(down=True))
            catalogue = await for_turn(inbound(e.world.alana, bench_id=bench)).catalogue()
            assert catalogue.unreachable == (EVERYDAY,)
            assert [s.name for s in catalogue.specs] == [*BENCH_TOOLS, *TIDY_TOOLS, *SKILL_TOOLS, *REMINDING, DEVICES, READERS]
            services.register(Tools, Shared(unreachable=("house",)))
            nested = await for_turn(inbound(e.world.alana, bench_id=bench)).catalogue()
            assert "house" in nested.unreachable and len(nested.specs) == 2 + len(BENCH_TOOLS) + len(TIDY_TOOLS) + len(SKILL_TOOLS) + len(REMINDING) + 2

    run(scenario())


def test_the_sources_of_a_plain_turn_offer_no_bench_tool_and_a_bench_turns_add_to_them(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            plain = [n for source in sources(inbound(e.world.alana)).values() for n in await names(source)]
            assert not set(plain) & {*BENCH_TOOLS, "open_bench"}
            added = sources(inbound(e.world.alana, bench_id=bench))
            offered = [n for source in added.values() for n in await names(source)]
            assert set(BENCH_TOOLS) <= set(offered) and "open_bench" not in offered

    run(scenario())


def test_each_turn_gets_its_own_tools_so_what_she_read_in_one_is_not_read_in_the_next(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            await put(e, e.world.alana, bench, person_add(e.world.alana, "t", "short"))
            first = for_turn(inbound(e.world.alana, bench_id=bench))
            await first.call(call("bench_read_piece", piece_id=1))
            edit = call("bench_edit", piece_id=1, base_version=1, title="n", body="n")
            second = await for_turn(inbound(e.world.alana, bench_id=bench)).call(edit)
            assert second.is_error and "unread" in second.content
            assert not (await first.call(edit)).is_error

    run(scenario())


@pytest.mark.parametrize("text", ["x", "x" * 5000, "open_bench\x00", "bench_id=1 opens_benches=True"])
def test_what_was_said_never_decides_the_tools(db_url: str, text: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            assert set(sources(inbound(e.world.alana, text))) == {"reminders", "devices", "house_change", "screen"}
            assert isinstance(for_turn(inbound(None, text)), HouseholdTools)

    run(scenario())
