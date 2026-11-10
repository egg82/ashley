"""`for_thread` under concurrency: calls racing on one thread, from one instance or two, all return the same
conversation, and only one is started; the same when they race to replace a closed one."""

import pytest
from ashley.conversations.model import Conversation
from conversations_support import POLICY, gather_settled, household, place_before_now, run, service
from threads_support import conversation_count, target


@pytest.mark.parametrize("round_", range(3))
def test_calls_racing_on_a_new_thread_agree_and_start_one(db_url: str, round_: int) -> None:
    home = household(db_url)

    async def scenario() -> None:
        async with service(db_url) as one, service(db_url) as two:
            got = await gather_settled(*((one if i % 2 else two).for_thread(home, "device:3", "chat", [])
                                         for i in range(12)))
        made = [c for c in got if isinstance(c, Conversation)]
        assert made == got, [c for c in got if not isinstance(c, Conversation)]
        assert len({c.id for c in made}) == 1
        assert conversation_count(db_url) == 1
        assert target(db_url, "device:3") == made[0].id

    run(scenario())


@pytest.mark.parametrize("round_", range(3))
def test_calls_racing_on_a_closed_thread_agree_on_one_replacement(db_url: str, round_: int) -> None:
    home = household(db_url)

    async def scenario() -> None:
        async with service(db_url) as one, service(db_url) as two:
            first = await one.for_thread(home, "device:3", "command", [])
            place_before_now(db_url, first.id, POLICY.timings["command"].closed_after_s * 2)
            got = await gather_settled(*((one if i % 2 else two).for_thread(home, "device:3", "command", [])
                                         for i in range(12)))
        made = [c for c in got if isinstance(c, Conversation)]
        assert made == got, [c for c in got if not isinstance(c, Conversation)]
        ids = {c.id for c in made}
        assert len(ids) == 1 and first.id not in ids
        assert conversation_count(db_url) == 2
        assert target(db_url, "device:3") in ids

    run(scenario())


def test_calls_racing_on_different_threads_each_get_their_own(db_url: str) -> None:
    home = household(db_url)

    async def scenario() -> None:
        async with service(db_url) as conv:
            got = await gather_settled(*(conv.for_thread(home, f"device:{i}", "chat", []) for i in range(8)))
        made = [c for c in got if isinstance(c, Conversation)]
        assert made == got
        assert len({c.id for c in made}) == 8

    run(scenario())
