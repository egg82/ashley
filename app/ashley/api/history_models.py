"""Wire models for a person's earlier conversations (`api.history`)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from ..conversations.model import Channel as ConversationChannel
from ..conversations.model import Kind as ConversationKind
from .models import ChatTurn


class PastSummary(BaseModel):
    """One conversation the signed-in person took part in, on any channel. `channel` is what it started on and `place`
    where, when the channel is a shared device; each is null when not recorded (conversations from before, or a
    channel with no place). `state` is as of the read."""

    id: int
    kind: ConversationKind
    state: Literal["open", "idle", "closed"]
    started_at: datetime
    last_activity_at: datetime
    channel: ConversationChannel | None
    place: str | None
    turn_count: int


class PastHistory(BaseModel):
    """A page of `PastSummary`, newest activity first. `next` is the `before` that reads the following page, null on
    the last."""

    conversations: list[PastSummary]
    next: str | None


class PastTurn(ChatTurn):
    """A turn of an earlier conversation. `speaker` is the first name the household knows the person by who said it,
    the household's name on its own turn, null for her turns and a speaker no one identified."""

    speaker: str | None


class PastConversation(PastSummary):
    """An earlier conversation with its turns, oldest first."""

    lines: list[PastTurn]
