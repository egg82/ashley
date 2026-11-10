"""The tier of a house action reaches `Outside` through the wrappers a turn's tools sit behind: the composite of sources and
the household's everyday tools resolved on first use. Directed tests added by the reconciler (not blind)."""

from ashley import services
from ashley.tools.composite import CompositeTools
from ashley.tools.everyday import Everyday, HouseholdTools
from ashley.tools.tools import Tools
from house_double_support import MemoryHouse
from taint_tiers_blind_house_support import HOUSEHOLD, do, house_tools, performed, the_house
from taint_tiers_blind_support import Tiered, scenario, taint_the_turn


class Fixed(Everyday):
    def __init__(self, tools: Tools) -> None:
        self._tools = tools

    async def of(self, household_id: int) -> Tools:
        return self._tools


async def lamp_runs_and_lock_waits(t: Tiered, wrap: Tools, house: MemoryHouse) -> None:
    o = taint_the_turn(wrap, t.w, "look_up")
    await o.call(do("light.turn_on", "light.porch"))
    await o.call(do("lock.unlock", "lock.front"))
    assert performed(house) == ["light.turn_on"] and [str(a["action"]) for _, a in await t.w.held()] == ["lock.unlock"]


def test_a_composite_passes_the_house_source_s_tier_through(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        house = the_house()
        await lamp_runs_and_lock_waits(t, CompositeTools({"house": house_tools(house)}), house)

    scenario(db_url, body)


def test_the_household_s_everyday_tools_pass_the_house_source_s_tier_through(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        house = the_house()
        services.register(Everyday, Fixed(house_tools(house)))
        try:
            await lamp_runs_and_lock_waits(t, HouseholdTools(HOUSEHOLD), house)
        finally:
            services.unregister(Everyday)

    scenario(db_url, body)
