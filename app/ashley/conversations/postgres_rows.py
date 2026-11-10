"""Rows to values."""

from datetime import UTC, datetime
from typing import Any, get_args

from .model import AgreedOutcome, Attachment, Author, Channel, Conversation, Kind, Receipts, State, Summary, Turn
from .policy import KINDS as KIND_NAMES

KINDS: dict[str, Kind] = {k: k for k in KIND_NAMES}
CHANNELS: dict[str, Channel] = {c: c for c in get_args(Channel)}
AUTHORS: dict[str, Author] = {a: a for a in get_args(Author)}

TURN_COLUMNS = "id, author, speaker_id, text, at, follows, conversation_id, answers, carried_from, continued_on, attachment_title, attachment, spoken, receipts, agreed"


def utc(moment: datetime) -> datetime:
    return moment.astimezone(UTC)


def turn_from(row: tuple[Any, ...]) -> Turn:
    attached = None if row[11] is None else Attachment(row[10], row[11])
    return Turn(row[0], AUTHORS[row[1]], row[2], row[3], utc(row[4]), row[5], row[6], row[7], row[8], row[9], attached,
                row[12], None if row[13] is None else Receipts.from_json(row[13]),
                None if row[14] is None else AgreedOutcome.from_json(row[14]))


def conversation_from(row: tuple[Any, ...], participants: frozenset[int], turns: tuple[Turn, ...],
                      state: State, channel: str | None, place: str | None) -> Conversation:
    """`row` is id, household_id, kind, started_at, last_activity_at."""
    return Conversation(row[0], row[1], KINDS[row[2]], participants, utc(row[3]), utc(row[4]), state, turns,
                        None if channel is None else CHANNELS[channel], place)


def summary_from(row: tuple[Any, ...], state: State) -> Summary:
    """`row` is id, kind, started_at, last_activity_at, channel, place, turn count."""
    return Summary(row[0], KINDS[row[1]], state, utc(row[2]), utc(row[3]), None if row[4] is None else CHANNELS[row[4]], row[5], row[6])
