"""One `Source` per system, each turning that system's records into `Found` under that system's own rule for who may
read them. Nothing here filters a record the system returned; a source that does not serve a hearer is not asked."""

from datetime import UTC, date, datetime

from .. import services
from ..conversations.conversations import Conversations, ConversationsUnavailable
from ..conversations.model import Hearer
from ..ledger import model as ledger
from ..ledger.ledger import Ledger
from ..memory.memory import Memory, MemoryUnavailable
from ..memory.model import Asker
from ..printing import model as printing
from ..printing.printing import Printing
from .find import Source
from .model import Found, SourceDown


class MemorySource(Source):
    """Facts by `Memory.recall`, whose visibility filter in SQL decides what the hearer may hear: an unknown speaker
    shared facts only, their own private facts only when the answer reaches them alone. A fact is a statement someone
    made and memory has no guessed facts, so each is confirmed."""

    kind = "memory"

    async def find(self, hearer: Hearer, query: str, limit: int) -> tuple[Found, ...] | None:
        asker = Asker(hearer.household_id, hearer.speaker_id, hearer.owner_only, datetime.now(UTC))
        try:
            recalled = await services.get(Memory).recall(asker, query)
        except MemoryUnavailable as e:
            raise SourceDown("memory") from e
        return tuple(Found("memory", str(r.fact.id), r.fact.text, r.fact.valid_from, True) for r in recalled[:limit])


class ConversationSource(Source):
    """Turns by `Conversations.search`: the conversations the speaker took part in, never a turn said privately to
    someone else. Only for a named speaker reading alone, since the search returns their own private turns. A turn is
    a record of what was said, so each is confirmed."""

    kind = "conversation"

    async def find(self, hearer: Hearer, query: str, limit: int) -> tuple[Found, ...] | None:
        if hearer.speaker_id is None or not hearer.owner_only:
            return None
        try:
            matches = await services.get(Conversations).search(hearer.household_id, hearer.speaker_id, query, limit)
        except ConversationsUnavailable as e:
            raise SourceDown("conversation") from e
        return tuple(Found("conversation", str(m.turn_id), m.snippet, m.at, True, str(m.conversation_id))
                     for m in matches)


class PrintSource(Source):
    """Print library files by `Printing.files`, whose name holds the query. The printers are the household's, so any
    named speaker may read them, as her printing tools are offered (`docs/decisions/connections.md`)."""

    kind = "print"

    async def find(self, hearer: Hearer, query: str, limit: int) -> tuple[Found, ...] | None:
        if hearer.speaker_id is None:
            return None
        try:
            page = await services.get(Printing).files(hearer.household_id, query, limit)
        except printing.NotConnected:
            return None
        except (printing.PrintingFailed, printing.PrintingUnavailable) as e:
            raise SourceDown("print") from e
        return tuple(Found("print", f.id, f.name, None, True) for f in page.rows)


class LedgerSource(Source):
    """Transactions by `Ledger.transactions` whose name, notes or merchant hold the query. Only for a named speaker
    reading alone, as her money tools are offered (`ashley.channels.audience.owner_alone`). A transaction the backend
    gives no id cannot be followed and is left out. Each is the backend's own record, so confirmed."""

    kind = "transaction"

    async def find(self, hearer: Hearer, query: str, limit: int) -> tuple[Found, ...] | None:
        if hearer.speaker_id is None or not hearer.owner_only:
            return None
        try:
            page = await services.get(Ledger).transactions(hearer.household_id,
                                                           ledger.TransactionQuery(per_page=limit, search=query))
        except ledger.NotConnected:
            return None
        except (ledger.LedgerFailed, ledger.LedgerUnavailable) as e:
            raise SourceDown("transaction") from e
        return tuple(Found("transaction", t.id, _titled(t), None, True, dated=_day(t.date))
                     for t in page.rows if t.id is not None)


def _titled(entry: ledger.Entry) -> str:
    return entry.name if entry.amount is None else f"{entry.name}, {entry.amount}"


def _day(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def everyday() -> tuple[Source, ...]:
    """Every source Find asks today, in the order their records are listed."""
    return (MemorySource(), ConversationSource(), PrintSource(), LedgerSource())
