"""The cheap model's pass over a bench's text pieces: the prompt it is given, the structured reply it must give, and the
check that every passage it points at is really there. The model only points; a quote that is not in the piece it names
is an invented one and is dropped."""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from ..inference.model import DEFAULT_VARIANT, Message, Prompt, SystemPrompt
from ..workshop.model import Piece
from .config import TidyConfig
from .tidy import Kind, NewFinding

SYSTEM = (
    "You read the text pieces of a working bench and point at passages that have gone wrong, for the person who owns "
    "them to check. You do not rewrite anything and you do not decide: you only point, and say why in a few words.\n\n"
    "Go through the pieces one at a time, then across them. A passage is one of these kinds.\n"
    "- `superseded`: a statement that a newer or more current statement, in the same piece or another, has replaced or "
    "answered. This includes a claim that something is missing, unknown, unconfirmed, unfinished or still to do, when "
    "another passage shows it has since been found, confirmed or done; and an older dated update sitting beside the "
    "current state it led to.\n"
    "- `contradicts`: a statement that cannot be true together with a statement elsewhere; name the other piece in "
    "`by_piece_id`.\n"
    "- `debris`: what editing left behind. A heading or lead-in that appears twice or is run together with the heading "
    "that follows it, a list introduced by a line that was meant to be replaced, a list item with nothing in it, a "
    "sentence that stops partway or starts partway, a label that says when something was updated wrapped around text "
    "that is simply the current state.\n"
    "- `duplicate`: a passage that says what another passage, in the same piece or another, already says.\n\n"
    "`quote` is copied character for character from the piece named by `piece_id`, short (a sentence or a heading), "
    "never joined across a gap, and points at the passage that should go or change, not at the one that is right. "
    "`by_piece_id` is the piece holding the passage it was judged against, or null when that passage is in the same "
    "piece or there is none. Report every passage you can quote and are sure of; a piece that reads cleanly gets "
    "nothing, and an empty list is a complete answer."
)


class Found(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    piece_id: int
    kind: Kind
    quote: str = Field(description="Copied exactly from the piece named by piece_id.")
    by_piece_id: int | None = Field(description="The other piece involved, or null.")
    why: str = Field(description="A few words saying how the passage is wrong.")


class Pointed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    findings: list[Found]


@dataclass(frozen=True)
class Asked:
    """What a pass sent: the prompt, and each piece's body as the model saw it by piece id (the cut part of a long one is
    not in it, so a quote from there is dropped)."""

    prompt: Prompt
    seen: Mapping[int, str]


def ask(pieces: Sequence[Piece], config: TidyConfig) -> Asked | None:
    """The prompt over the text pieces of `config.kinds`, newest change first until `max_total_chars` is spent, each
    cut to `max_piece_chars`; None when the bench has no such piece."""
    chosen: dict[int, str] = {}
    spent = 0
    for p in sorted((p for p in pieces if p.kind in config.kinds and p.text.body.strip()), key=lambda p: -p.changed_by):
        body = p.text.body[:config.max_piece_chars]
        if spent + len(body) > config.max_total_chars:
            continue
        chosen[p.id] = body
        spent += len(body)
    if not chosen:
        return None
    by_id = {p.id: p for p in pieces}
    parts = [f'Piece {i} ({by_id[i].kind}) "{by_id[i].text.title}"\n{chosen[i]}' for i in sorted(chosen)]
    text = "\n\n=====\n\n".join(parts)
    prompt = Prompt(system={DEFAULT_VARIANT: SystemPrompt(SYSTEM)}, messages=(Message("person", text),))
    return Asked(prompt, chosen)


@dataclass(frozen=True)
class Checked:
    """What a reply came to: the findings that stand, and how many the check dropped."""

    found: tuple[NewFinding, ...]
    dropped: int

    def per_kind(self) -> dict[str, int]:
        return dict(Counter(f.kind for f in self.found))


def check(pointed: Pointed, seen: Mapping[int, str], config: TidyConfig) -> Checked:
    """The findings of `pointed` that point at a real passage: the piece was sent, the quote is in the body the model saw
    and within the bounds, and it is not a repeat; `by_piece_id` is kept only when that piece was sent, else None. The
    first `max_findings` stand. The reason is cut to `max_why_chars`."""
    kept: dict[tuple[int, str], NewFinding] = {}
    for f in pointed.findings:
        body = seen.get(f.piece_id)
        quote = f.quote.strip()
        if (body is None or not config.min_quote_chars <= len(quote) <= config.max_quote_chars or quote not in body
                or (f.piece_id, quote) in kept):
            continue
        by = f.by_piece_id if f.by_piece_id in seen and f.by_piece_id != f.piece_id else None
        kept[(f.piece_id, quote)] = NewFinding(f.piece_id, f.kind, quote, by, f.why.strip()[:config.max_why_chars])
    standing = tuple(kept.values())[:config.max_findings]
    return Checked(standing, len(pointed.findings) - len(standing))
