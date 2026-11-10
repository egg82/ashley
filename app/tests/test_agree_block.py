"""The receipts name their proposal: after a tainted turn holds a change, the `Outside` that built them says which stored
proposal they show (`agree`), the id the page and the push notification offer Agree for; with nothing held it says none."""

from ashley.conversations.model import NewTurn
from ashley.inference.model import ToolCall
from ashley.senses.proposal_payloads import OUTSIDE
from ashley.tools.outside import Outside, Standing
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template, run
from agree_support import world


def test_the_receipts_of_a_turn_that_held_name_the_stored_proposal(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            conversation = await w.conversations.for_thread(w.home, w.thread, "chat", [w.alana], remembered=True,
                                                            channel="web", place=None)
            said = await w.conversations.add_turn(conversation.id, NewTurn("household", "a watch fired"))
            outside = Outside(w.tools, Standing(w.home, w.alana, True, False), (conversation.id, said.id), tainted="watch")
            assert await outside.receipts() is None and outside.agree is None
            await outside.call(ToolCall("c1", "switch", {"lamp": "hall"}))
            receipts = await outside.receipts()
            held = await w.proposals.pending(w.alana, 0, OUTSIDE)
            assert receipts is not None and held is not None and held.id is not None
            assert outside.agree == held.id == receipts.proposal_id and w.tools.ran == []
    run(go())
