"""The Proposals service on the house topic (`senses.proposals`, Postgres): one proposal per person and conversation, a newer one
replacing the earlier, taken only from a later turn within the limit, once; and a Null Object that raises."""

from datetime import UTC, datetime, timedelta

import pytest
from ashley import services
from ashley.home_assistant.change import Change
from ashley.senses.proposal_payloads import HOUSE, HouseChange
from ashley.senses.proposals import NullProposals, Proposal, ProposalRefused, Proposals, ProposalsUnavailable
from contract.conversations_support import footprint, run, scalar
from hag_world_support import World, world

TTL = 3600.0


def now() -> datetime:
    return datetime.now(UTC)


def age_all(url: str, hours: int) -> None:
    """Make every stored proposal `hours` older, as the database holds them."""
    moved = scalar(url, f"WITH u AS (UPDATE proposals SET created_at = created_at - interval '{hours} hours' RETURNING 1) "
                        "SELECT count(*) FROM u")
    assert moved >= 1


def proposal(w: World, who: int | None = None, conversation: int = 4, turn: int = 10, change: Change | None = None,
             at: datetime | None = None, summary: str = "delete the porch automation") -> Proposal[HouseChange]:
    return Proposal(w.home, who or w.alana, conversation, turn, at or now(),
                    HouseChange(change or Change("delete", "automation", "porch"), summary))


def test_the_unwired_locator_answers_a_null_object_that_raises_on_every_call() -> None:
    null = services.get(Proposals)
    assert isinstance(null, NullProposals) and isinstance(Proposals.null(), NullProposals)

    async def go() -> None:
        change = Proposal(1, 1, 1, 1, now(), HouseChange(Change("delete", "area", "a"), "s"))
        with pytest.raises(ProposalsUnavailable):
            await null.propose(change, TTL)
        with pytest.raises(ProposalsUnavailable):
            await null.pending(1, 1, HOUSE)
        with pytest.raises(ProposalsUnavailable):
            await null.take(1, 1, HOUSE, 2, TTL)
    run(go())


def test_a_proposal_is_kept_whole_and_pending_until_taken(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            assert await w.proposals.pending(w.alana, 4, HOUSE) is None
            kept = proposal(w, change=Change("perform", "action", "homeassistant.stop", {"note": {"a": [1, 2, {"b": None}]}, "n": 1.5},
                                              ("light.a", "light.b")))
            await w.proposals.propose(kept, TTL)
            got = await w.proposals.pending(w.alana, 4, HOUSE)
            assert got is not None
            assert got.payload == kept.payload and got.payload.change.ids == ("light.a", "light.b")
            assert (got.household_id, got.made_by, got.conversation_id, got.turn_id) == (w.home, w.alana, 4, 10)
            assert got.payload.summary == kept.payload.summary and abs((got.proposed_at - kept.proposed_at).total_seconds()) < 1
            again = await w.proposals.pending(w.alana, 4, HOUSE)
            assert again == got
    run(go())


def test_a_change_with_no_id_and_empty_fields_comes_back_the_same(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            for change in (Change("create", "area", None, {"name": "Sauna"}), Change("delete", "label", "x"),
                           Change("perform", "action", "backup.create")):
                await w.proposals.propose(proposal(w, change=change), TTL)
                got = await w.proposals.pending(w.alana, 4, HOUSE)
                assert got is not None and got.payload.change == change
    run(go())


def test_a_proposal_is_taken_from_a_later_turn_once_and_leaves_none(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            kept = proposal(w)
            await w.proposals.propose(kept, TTL)
            got = await w.proposals.take(w.alana, 4, HOUSE, 11, TTL)
            assert got.payload.change == kept.payload.change and got.turn_id == 10
            assert await w.proposals.pending(w.alana, 4, HOUSE) is None
            with pytest.raises(ProposalRefused) as raised:
                await w.proposals.take(w.alana, 4, HOUSE, 12, TTL)
            assert raised.value.reason == "none"
    run(go())


def test_the_turn_that_proposed_it_and_earlier_ones_cannot_take_it_and_it_stays_for_a_later_one(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.proposals.propose(proposal(w), TTL)
            for turn in (10, 9, 0):
                with pytest.raises(ProposalRefused) as raised:
                    await w.proposals.take(w.alana, 4, HOUSE, turn, TTL)
                assert raised.value.reason == "same_turn"
            assert await w.proposals.pending(w.alana, 4, HOUSE) is not None
            assert (await w.proposals.take(w.alana, 4, HOUSE, 11, TTL)).turn_id == 10
    run(go())


def test_a_proposal_past_its_limit_is_expired_and_cannot_be_taken(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.proposals.propose(proposal(w), 86400.0)
            age_all(db_url, 2)
            with pytest.raises(ProposalRefused) as raised:
                await w.proposals.take(w.alana, 4, HOUSE, 11, TTL)
            assert raised.value.reason == "expired"
            await w.proposals.propose(proposal(w, conversation=5), TTL)
            assert (await w.proposals.take(w.alana, 5, HOUSE, 11, TTL)).conversation_id == 5
    run(go())


def test_nothing_taken_from_where_nothing_was_proposed(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.proposals.propose(proposal(w), TTL)
            for who, conversation in ((w.sam, 4), (w.alana, 5), (w.sam, 5)):
                with pytest.raises(ProposalRefused) as raised:
                    await w.proposals.take(who, conversation, HOUSE, 11, TTL)
                assert raised.value.reason == "none"
                assert await w.proposals.pending(who, conversation, HOUSE) is None
            assert await w.proposals.pending(w.alana, 4, HOUSE) is not None
    run(go())


def test_a_newer_proposal_replaces_the_earlier_of_its_person_and_conversation_only(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            older = Change("delete", "automation", "old")
            newer = Change("delete", "area", "new")
            other = Change("delete", "label", "elsewhere")
            await w.proposals.propose(proposal(w, change=older, turn=10), TTL)
            await w.proposals.propose(proposal(w, conversation=9, change=other, turn=3), TTL)
            await w.proposals.propose(proposal(w, who=w.sam, change=other, turn=3), TTL)
            await w.proposals.propose(proposal(w, change=newer, turn=12), TTL)
            got = await w.proposals.pending(w.alana, 4, HOUSE)
            assert got is not None and got.payload.change == newer and got.turn_id == 12
            assert (await w.proposals.take(w.alana, 4, HOUSE, 13, TTL)).payload.change == newer
            assert await w.proposals.pending(w.alana, 4, HOUSE) is None
            with pytest.raises(ProposalRefused):
                await w.proposals.take(w.alana, 4, HOUSE, 14, TTL)
            for who, conversation in ((w.alana, 9), (w.sam, 4)):
                left = await w.proposals.pending(who, conversation, HOUSE)
                assert left is not None and left.payload.change == other
    run(go())


def test_the_latest_is_the_one_pending_and_taken_whatever_order_they_were_kept_in(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.proposals.propose(proposal(w, change=Change("delete", "area", "first"), turn=10), TTL)
            await w.proposals.propose(proposal(w, change=Change("delete", "area", "second"), turn=11), TTL)
            await w.proposals.propose(proposal(w, change=Change("delete", "area", "third"), turn=12), TTL)
            got = await w.proposals.take(w.alana, 4, HOUSE, 13, TTL)
            assert got.payload.change.id == "third"
            with pytest.raises(ProposalRefused):
                await w.proposals.take(w.alana, 4, HOUSE, 14, TTL)
    run(go())


def test_proposing_drops_what_is_older_than_the_limit(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.proposals.propose(proposal(w, conversation=7), 86400.0)
            age_all(db_url, 3)
            assert await w.proposals.pending(w.alana, 7, HOUSE) is not None
            await w.proposals.propose(proposal(w, conversation=8), TTL)
            assert await w.proposals.pending(w.alana, 7, HOUSE) is None
            assert await w.proposals.pending(w.alana, 8, HOUSE) is not None
    run(go())


def test_taking_a_refused_proposal_changes_nothing_stored(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.proposals.propose(proposal(w), TTL)
            before = footprint(db_url)
            with pytest.raises(ProposalRefused):
                await w.proposals.take(w.alana, 4, HOUSE, 10, TTL)
            assert footprint(db_url) == before
    run(go())


def test_a_proposal_keeps_the_time_it_was_given(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            given = now() - timedelta(hours=2)
            await w.proposals.propose(proposal(w, at=given), 86400.0)
            got = await w.proposals.pending(w.alana, 4, HOUSE)
            assert got is not None and abs((got.proposed_at - given).total_seconds()) < 1
    run(go())
