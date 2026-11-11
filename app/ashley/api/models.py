"""The API's wire models: one per response, one per error. A route declares them, so the OpenAPI document is exact
and the web client's types are generated from it (`api-contract-first`). A field name means one type across all of
them, which `tests/test_contract.py` checks. Add a model here before adding a route."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from ..channels.push import config as push_config
from ..conversations.model import Channel as ConversationChannel
from ..conversations.model import Kind as ConversationKind
from ..memory.model import Kind as FactKind, Visibility
from ..text import NoNul
from .chat_models import ChatAttachment
from .chat_models import ChatRequest as ChatRequest
from .look_models import ChatLook
from .people_models import MeResponse as MeResponse, Person as Person, wire_person as wire_person
from .receipt_models import WireAgreed, WireReceipts
from .run_models import ChatRun


class HealthResponse(BaseModel):
    """The process is up. Says nothing about the database."""

    status: Literal["ok"]
    version: str


class ReadyResponse(BaseModel):
    """A database connection could be opened. `writable` is false on a standby, which can serve reads only."""

    ready: Literal[True]
    writable: bool


class MessageRequest(BaseModel):
    """What a device heard or was sent. `text` is 1 to 4000 characters and not only whitespace. `thread`, when given,
    is 1 to 64 characters of `[A-Za-z0-9_-]`, the device's own name for a conversation it keeps apart from its others."""

    model_config = ConfigDict(extra="forbid")

    text: NoNul = Field(min_length=1, max_length=4000, pattern=r"\S")
    thread: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class MessageResponse(BaseModel):
    """Her reply. `body` is rendered for `medium`, the device's: for `spoken`, plain sentences to hand a TTS engine. It
    holds only her words; `receipts` is what code shows beside them, which a device that speaks says none of."""

    conversation_id: int
    medium: Literal["spoken", "text"]
    body: str
    receipts: WireReceipts | None = None


class ErrorResponse(BaseModel):
    """The body of every error a route declares. `code` is a stable machine-readable word a client branches on;
    `detail` is for a person and carries no data."""

    code: Literal["database_unavailable", "unauthorized", "refused", "unavailable", "not_found", "rate_limited", "forbidden",
                  "too_large", "unsupported", "closed", "label_taken", "too_many", "held_by_household", "version_conflict",
                  "gone", "expired", "not_yours", "stale", "admin_only", "last_admin", "admins_from_provider"]
    detail: str


class LinkedAccount(BaseModel):
    """One of the signed-in person's accounts elsewhere. `system` names where (`oidc`, `discord`,
    `home_assistant`); `handle` is the account's name there as it was when they linked it themselves, null when the
    admin mapped it. `unlinkable` is whether they may unlink it here, which only a Discord account is: unlinking the
    account they sign in with would sign them out for good."""

    id: int
    system: str
    handle: str | None
    unlinkable: bool


class AccountsResponse(BaseModel):
    """The signed-in person's accounts, oldest first. `discord_linking` is whether linking a Discord account is set up
    here; false, `start_discord_link` answers 503."""

    accounts: list[LinkedAccount]
    discord_linking: bool


class ListedDevice(BaseModel):
    """One of the household's devices. `form` is what it is wired to, not what it is called: a voice `satellite`, a
    household's `discord_server`, the household's Home Assistant (`household`, which hands in wakes), or `other` (the hallway
    tablet is one). `audience` is who hears or reads what it
    says and `medium` how it reaches them. Never a token, host or server id."""

    id: int
    name: str
    place: str
    form: Literal["satellite", "discord_server", "house", "other"]
    audience: Literal["owner", "household", "present"]
    medium: Literal["spoken", "text"]


class DevicesResponse(BaseModel):
    """The signed-in person's household's unrevoked devices, oldest first."""

    devices: list[ListedDevice]


class LinkStartResponse(BaseModel):
    """Where to send this browser to link a Discord account: Discord's authorization page, which returns it to
    `/connections?link=<outcome>`. Good for one link, within sign-in's `pending_minutes`."""

    authorize_url: str


class ReplacedFact(BaseModel):
    """The fact this one superseded: what it said, and when it stopped being true."""

    text: str
    valid_to: datetime


class FactSource(BaseModel):
    """Where a fact was learned. `took_part` is whether the person reading was in that conversation. `channel` is
    what the conversation started on and `place` where, when the channel is a shared device; each is null when not
    recorded (conversations from before, or a channel with no place). A correction made on the web is a `command`
    conversation of its own on the `web` channel, with the reader taking part."""

    conversation_id: int
    conversation_kind: ConversationKind
    started_at: datetime
    took_part: bool
    channel: ConversationChannel | None
    place: str | None


class MemoryFact(BaseModel):
    """A current fact that concerns the signed-in person: about them, theirs (`owner`), or the household's (`about`
    and `owner` both null). `valid_from` is when it became true to her, so "new this week" is a filter on it.
    `standing` facts reach every reply; the rest come back when a message bears on them. `replaced` is the fact this
    one superseded, when there was one the reader may see."""

    id: int
    text: str
    kind: FactKind
    standing: bool
    visibility: Visibility
    about: Person | None
    owner: Person | None
    valid_from: datetime
    replaced: ReplacedFact | None
    source: FactSource


class MemoryFactsResponse(BaseModel):
    """Every current fact that concerns the signed-in person, newest `valid_from` first. Never another person's
    private fact, even one about the reader."""

    items: list[MemoryFact]


class CorrectionRequest(BaseModel):
    """What the fact should say now: `text`, 1 to 1000 characters and not only whitespace, one statement true on its
    own. `visibility`, when given, is who may know it from now on; only the fact's owner may change it. The kind,
    who it is about and whose it is carry over."""

    model_config = ConfigDict(extra="forbid")

    text: NoNul = Field(min_length=1, max_length=1000, pattern=r"\S")
    visibility: Visibility | None = None


class MoveRequest(BaseModel):
    """Whose the fact is from now on: `household` makes it the household's (about and owner become null, and it is
    shared), allowed to the person who owns it when it is about them or about the household; `mine` makes a household
    fact theirs (owner becomes them). The text and kind carry over."""

    model_config = ConfigDict(extra="forbid")

    to: Literal["household", "mine"]


class RememberRequest(BaseModel):
    """A line to remember now: turn `turn_id` of conversation `conversation_id`, one the signed-in person took part
    in, either author's."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: int = Field(ge=1)
    turn_id: int = Field(ge=1)


class RememberResponse(BaseModel):
    """What remembering the line changed. `facts` are the facts she learned from it, and from any earlier lines of
    that conversation she had not learned from yet, that concern the reader, in the order she decided them, each with `replaced` when it updated an older one; `unseen` how many more she learned that
    the reader may not see; `ended` how many facts she knew stopped being current. All empty and zero: nothing new."""

    facts: list[MemoryFact]
    unseen: int
    ended: int


class ForgetResponse(BaseModel):
    """How many facts were deleted: the one forgotten and every earlier version it replaced. None of them is kept."""

    deleted: int


class KioskPairRequest(BaseModel):
    """A device token from `python -m ashley.channels.devices add`, pasted once on the tablet to pair it."""

    model_config = ConfigDict(extra="forbid")

    token: NoNul = Field(min_length=1, max_length=200)


class KioskDevice(BaseModel):
    """The device a kiosk browser is paired as: never a person. `place` is where it stands (`hallway`)."""

    id: int
    name: str
    place: str


class KioskGlance(BaseModel):
    """What the kiosk shows at a glance, shared things only. `home` is the first names of the household's people who
    are home: empty when everyone known is away, null when it cannot be known. `not_connected` names the glance's
    sources that have nothing behind them yet, which the page shows as not connected, never with sample data.
    `locale` (BCP 47) and `clock` are how the household writes dates and times, null when the household could not be
    read; the time itself is the tablet's own."""

    home: list[str] | None
    not_connected: list[Literal["calendar", "reminders"]]
    locale: str | None
    clock: Literal["12h", "24h"] | None


class KioskControl(BaseModel):
    """One touch control: `name` is its stable key, `label` what its button says. `on` is whether the light of a toggle
    is on now; null for any other control, and for a toggle whose light the house could not say."""

    name: str
    label: str
    on: bool | None


class KioskControls(BaseModel):
    """The kiosk's touch controls, in the order they are shown; empty when none are set."""

    controls: list[KioskControl]


class KioskControlDone(BaseModel):
    """Whether her tool reported the control carried out (`done`); false when the tool or the house refused it."""

    done: bool


class ChatReply(BaseModel):
    """Her reply on a web thread, as text. `follows` is true when it only says she will check, or, with an empty `body`,
    when her turn is still being worked on elsewhere: the answer is stored as her turn later, announced on
    `GET /api/live` as a `LiveTurn` for the thread; on the kiosk it is announced to the device's screen on
    `GET /api/kiosk/live`. `receipts` is what code shows beside her words after a turn that did or held changes."""

    conversation_id: int
    body: str
    follows: bool
    receipts: WireReceipts | None = None


class AgreeRequest(BaseModel):
    """The tap on a held receipt's Agree button: `proposal_id`, the `agree` of the turn whose receipts hold it, or the one
    a push notification carried."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: int = Field(ge=1)


class AgreeReply(BaseModel):
    """What agreeing did: `agreed`, what became of each held call, also kept on the agreeing turn in `conversation_id`
    (`ChatConversationTurn.agreed`). No turn of hers is stored."""

    conversation_id: int
    agreed: WireAgreed


class ChatTurn(BaseModel):
    """One turn of a web conversation: the person's, hers or the household's (`author`; the household speaking as itself,
    as in a wake, is never a person's words), what was said, and when it was stored. Memory
    is not read back onto a turn. `follows` is true on a line of hers that went out while her answer was still to
    come ("let me check"): the answer is a later turn, so a conversation ending with one is still owed it.
    `continued_on` is set on a turn of hers that hands the reader on to a bench, where the rest of her reply was said
    because the page moved there: the bench's id, and `text` the label of the link that opens it. `attachment` is
    what the person pasted with the message, on their turn, which a page shows folded; null on every other turn."""

    id: int
    author: Literal["person", "ashley", "household"]
    text: str
    at: datetime
    follows: bool
    continued_on: int | None
    attachment: ChatAttachment | None


class ChatConversationTurn(ChatTurn):
    """A turn of a conversation a web thread carries. `runs` are the scripts she ran to answer, in the order they ran,
    on her turn that is the final answer to the person's message that asked for them (not on a held line before it);
    empty on every other turn. `looks` are the pictures of a bench she was given, placed the same way. `working` is
    true on the person's turn still owed its answer while her work on it is in flight (a runner has it, or a resumed
    one will), so a page shows her still on it rather than the message missed; false on every other turn. `agree` is
    the id of the held proposal (`POST /api/chat/agree`) on her turn whose receipts hold it, while the person
    reading can still agree to it; null on every other turn, and on a conversation read for another thread than the
    person's own. `voiced` is true on her turn that has a voice stored (`Turn.spoken`). `receipts` is what code
    stored beside her words on that turn, whether or not `agree` is still offered. `agreed` is what became of the held
    calls a person's agreeing turn carried out, shown beside that turn; null on every other turn."""

    runs: list[ChatRun]
    looks: list[ChatLook]
    working: bool
    agree: int | None
    voiced: bool
    receipts: WireReceipts | None = None
    agreed: WireAgreed | None = None


class ChatConversation(BaseModel):
    """The conversation a web thread carries (a person's own, or the kiosk's), oldest turn first, while it is open or
    idle. Once it has closed, or before the first message, `conversation_id` and `started_at` are null and `turns` is
    empty: the next message starts a new one. `thread` is the web thread, which a `LiveTurn` names when it got a turn."""

    thread: str
    conversation_id: int | None
    started_at: datetime | None
    turns: list[ChatConversationTurn]


_PUSH = push_config.load()
_KEY = r"^[A-Za-z0-9_-]+={0,2}$"


def _push_service(endpoint: str) -> str:
    if not push_config.is_push_service(endpoint, _PUSH):
        raise ValueError("not a browser push service")
    return endpoint


PushEndpoint = Annotated[str, Field(min_length=9, max_length=2048), AfterValidator(_push_service)]
"""A browser's push service endpoint: an https URL on one of the browsers' own push services (`push.json`). A secret:
whoever holds it can push to that browser."""


class PushKeys(BaseModel):
    """The browser's keys for what is pushed to it, base64url, as `PushSubscription.toJSON()` gives them."""

    model_config = ConfigDict(extra="forbid")

    p256dh: str = Field(min_length=80, max_length=100, pattern=_KEY)
    auth: str = Field(min_length=16, max_length=32, pattern=_KEY)


class PushSubscriptionRequest(BaseModel):
    """This browser's push subscription, as `PushSubscription.toJSON()` gives it; extra fields it may carry
    (`expirationTime`) are ignored."""

    endpoint: PushEndpoint
    keys: PushKeys


class PushEndpointRequest(BaseModel):
    """Which browser: its push subscription's endpoint."""

    model_config = ConfigDict(extra="forbid")

    endpoint: PushEndpoint


class PushKeyResponse(BaseModel):
    """Her VAPID public key, base64url: the `applicationServerKey` a browser subscribes with."""

    public_key: str


class PushStateResponse(BaseModel):
    """The signed-in person's notifications: how many browsers they have subscribed, and whether the one asking is
    one of them."""

    subscriptions: int
    this_browser: bool
