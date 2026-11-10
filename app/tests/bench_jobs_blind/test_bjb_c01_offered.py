"""Contract 1: `bench_hand_off` is offered only on a bench turn whose reply reaches the speaker alone and that nobody
did not ask for (`unprompted` false). Elsewhere it is absent."""

import pytest
from bjb_support import World, bench_inbound, offered_names, scenario

TOOL = "bench_hand_off"
CANCEL = "bench_job_cancel"


def test_c01_a_bench_turn_of_the_owner_alone_offers_hand_off_and_cancel(db_url: str) -> None:
    async def body(w: World) -> None:
        names = await offered_names(w, bench_inbound(w))
        assert TOOL in names and CANCEL in names

    scenario(db_url, body)


@pytest.mark.parametrize("changes", [
    {"bench_id": None, "thread": "person:1:web", "kind": "chat", "opens_benches": True, "on_page": True},
    {"shared": True},
    {"audience": "present"},
    {"device_id": 5},
    {"unprompted": True},
    {"speaker_id": None},
], ids=["no-bench", "shared-channel", "audience-not-owner", "device-screen", "unprompted", "no-named-speaker"])
def test_c01_hand_off_is_absent_where_the_gate_is_not_met(db_url: str, changes: dict[str, object]) -> None:
    async def body(w: World) -> None:
        names = await offered_names(w, bench_inbound(w, **changes))
        assert TOOL not in names and CANCEL not in names

    scenario(db_url, body)


def test_c01_a_woken_turn_cannot_chain_jobs(db_url: str) -> None:
    async def body(w: World) -> None:
        woken = bench_inbound(w, unprompted=True, author="household", note="a watch woke", later_by="turn")
        assert TOOL not in await offered_names(w, woken)

    scenario(db_url, body)
