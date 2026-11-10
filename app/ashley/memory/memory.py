"""The Memory service (`ashley.services`): what she knows, and who may hear it. Callers import only this module and
`model`. Fact text is people's data, so it is never logged; fact ids and counts are."""

from abc import abstractmethod
from collections.abc import Mapping, Sequence
from datetime import datetime

from ..conversations.model import Conversation, Kind as ConversationKind
from ..inference.inference import InferenceUnavailable
from ..services import Service
from .model import Asker, Fact, Held, Op, Recalled, Unwritten


class MemoryUnavailable(Exception):
    """The database could not be reached. Transient: the caller may retry."""


class AlreadyWritten(Exception):
    """The conversation's turns through that id were already written; nothing was applied."""


class Memory(Service):
    @classmethod
    def null(cls) -> "Memory":
        return NullMemory()

    @abstractmethod
    async def recall(self, asker: Asker, query: str) -> tuple[Recalled, ...]:
        """The current facts that bear on `query`, best first, filtered before ranking by who is asking: an unknown
        speaker gets shared facts only; a known one gets everyone's shared and discreet facts and their own private
        ones, the private ones only when `asker.owner_only`. Another person's private fact never comes back, and
        nothing crosses households.

        Standing facts are never returned here; they come through `profile`.

        The matches are the facts sharing a word with `query`, best match first, and then the few facts whose meaning
        is nearest to it by embedding (a paraphrase shares no word), nearest first, each at most once. When the
        embedder cannot answer, only the first kind is returned and nothing fails. Logs `memory.recall` with the
        household, how many facts came `by_text` and `by_vector`, and their ids."""

    @abstractmethod
    async def profile(self, asker: Asker) -> tuple[Recalled, ...]:
        """Every current standing fact of `asker.household_id`, oldest id first, filtered exactly as `recall` filters:
        an unknown speaker gets shared facts only; a known one gets everyone's shared and discreet facts and their
        own private ones, the private ones only when `asker.owner_only`. Another person's private fact never comes
        back, and nothing crosses households. `may_volunteer` is as in `recall`. No query, no embedding. Logs
        `memory.profile` with the household, how many facts and their ids."""

    @abstractmethod
    async def similar(self, conversation: Conversation, limit: int) -> tuple[Fact, ...]:
        """At most `limit` current facts of the conversation's household that share a word with what people said in
        it (its `person` turns; hers are not searched), best match first, followed by up to the recall policy's
        `vector_k` more whose meaning is nearest to it by embedding (so up to `limit + vector_k` in all), each at most
        once, whatever their visibility: this is what the write job decides against,
        never what anyone hears. The nearest-by-meaning facts are how a paraphrase of a known fact reaches the writer.
        The embedder being unavailable leaves the word matches alone. Nothing crosses households; no person turn, no
        facts."""

    @abstractmethod
    async def apply(self, household_id: int, conversation_id: int, ops: Sequence[Op], at: datetime,
                    written_through: int | None = None, written_from: int | None = None) -> tuple[int, ...]:
        """Carries out the write job's ops in one transaction: an `Add` or `Update` inserts a fact (an `Update` also
        closes its target), `Invalidate` closes its target, `Forget` deletes it and every fact it superseded, `Noop`
        changes nothing. Code pins `health` and `finance` facts to private here unless `visibility_stated`, and `diet` facts to
        standing. Returns the ids of the facts inserted, in op order.
        Each inserted fact is stored with its embedding; when the embedder cannot answer the facts are stored
        without one (never lost) and logged `memory.write_unembedded` by id, for `embed_missing` to fill.
        A target that is not a current fact of that household raises ValueError and nothing is applied.

        With `written_through`, the same transaction records the conversation as written through that turn id and
        clears its failures, so the ops and the record land together or not at all. When it was already written
        through that turn or later, or its watermark is no longer `written_from` (where the decision's turns began; None
        before any write), AlreadyWritten is raised and nothing is applied: the decision is stale, since another
        writer got to those turns first. The check holds the watermark row's lock until the transaction ends, so two
        writers over one conversation cannot both land."""

    @abstractmethod
    async def held(self, household_id: int, person_id: int, fact_id: int | None = None) -> tuple[Held, ...]:
        """The current facts of the household that concern `person_id`, newest `valid_from` first: those about them,
        those they own, and household facts (about and owned by nobody). Filtered as `recall` filters for that person
        on an owner-only channel, so another person's private fact never comes back, even when it is about them;
        `replaced` likewise only when they may see the fact it names. With `fact_id`, at most that fact. These are
        the facts the person may correct and forget (`decisions.md`, "People see, correct and forget what she
        knows of them")."""

    @abstractmethod
    async def forget(self, household_id: int, fact_id: int, by: int) -> int:
        """Deletes the current fact `fact_id` and every fact it superseded, however far back, embeddings with them,
        in one transaction, as a `Forget` op does; returns how many were deleted. Nothing is kept as history. Raises
        ValueError, deleting nothing, when it is not a current fact of the household. Says nothing about who may:
        the caller checks `held` first. Logs `memory.forgotten` with the household, `by` (the person who asked) and
        the count, never text."""

    @abstractmethod
    async def embed_missing(self, limit: int) -> int:
        """Embeds up to `limit` current facts, oldest first, that have no embedding or whose embedding was made by a
        model other than the one Inference now answers with; returns how many were embedded. Another model's embeddings
        are replaced, so changing the model re-embeds the facts in batches. Facts that are not current are left as
        they are. Embedding unavailable is not an error: it returns 0. Logs `memory.embed_backfill` (wanted, stored,
        model)."""

    @abstractmethod
    async def unwritten(self, idle_after_s: Mapping[ConversationKind, float], limit: int,
                        max_failures: int) -> tuple[Unwritten, ...]:
        """At most `limit` conversations that need a write, oldest last activity first: no turn for at least
        `idle_after_s` of their kind (idle or closed, by the database's clock), and a `person` turn newer than the
        turn they were written through. One whose last `max_failures` writes in a row failed is left out until a
        person turn newer than its last failure arrives."""

    @abstractmethod
    async def write_failed(self, household_id: int, conversation_id: int, through: int) -> int:
        """Records a failed write of the conversation's turns through `through`; returns the failures in a row, which
        starts again at 1 when `through` is newer than the last failure's."""

    @abstractmethod
    async def written_through(self, conversation_id: int) -> int | None:
        """The newest turn id the conversation was written through, as `apply` recorded it; None before its first
        write, or when no conversation has that id."""


class FactWriter(Service):
    """The write job's decision: what a conversation changed about what she knows. A Strategy, so the eval can run the
    real one against planted wrong ones; reached through the locator by the write job and by remembering one line
    (`ashley.memory.remember`)."""

    @classmethod
    def null(cls) -> "FactWriter":
        return NullFactWriter()

    @abstractmethod
    async def decide(self, conversation: Conversation, known: Sequence[Fact], now: datetime) -> tuple[Op, ...]:
        """One op per thing the conversation said that is worth deciding about, against `known`, the current facts
        most like it. Things said in jest, hypotheticals and passing mentions are not facts; restating a known fact is
        a `Noop` on it."""


class NullFactWriter(FactWriter):
    """Decides nothing: what an unwired process sees. Raises InferenceUnavailable, so a caller treats it as the model
    being down rather than as a conversation with nothing in it."""

    async def decide(self, conversation: Conversation, known: Sequence[Fact], now: datetime) -> tuple[Op, ...]:
        raise InferenceUnavailable("FactWriter is not wired")


class NullMemory(Memory):
    """Knows nothing: what an unwired process sees. Every call raises MemoryUnavailable, so a missing registration fails
    loudly instead of answering as though the household were strangers."""

    async def recall(self, asker: Asker, query: str) -> tuple[Recalled, ...]:
        raise MemoryUnavailable("Memory is not wired")

    async def profile(self, asker: Asker) -> tuple[Recalled, ...]:
        raise MemoryUnavailable("Memory is not wired")

    async def similar(self, conversation: Conversation, limit: int) -> tuple[Fact, ...]:
        raise MemoryUnavailable("Memory is not wired")

    async def apply(self, household_id: int, conversation_id: int, ops: Sequence[Op], at: datetime,
                    written_through: int | None = None, written_from: int | None = None) -> tuple[int, ...]:
        raise MemoryUnavailable("Memory is not wired")

    async def held(self, household_id: int, person_id: int, fact_id: int | None = None) -> tuple[Held, ...]:
        raise MemoryUnavailable("Memory is not wired")

    async def forget(self, household_id: int, fact_id: int, by: int) -> int:
        raise MemoryUnavailable("Memory is not wired")

    async def embed_missing(self, limit: int) -> int:
        raise MemoryUnavailable("Memory is not wired")

    async def unwritten(self, idle_after_s: Mapping[ConversationKind, float], limit: int,
                        max_failures: int) -> tuple[Unwritten, ...]:
        raise MemoryUnavailable("Memory is not wired")

    async def write_failed(self, household_id: int, conversation_id: int, through: int) -> int:
        raise MemoryUnavailable("Memory is not wired")

    async def written_through(self, conversation_id: int) -> int | None:
        raise MemoryUnavailable("Memory is not wired")
