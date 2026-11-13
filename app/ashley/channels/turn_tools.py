"""The tools one turn offers: its household's everyday tools (`tools.everyday.HouseholdTools`), the catalogue every
turn of the household shares, plus the sources this turn's `Inbound` fields call for, each built for this turn alone
and gone when it ends. A turn that calls for none gets the household's everyday tools alone. Chosen from fields the adapter set, never from what was said."""

from collections.abc import Callable, Mapping
from functools import partial

from .. import services
from ..connections.connections import Connections
from ..runs.sandbox import Sandbox
from ..codehost import config as codehost_config
from ..tools.arrival import Arrival
from ..tools.bench_automations import BenchAutomationTools
from ..tools.bench_files import BenchFileTools
from ..tools.bench_image import BenchImageTools
from ..tools.bench_jobs import BenchJobTools
from ..tools.bench_printables import BenchPrintablesTools
from ..tools.bench_look import BenchLookTools
from ..tools.bench_media import BenchMediaTools
from ..tools.claude_code import ClaudeCodeTools
from ..tools.claude_code_config import load as claude_code_config
from ..tools.code_host import CodeHostTools
from ..tools.bench_run import BenchRunTools
from ..tools.bench_skills import BenchSkillTools
from ..tools.bench_tidy import BenchTidyTools
from ..tools.bench_tools import BenchTools
from ..tools.composite import CompositeTools
from ..tools.discord_read import DiscordReadTools
from ..tools.errand_step import ErrandStepTools
from ..tools.everyday import HouseholdTools
from ..tools.house_change import HouseChangeTools
from ..tools.mail import MailTools
from ..tools.money import MoneyTools
from ..tools.money_config import load as money_config
from ..tools.move_page import MovePageTools
from ..tools.only import Only
from ..tools.reading import Reading
from ..tools.readers import ReaderTools
from ..tools.open_bench import OpenBenchTools
from ..tools.reminders import ReminderTools
from ..tools.results import Results
from ..tools.run_code import RunCodeTools
from ..tools.tools import Tools
from ..tools.watches import WatchTools
from . import said_links
from .audience import owner_alone, use_of
from .limits import load as load_limits, smallest_result_chars
from .devices_tool import DeviceTools
from .screen_tools import ScreenTools
from .model import Inbound
from .wake import reminder_device

EVERYDAY = "everyday"
"""The key the household's everyday tools go under when a turn adds sources; first, so its tools and instructions lead."""
READERS = "readers"
"""The key `send_readers` goes under, last: its readers read with the turn's other tools as narrowed, never with it."""
_MONEY = money_config()
_CODE_HOST = codehost_config.load()
_CLAUDE_CODE = claude_code_config()
READABLE_CHARS = smallest_result_chars(load_limits())
ERRAND = "errand"
"""The key `check_again` goes under on a check of an errand, beside the turn's tools as narrowed, never narrowed itself."""


def for_turn(inbound: Inbound, said: tuple[int, int] | None = None, arrival: Arrival | None = None,
             results: Results | None = None) -> Tools:
    """What `inbound`'s turn offers: with `bench_id` and a known speaker, that bench's tools (`bench`), worked as her
    on the speaker's bench, its Home Assistant automation tools (`automations`, an empty catalogue while the
    household has no house) and its kind of work with the household's skill for it (`skills`); with `opens_benches` and a known speaker, opening a bench for them (`open_bench`); with
    `on_page` and a known speaker, moving their page (`page`); with a known speaker or a device's own thread (`device_id`),
    arranging the household's screens (`screen`; the thread's own screen alone on a device's thread); where the reply reaches the speaker alone
    (`audience.owner_alone`) and connections can be opened, their household's finances (`money`) the speaker's own code host (`code_host`) Claude Code sessions (`claude_code`) and watches on what they connected (`watches`), each an
    empty catalogue until they connect one; with a known speaker,
    reading the mailboxes the resource gate allows the turn (`mail`, `ConnectionResources.usable`: any turn, speaker or not), setting reminders (`reminders`), reading the household's devices (`devices`), and listing and cancelling theirs only where the reply reaches them alone; with
    `said` (the conversation id and the person turn's id) and a `Sandbox` that runs some language, running code
    (`code`), recorded against that turn, whoever spoke, but on a bench with a known speaker running its code pieces
    instead (`bench_run`), recorded against the bench and the turn: code on a bench is a piece, never a loose run, and past
    `max_runs_per_turn` of them handed to a worker (`jobs`, `tools.bench_jobs`) where `hands_off`.
    With `moved_to`, the bench's tools are that bench's, not the thread's, and
    with `arrival` fresh (the bench was opened in this turn) or `lead` (the message opened it) its instructions tell her
    to lead (`bench_lead`).
    `arrival` is told by `open_bench` and `move_page`. With `tools_only`, all of that narrowed to the tools it
    names; with `reads_only`, to those that change nothing, where the reply reaches the speaker alone and else to none.
    From a server channel (`discord_channel`) with a known speaker, reading that channel's recent messages (`discord_read`). With a known speaker, `send_readers` (`readers`) too, whose readers read with the turn's other tools, so narrowed. `results` is the turn's numbered search results (`tools.results`), which her bench tools name a site or video
    by; the conversation she is in (`said`) is what they check a URL the person gave against. With `errand` and a known
    speaker, `check_again` (`errand`) beside all of that, not narrowed."""
    everyday = HouseholdTools(inbound.household_id)

    def usable() -> Tools:
        """What the speaker has in this turn except the reminder tools: what a reminder may name."""
        rest = {k: v for k, v in added.items() if k not in ("reminders", "watches")}
        return CompositeTools({EVERYDAY: everyday, **rest, READERS: readers})

    added = {**sources(inbound, arrival, said and said[0], results, said, usable), **_mail(inbound),
             **_code(inbound, said)}
    own = narrowed(inbound, CompositeTools({EVERYDAY: everyday, **added}) if added else everyday)
    readers = ReaderTools(lambda names: Reading(Only(own, names)))
    if inbound.speaker_id is None:
        return own
    turn = narrowed(inbound, CompositeTools({EVERYDAY: everyday, **added, READERS: readers}))
    if inbound.errand is None:
        return turn
    return CompositeTools({"turn": turn, ERRAND: ErrandStepTools(inbound.household_id, inbound.errand)})


def narrowed(inbound: Inbound, offered: Tools) -> Tools:
    """`offered` as `inbound` narrows it: to its reads with `reads_only` (to none unless the reply reaches the speaker
    alone), then to the tools `tools_only` names."""
    if inbound.reads_only:
        offered = Reading(offered) if owner_alone(inbound) else Only(offered, ())
    return offered if inbound.tools_only is None else Only(offered, inbound.tools_only)


def hands_off(inbound: Inbound) -> bool:
    """Whether this turn may hand a bench job to a worker: a bench's talk, the reply reaching the speaker alone, and
    nobody having woken it, so a woken turn cannot chain jobs."""
    return owner_alone(inbound) and not inbound.unprompted


def _mail(inbound: Inbound) -> Mapping[str, Tools]:
    """Her mail tools for every turn, whoever speaks: which mailboxes a turn may use is the resource gate's to say."""
    return {"mail": MailTools(use_of(inbound), READABLE_CHARS)} if services.get(Connections).can_open() else {}


def _code(inbound: Inbound, said: tuple[int, int] | None) -> Mapping[str, Tools]:
    if said is None or not services.get(Sandbox).languages():
        return {}
    bench = _bench_of(inbound)
    if bench is not None and inbound.speaker_id is not None:
        return {"bench_run": BenchRunTools(inbound.household_id, inbound.speaker_id, bench, *said,
                                           hand_off=hands_off(inbound))}
    return {"code": RunCodeTools(inbound.household_id, *said)}


def _bench_of(inbound: Inbound) -> int | None:
    return inbound.bench_id if inbound.moved_to is None else inbound.moved_to


def _screen(inbound: Inbound) -> Mapping[str, Tools]:
    """Her screen tools for a known speaker, and for a turn on a device's own thread whoever speaks; which screens that
    reaches is the tools' to say."""
    if inbound.speaker_id is None and inbound.device_id is None:
        return {}
    return {"screen": ScreenTools(inbound.household_id, inbound.speaker_id, inbound.device_id)}


def sources(inbound: Inbound, arrival: Arrival | None = None, conversation_id: int | None = None,
            results: Results | None = None, turn: tuple[int, int] | None = None,
            usable: Callable[[], Tools] | None = None) -> Mapping[str, Tools]:
    if inbound.speaker_id is None:
        return _screen(inbound)
    household, person = inbound.household_id, inbound.speaker_id
    found: dict[str, Tools] = {}
    bench = _bench_of(inbound)
    if bench is not None:
        found["bench"] = BenchTools(household, person, bench, lead=inbound.lead or (arrival is not None and arrival.fresh),
                                    results=results,
                                    said=None if conversation_id is None else said_links.by_people(conversation_id),
                                    turns=None if conversation_id is None else said_links.turns_by_people(conversation_id),
                                    turn_id=None if turn is None else turn[1])
        found["tidy"] = BenchTidyTools(bench)
        found["automations"] = BenchAutomationTools(household, person, bench)
        found["skills"] = BenchSkillTools(household, person, bench)
        found["files"] = BenchFileTools(household, person, bench)
        found["printables"] = BenchPrintablesTools(household, person, bench, results)
        if turn is not None:
            found["look"] = BenchLookTools(household, person, bench, *turn)
            found["image"] = BenchImageTools(household, person, bench, turn[0])
            found["media"] = BenchMediaTools(household, person, bench, *turn)
            if hands_off(inbound):
                found["jobs"] = BenchJobTools(household, person, bench, turn, services.get(Connections).can_open())
    if inbound.opens_benches:
        found["open_bench"] = OpenBenchTools(household, person, arrival)
    if inbound.on_page:
        found["page"] = MovePageTools(household, person, arrival)
    if owner_alone(inbound) and services.get(Connections).can_open():
        found["money"] = MoneyTools(household, _MONEY)
    if owner_alone(inbound) and services.get(Connections).can_open():
        found["code_host"] = CodeHostTools(household, person, bench, _CODE_HOST, READABLE_CHARS)
        found["claude_code"] = ClaudeCodeTools(household, person, _CLAUDE_CODE, READABLE_CHARS, bench)
        found["watches"] = WatchTools(household, person, bench_id=bench, turn=turn, usable=usable)
    if inbound.discord_channel is not None:
        found["discord_read"] = DiscordReadTools(inbound.discord_channel, READABLE_CHARS)
    found["reminders"] = ReminderTools(household, person, private=owner_alone(inbound), turn=turn, usable=usable,
                                       routable=partial(reminder_device.takes, household))
    found["devices"] = DeviceTools(household)
    found.update(_screen(inbound))
    found["house_change"] = HouseChangeTools(household, person, private=owner_alone(inbound), turn=turn)
    return found
