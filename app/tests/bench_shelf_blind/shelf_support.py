"""Shared pieces of the shelf's blind contract tests: small rules a test can cross in a few commands, builders for the
commands, a fold of `decide` over a list of commands, and readers that look at a bench by ids."""

from collections.abc import Iterable
from types import MappingProxyType

from ashley.workshop.commands import Add, Archive, Command, Edit, Move, Remove, Restore, Undo
from ashley.workshop.decide import EMPTY, Accepted, BenchState, Decision, Refused, decide
from ashley.workshop.model import By, Piece, Place, Size, Text
from ashley.workshop.rules import Kind, Rules

NOTE = Kind("note", "stored", "Note", 10)
DOC = Kind("doc", "stored", "Doc", 50)
RULES = Rules(MappingProxyType({"note": NOTE, "doc": DOC}), max_pieces=3, title_max_chars=5, recent_commands=4,
              undo_window=100)
ALANA = By(7)
SAM = By(8)


def add(title: str = "a", body: str = "", kind: str = "note", size: Size = "small", by: By = ALANA) -> Add:
    return Add(by, kind, Text(title, body), size)


def edit(piece_id: int, base_version: int, title: str = "b", body: str = "", by: By = ALANA) -> Edit:
    return Edit(by, piece_id, base_version, Text(title, body))


def move(piece_id: int, order: int, size: Size = "small", by: By = ALANA) -> Move:
    return Move(by, piece_id, Place(order, size))


def remove(piece_id: int, by: By = ALANA) -> Remove:
    return Remove(by, piece_id)


def archive(piece_id: int, by: By = ALANA) -> Archive:
    return Archive(by, piece_id)


def restore(piece_id: int, by: By = ALANA) -> Restore:
    return Restore(by, piece_id)


def undo(seq: int, by: By = ALANA) -> Undo:
    return Undo(by, seq)


def fold(commands: Iterable[Command], rules: Rules = RULES, state: BenchState = EMPTY) -> list[Decision]:
    """Every command decided in turn by `decide` itself, each against the state the one before left."""
    out: list[Decision] = []
    for command in commands:
        decision = decide(state, command, rules)
        out.append(decision)
        state = decision.state
    return out


def last(*commands: Command) -> Decision:
    return fold(commands)[-1]


def end(*commands: Command) -> BenchState:
    return last(*commands).state


def reason(decision: Decision) -> str:
    assert isinstance(decision, Refused), f"expected a refusal, got {decision}"
    return decision.reason


def accepted(decision: Decision) -> Accepted:
    assert isinstance(decision, Accepted), f"expected an acceptance, got {decision}"
    return decision


def ids(pieces: Iterable[Piece]) -> list[int]:
    return [p.id for p in pieces]


def sizes(pieces: Iterable[Piece]) -> list[str]:
    return [p.place.size for p in pieces]


def shape(piece: Piece) -> tuple[int, str, Text, Place]:
    """A piece without its version and `changed_by`, which an undo moves on."""
    return (piece.id, piece.kind, piece.text, piece.place)


def core(piece: Piece) -> tuple[int, str, Text, str]:
    """A piece by what a round trip through the shelf cannot change: id, kind, words and size (its order and
    `changed_by` move)."""
    return (piece.id, piece.kind, piece.text, piece.place.size)


def three() -> list[Command]:
    """Three pieces a, b, c with ids 1, 2, 3 at orders 0, 1, 2, sizes small, medium, large."""
    return [add("a", "A", size="small"), add("b", "B", size="medium"), add("c", "C", size="large")]
