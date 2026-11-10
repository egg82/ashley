"""Receipts over a real database: kept with her turn and read back equal, refused on a turn that is not hers, kept with a
queued reply and read back when the channel takes it, and a turn without any reads back with none."""

import pytest
from ashley.channels.model import Outbound
from ashley.channels.postgres_outbox import PostgresOutbox
from ashley.conversations.model import Author, NewTurn, Receipt, Receipts
from ashley.db.pool import PoolDatabase
from contract.conversations_support import POLICY, db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import person, run, scalar, service

RECEIPTS = Receipts((Receipt("Sent an email", 'mail_send (to: ["a@b.test"])', "You asked for it."), Receipt("Made a change")),
                    (Receipt("Cancelled a reminder", "cancel_reminder (id: 4)", None),), 9)
DONE_ONLY = Receipts((Receipt("Saved an email draft"),))
NOT_HERS: tuple[Author, ...] = ("person", "household")


def test_her_turn_reads_back_with_the_receipts_it_was_stored_with_and_her_words_untouched(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conversations:
            started = await conversations.start(home, "chat", [who])
            said = await conversations.add_turn(started.id, NewTurn("person", "do it", who))
            kept = await conversations.add_turn(started.id, NewTurn("ashley", "Okay.", answers=said.id, receipts=RECEIPTS))
            plain = await conversations.add_turn(started.id, NewTurn("ashley", "Done.", answers=said.id))
            assert kept.receipts == RECEIPTS and kept.text == "Okay." and plain.receipts is None
            found = await conversations.get(started.id)
            assert found is not None
            read = {t.id: t for t in found.turns}
            assert read[kept.id].receipts == RECEIPTS and read[plain.id].receipts is None
            assert read[said.id].receipts is None

    run(scenario())
    assert scalar(db_url, "SELECT count(*) FROM turns WHERE receipts IS NOT NULL") == 1


def test_a_turn_that_is_not_hers_cannot_carry_receipts(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conversations:
            started = await conversations.start(home, "chat", [who])
            for author in NOT_HERS:
                with pytest.raises(ValueError):
                    await conversations.add_turn(started.id, NewTurn(author, "hi", receipts=DONE_ONLY))

    run(scenario())
    assert scalar(db_url, "SELECT count(*) FROM turns") == 0


def test_the_database_itself_refuses_receipts_on_a_turn_that_is_not_hers(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conversations:
            await conversations.start(home, "chat", [who])

    run(scenario())
    with pytest.raises(Exception, match="turns_receipts_hers"):
        scalar(db_url, "INSERT INTO turns (conversation_id, household_id, author, text, receipts) "
                       "SELECT id, household_id, 'person', 'x', '{}'::jsonb FROM conversations RETURNING id")


def test_a_queued_reply_carries_its_receipts_and_the_agree_it_still_writes(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conversations:
            started = await conversations.start(home, "chat", [who])
        database = PoolDatabase(db_url, connect_timeout_s=5.0)
        await database.open()
        try:
            box = PostgresOutbox(database, 600.0, POLICY)
            await box.add(home, f"push:{who}", Outbound(started.id, "text", "Okay.", agree=9, receipts=RECEIPTS))
            await box.add(home, f"push:{who}", Outbound(started.id, "text", "Plain."))
            first, second = await box.take("push:")
        finally:
            await database.close()
        assert first.outbound == Outbound(started.id, "text", "Okay.", agree=9, receipts=RECEIPTS)
        assert second.outbound == Outbound(started.id, "text", "Plain.") and second.outbound.receipts is None

    run(scenario())
