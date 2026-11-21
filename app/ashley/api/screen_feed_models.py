"""Wire models for a camera's live feed on a screen (`api.screen_feed`)."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, RootModel


class FeedIceServer(BaseModel):
    """A server the page's `RTCPeerConnection` may use, as its `iceServers` entry."""

    urls: list[str]
    username: str | None
    credential: str | None


class ScreenFeed(BaseModel):
    """The feed this screen shows: the camera's `camera_title`, the seconds it stays (`remaining_s`, after which the page
    takes it down), and what the page's connection needs (`ice_servers`, and `data_channel`, the channel its offer
    carries when it is not null). An empty `ice_servers` means the service gave none."""

    camera_title: str
    remaining_s: float
    ice_servers: list[FeedIceServer]
    data_channel: str | None


class ScreenFeedRead(BaseModel):
    """`feed` is null when this screen shows none."""

    feed: ScreenFeed | None


class FeedDismiss(BaseModel):
    """The screen whose feed is taken off: the token it opened its live feed under."""

    screen: UUID


class FeedOffer(BaseModel):
    """The page's WebRTC offer for the feed it shows: `screen` is the token it opened its live feed under, `offer` its SDP."""

    screen: UUID
    offer: Annotated[str, Field(min_length=1, max_length=65536)]


class FeedCandidate(BaseModel):
    """One of the page's ICE candidates for the feed `session_id` (from the offer's `session` signal), as the browser's
    `RTCIceCandidateInit` names its fields."""

    screen: UUID
    session_id: Annotated[str, Field(min_length=1, max_length=200)]
    candidate: Annotated[str, Field(min_length=1, max_length=4096)]
    sdp_mid: Annotated[str, Field(max_length=200)] | None = None
    sdp_m_line_index: Annotated[int, Field(ge=0, le=1024)] | None = None
    username_fragment: Annotated[str, Field(max_length=200)] | None = None


class FeedSession(BaseModel):
    """The camera's service took the offer: the page's later candidates name `session_id`."""

    type: Literal["session"]
    session_id: str


class FeedAnswer(BaseModel):
    """The camera's answer (SDP), for `setRemoteDescription`."""

    type: Literal["answer"]
    answer: str


class FeedRemoteCandidate(BaseModel):
    """A candidate from the camera's side, for `addIceCandidate` (a page that has neither `sdp_mid` nor
    `sdp_m_line_index` uses mid `0`)."""

    type: Literal["candidate"]
    candidate: str
    sdp_mid: str | None
    sdp_m_line_index: int | None
    username_fragment: str | None


class FeedError(BaseModel):
    """The feed could not be set up or has ended, `code` the service's own short reason or `unavailable`: the page says the
    camera did not answer."""

    type: Literal["error"]
    code: str


class FeedSignal(RootModel[Annotated[FeedSession | FeedAnswer | FeedRemoteCandidate | FeedError, Field(discriminator="type")]]):
    """One `data:` line of the offer's stream, told apart by `type`."""
