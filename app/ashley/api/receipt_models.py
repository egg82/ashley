"""What code shows beside a turn, on the wire (`conversations.model.Receipts`, `conversations.model.AgreedOutcome`): one
schema each for every route that carries it."""

from typing import Literal

from pydantic import BaseModel

from ..conversations.model import AgreedCall, AgreedOutcome, Fact, Receipt, Receipts


class WireReceipt(BaseModel):
    """One change: `headline` is the tool's plain label, `detail` code's own summary of the call (null where the reply
    was shared), `why` the reason it ran or waits, when there is one."""

    headline: str
    detail: str | None
    why: str | None


class WireFact(BaseModel):
    """A row of a bench's measurements piece shown beside her reply, once: a choice, or a guessed number a check of the
    turn's run rests on (its `value` with its unit). `label` and `value` as she set them, and `option_values`, each a tap
    that sets the row (`PUT /api/benches/{bench_id}/pieces/{piece_id}/choices/{name}`); empty when the row has none,
    as a number's."""

    bench_id: int
    piece_id: int
    name: str
    label: str
    value: str
    option_values: list[str]


class WireReceipts(BaseModel):
    """The changes that ran without asking (`ran`) and the calls waiting for the person's OK (`held`, each with its
    summary in full: the person agrees to what code wrote). `proposal_id` is the held proposal, null when nothing is
    held; whether it can still be agreed to is `ChatConversationTurn.agree`. `choice_rows` the rows of a bench shown to
    the person this turn, as they stood then."""

    ran: list[WireReceipt]
    held: list[WireReceipt]
    proposal_id: int | None
    choice_rows: list[WireFact]


def wire_receipts(receipts: Receipts | None) -> WireReceipts | None:
    return None if receipts is None else WireReceipts(
        ran=[_wire(r) for r in receipts.done], held=[_wire(r) for r in receipts.held], proposal_id=receipts.proposal_id,
        choice_rows=[_wire_fact(f) for f in receipts.facts])


def _wire_fact(fact: Fact) -> WireFact:
    return WireFact(bench_id=fact.bench_id, piece_id=fact.piece_id, name=fact.name, label=fact.label, value=fact.value,
                    option_values=list(fact.options))


def _wire(receipt: Receipt) -> WireReceipt:
    return WireReceipt(headline=receipt.headline, detail=receipt.detail, why=receipt.why)


class WireAgreedCall(BaseModel):
    """One held call the person agreed to: `summary`, code's own words for it as the person was shown it, and whether it
    `ran`, `failed` or was `not_run` (not offered where it was agreed). Never what the call returned."""

    summary: str
    status: Literal["ran", "failed", "not_run"]


class WireAgreed(BaseModel):
    """What became of a held proposal the person agreed to, shown beside their agreeing turn and never as her words:
    `carried`, each held call in the order it was held, or `interrupted` true with none when the run stopped partway, so any of
    them may or may not have taken effect."""

    carried: list[WireAgreedCall]
    interrupted: bool


def wire_agreed(outcome: AgreedOutcome) -> WireAgreed:
    return WireAgreed(carried=[_wire_call(c) for c in outcome.calls], interrupted=outcome.interrupted)


def _wire_call(call: AgreedCall) -> WireAgreedCall:
    return WireAgreedCall(summary=call.summary, status=call.status)
