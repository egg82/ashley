"""Wire model for a wake rule piece's senders (`BenchPiece.wake`): the installed automations that send its event."""

from pydantic import BaseModel

from ..workshop.wake_links import WakeLinks
from ..workshop.wake_rule import rule_of


class WakeSender(BaseModel):
    """An installed automation that sends the rule's event: its piece `piece_id` on bench `bench_id`, named by `title`
    on the viewer's own benches and null on another member's."""

    bench_id: int
    piece_id: int
    title: str | None


class PieceWake(BaseModel):
    """A wake rule piece's `senders`: the automations installed in Home Assistant, as their latest install left them,
    whose wake action names the rule's event. Empty when none does, or the piece holds no rule yet."""

    senders: list[WakeSender]


def wake_of(body: str, links: WakeLinks) -> PieceWake:
    rule = rule_of(body)
    found = () if rule is None else links.senders_of(rule.event)
    return PieceWake(senders=[WakeSender(bench_id=s.bench_id, piece_id=s.piece_id, title=s.title) for s in found])
