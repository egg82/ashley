"""Wire models for the open screens' feed (`api.live`, and the kiosk's, `api.kiosk`): one `LiveEvent` per `data:` line."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, RootModel

from ..live.events import PageRoom


class LiveState(BaseModel):
    """Her state in one turn on a channel this person may see: their own (a DM, their web chat) or a shared one (a
    satellite, a shared Discord channel), never which room or who is talking. `turn` is a random token naming the
    turn. A screen shows her `listening`, `thinking` or `speaking` while any turn it heard is, until that turn's `idle` or
    `at_most_s` after it heard the state, whichever is first."""

    type: Literal["state"]
    turn: str
    state: Literal["listening", "thinking", "speaking", "idle"]
    at_most_s: float


class LiveTurn(BaseModel):
    """A turn was stored on `thread`, one of this person's own threads (`ChatConversation.thread` names the web one):
    a page showing it reads the conversation back."""

    type: Literal["turn"]
    thread: str


class LiveFailed(BaseModel):
    """A turn on `thread`, one of this person's own, ended with no reply after its request had returned pending (an
    empty `ChatReply.body` with `follows`): a page showing it shows the person's last message as unanswered, `why`
    as the request would have said (`unavailable` a 503, `refused` a 422); `retrying` it failed and its work is kept to try
    again, `unfinished` it failed with nothing she could say, `too_big` the work was too big for one reply and is not
    tried again: the page words each and no turn of hers carries them."""

    type: Literal["failed"]
    thread: str
    why: Literal["unavailable", "refused", "retrying", "unfinished", "too_big"]


class LiveBench(BaseModel):
    """Command `seq` changed bench `bench_id`, one of this person's own: a page showing it reads the bench back."""

    type: Literal["bench"]
    bench_id: int
    seq: int


class LiveCue(BaseModel):
    """She cued the player of video piece `piece_id` on this person's bench `bench_id`: `play`, `pause`, or `seek` to
    `seconds`. Heard only by the screens open now; a page showing the piece drives its player and reads nothing back."""

    type: Literal["cue"]
    bench_id: int
    piece_id: int
    action: Literal["play", "pause", "seek"]
    seconds: float | None


class LivePage(BaseModel):
    """She moved this person's page to `room`, and to bench `bench_id` in the workshop when it is set: each of their
    open pages flies there, or, while the person is in the middle of something, offers to follow her."""

    type: Literal["page"]
    room: PageRoom
    bench_id: int | None


class LiveScreen(BaseModel):
    """Command `seq` changed the screen of device `device_id`, one of the household's: a tablet showing that screen reads
    its layout back, and the Devices room its buttons."""

    type: Literal["screen"]
    device_id: int
    seq: int


class LiveResync(BaseModel):
    """Something may have been missed (the feed reconnected, or this stream fell behind): read back what is shown, and
    forget the turns heard so far."""

    type: Literal["resync"]


class LiveEvent(RootModel[Annotated[LiveState | LiveTurn | LiveFailed | LiveBench | LiveCue | LivePage | LiveScreen | LiveResync, Field(discriminator="type")]]):
    """One event on `GET /api/live`, the JSON of one `data:` line, told apart by `type`."""
