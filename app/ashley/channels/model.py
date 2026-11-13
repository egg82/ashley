"""What a channel hands in and gets back, as values."""

from dataclasses import dataclass
from typing import Literal

from ..conversations.model import Attachment, Channel, Kind, Receipts
from ..workshop.model import thread_of

Medium = Literal["spoken", "text"]
"""How a channel's reply reaches people: heard (a satellite, a speaker) or read (a chat, a screen)."""

Audience = Literal["owner", "household", "present"]
"""Who can hear or read what is said on a channel, which private-answer routing checks: `owner`, only the person the
account belongs to (a Discord DM, a web login); `household`, anyone in it (a shared Discord channel); `present`,
whoever is in the room or home (a satellite, the hallway tablet)."""


@dataclass(frozen=True)
class Device:
    """A shared device signed in as itself, never as a person: a satellite, the hallway tablet, the eval harness. It
    names a place (`kitchen`, `hallway`) and declares its audience (`household` or `present`), the medium its replies
    are delivered in, the kind of conversation it opens, and whether those conversations are remembered (`remembers`;
    false for the eval harness and test devices)."""

    id: int
    household_id: int
    name: str
    place: str
    audience: Audience
    medium: Medium
    kind: Kind
    remembers: bool = True


Form = Literal["satellite", "discord_server", "house", "other"]
"""What a device is, by what it is wired to: a voice satellite (it has an ESPHome host), a household's Discord server
(it has a server), the household's Home Assistant (set as the house, the one device that hands in wakes), else other.
Never read from its name."""

Capability = Literal["controls"]
"""What a device can do, said when it is registered rather than worked out from what it is: `controls`, it is a screen
that shows touch controls (the hallway tablet). Only a text device that is not a satellite, a Discord server or the
house can have it."""


@dataclass(frozen=True)
class Listed:
    """A device as a household's list shows it: the device, its `form` and its `capabilities`. Carries no token, host
    or server id."""

    device: Device
    form: Form
    capabilities: frozenset[Capability] = frozenset()

    @property
    def takes_controls(self) -> bool:
        """Whether the device has the `controls` capability: the Devices room offers the controls editor by this and
        nothing else."""
        return "controls" in self.capabilities


@dataclass(frozen=True)
class Satellite:
    """A device that is a voice satellite: reached over the ESPHome native API at `host` (a name or IP, port 6053),
    its reply played on `room_speaker` (a Home Assistant `media_player` entity id) when it names one, else on the
    satellite's own speaker."""

    device: Device
    host: str
    room_speaker: str | None


@dataclass(frozen=True)
class DiscordServer:
    """A device that is a household's Discord server: `guild_id` is the server's snowflake, `home_channel_id` the
    text channel she calls home (where she posts on her own initiative)."""

    device: Device
    guild_id: int
    home_channel_id: int


Taint = Literal["watch", "stranger", "inherited", "pasted"]
"""What outside started a turn: the wake of a watch whose kind reads outside text (`watch`), or a Discord server message
by an author who is not a member of that household (`stranger`), or the firing of a reminder or watch that a tainted turn
made (`inherited`), or a person's message whose pasted or forwarded block is over the threshold (`pasted`,
`channels.pasted`)."""


@dataclass(frozen=True)
class Inbound:
    """One message arriving on a channel. `thread` is the channel's key for where it came from (`Conversations.
    for_thread`). `speaker_id` is the person when the channel itself names them (a personal account), else None;
    `shared` says whether others use this channel, so presence may name the speaker when the channel does not.
    `place` is where a shared device is, None for a personal channel. `channel` is the kind of channel it arrived on,
    recorded on a conversation it starts. `text` is what was said, in real spellings,
    non-empty. `remembers` is whether a conversation this message starts is remembered (the device's `remembers`); a
    conversation continued from the thread keeps the value it started with. `heard_as` is the person a voice match
    names, set only by a voice channel: a hint the speaker step weighs after `speaker_id` (`speaker.who`). `later` is
    whether the channel takes replies said after the response, so a "let me check" can go out first; `later_by` is how
    such a reply reaches it: queued in the `Outbox` for the thread (`outbox`), or only stored as her turn, which an
    open page learns of from Live and reads back (`turn`). `device_id` is the device whose screen shows this thread, set
    only by a channel with such a screen (the kiosk): each turn stored on the thread is announced to that screen.
    `bench_id` is the bench whose talk this thread is, set only by the bench adapter, and offers her that bench's tools;
    `opens_benches` offers her a tool to open a bench for the speaker, set only by the person's own web chat;
    `on_page` says the channel is the speaker's own page (their web chat, a bench's talk), and offers her moving it
    (`turn_tools.for_turn`). `source` is the channel's id for the message (`discord:<message id>`), set only by a
    channel that may hand one message in twice: the person turn it is stored once (`NewTurn.source`). `unprompted` says
    nobody is waiting on the response (a wake from the household): the turn never holds unless it is `watched`, and its answer, from whichever
    runner finishes it, is queued in the `Outbox` for the thread with her stored turn only when `Initiative` says it
    goes out, else her turn is stored as `unprompted.QUIET`. `author` is who the message is by: `household` for an event the
    household reported (a wake), stored as a turn of the household with no speaker, never as the words of the person it is
    about; `note` is words for her alone, added to this turn's message in her prompt and never stored (a wake's brief), so
    never shown or carried. `promised` says the person asked for this turn earlier (a reminder firing): it goes out whatever
    `Initiative` would say, and her reply only words it. `tools_only` narrows what the turn offers to the tools named
    (`ashley.tools.only.Only`); None offers all. `reads_only` narrows it to the tools that change nothing
    (`ashley.tools.reading.Reading`), and only where `audience.owner_alone`; elsewhere it offers none. `moved_to` is the bench this turn has taken the speaker's page to
    (`channels.landing`): the rest of the turn is that bench's, its tools offered and her reply said in its talk. `steers`: a message that arrives while
    another turn of this thread is running is handed to that turn instead of starting its own (`channels.steering`).
    `lead` says this message opened the bench `bench_id` (a person's ask from the Workshop list), so she is told to
    lead as on a bench she opened herself. `watched` says the person is on the page the turn's replies are stored on (a
    bench's reaction to what they just did), so an unprompted turn holds as a person's does. `taint` is what outside
    started the turn, None for a turn started by the household itself: a turn with a `taint` is tainted from its first
    step (`channels.taint`). `made_in` is the conversation and turn that made the reminder or watch whose wake this is, set
    with the origin `inherited` (`Reminder.made_in`): the action judge's words are read from it (`channels.judge_words`).
    `agree` is the id of the held proposal a person tapped Agree on: set only by the web adapter's
    agree route, with an empty `text`, it makes the turn a command to carry out what was held (`channels.agree`) with no
    model step, and it never goes through `respond`. `attachment` is the block the person pasted or forwarded with the message, stored on their turn apart from `text`
    (`Turn.attachment`) and read by her with it; the adapter that sets it sets `taint` `pasted` when `channels.pasted`
    says it is over the threshold. `said_aloud` says the words came from the page's record button, set only by the web
    chat and kiosk adapters from the request: it offers her to answer aloud (`channels.aloud.offered`), and `medium` stays
    `text`."""

    household_id: int
    thread: str
    text: str
    kind: Kind
    medium: Medium
    audience: Audience
    speaker_id: int | None
    shared: bool
    place: str | None
    channel: Channel
    remembers: bool = True
    heard_as: int | None = None
    later: bool = False
    later_by: Literal["outbox", "turn"] = "outbox"
    device_id: int | None = None
    bench_id: int | None = None
    opens_benches: bool = False
    on_page: bool = False
    source: str | None = None
    unprompted: bool = False
    author: Literal["person", "household"] = "person"
    note: str | None = None
    promised: bool = False
    tools_only: tuple[str, ...] | None = None
    reads_only: bool = False
    moved_to: int | None = None
    steers: bool = False
    lead: bool = False
    watched: bool = False
    taint: Taint | None = None
    made_in: tuple[int, int] | None = None
    agree: int | None = None
    attachment: Attachment | None = None
    said_aloud: bool = False

    @property
    def lands_on(self) -> int | None:
        """The bench where her reply is said: the one this turn moved the page to, when that is not the bench whose
        talk this already is."""
        return self.moved_to if self.moved_to != self.bench_id else None

    @property
    def paged(self) -> bool:
        """Whether the person reads this channel on a page that learns of a turn from Live (`later_by` `turn` in text: web
        chat, a bench's talk, the kiosk), so a turn that fails is shown there by the page and code writes no words for it.
        A reply meant to be heard (`medium` spoken) is always a line said."""
        return self.later_by == "turn" and self.medium == "text"

    @property
    def holds(self) -> bool:
        """Whether a reply that is not yet the answer may go out first, with the answer later."""
        return self.later and (self.watched or not self.unprompted)


@dataclass(frozen=True)
class Outbound:
    """Her reply for the channel to deliver: `body` rendered for `medium` (`render.render`). `follows` is true when it
    only says she will check, and the answer will come through the `Outbox` for the thread. `quiet` is true when the turn
    was on her own initiative and she kept it to herself (`unprompted.QUIET` is what was stored). `agree` is the id of the
    held proposal `receipts` shows, so a channel that can offer one tap offers it (the web push notification's Agree
    action); it is set from `receipts` for one release and then dropped. `receipts` is what code shows beside the
    reply (`conversations.model.Receipts`), never part of `body`; None when there is none."""

    conversation_id: int
    medium: Medium
    body: str
    follows: bool = False
    quiet: bool = False
    agree: int | None = None
    receipts: Receipts | None = None


def on_bench(household_id: int, speaker_id: int | None, bench_id: int, text: str) -> Inbound:
    """A message on a bench's talk as the turn loop takes it: on the bench's thread, its owner the speaker and the only
    audience, a `brainstorm` conversation in text whose replies are stored as her turns, and whose messages steer."""
    return Inbound(household_id=household_id, thread=thread_of(bench_id), text=text, kind="brainstorm", medium="text",
                   audience="owner", speaker_id=speaker_id, shared=False, place=None, channel="web", later=True,
                   later_by="turn", bench_id=bench_id, on_page=True, steers=True, taint=None)
