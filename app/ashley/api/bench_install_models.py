"""Wire models for an automation piece's installing into Home Assistant (`BenchPiece.automation`): her proposal waiting
on the person's approval, and what the latest install, or undo of one, did to the house."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from ..workshop.installs import Ending, InstallRecord
from ..workshop.proposals import Proposal
from ..workshop.shadows import ShadowRun
from ..workshop.wake_links import WakeLinks


class InstallProposal(BaseModel):
    """Her proposal `seq` to install the piece as it is at `piece_version`: `enabled` or not once installed, turning off
    `turn_off` (an automation's entity id) with it, null for none. The person approves it with an `install` command
    naming `seq`. A `shadow` proposal is for a shadow run: the piece installed as a shadow that only records when it
    would have fired, turning nothing off (`turn_off`, then, is the automation it would replace, which is recorded
    beside it)."""

    seq: int
    piece_version: int
    enabled: bool
    turn_off: str | None
    shadow: bool


class InstallState(BaseModel):
    """What the latest install of the piece, or undo of one, did to the house. `seq` is its command; `action`
    `install` or `uninstall`; `automation_id` the id it is installed under in Home Assistant, the same for every
    install of the piece; for an install, `enabled` as chosen (null for an uninstall) and `turn_off` the automation
    it turned off (an uninstall's, the one it turned back on). `install_ending` is null while it runs, and for good
    when its runner stopped part way (it is never carried out again; check the house); `done`; `refused` (Home
    Assistant refused the config, `install_note` its reason; nothing was written) or `failed` (`install_note` says
    from which step, and whether anything may have changed)."""

    seq: int
    action: Literal["install", "uninstall"]
    automation_id: str
    enabled: bool | None
    turn_off: str | None
    started_at: datetime
    install_ending: Ending | None
    install_note: str | None
    finished_at: datetime | None


class ShadowFiring(BaseModel):
    """One recorded firing: `would`, the piece's shadow fired (it would have), or `did`, the automation it would replace
    was triggered, at `at`."""

    kind: Literal["would", "did"]
    at: datetime


class ShadowState(BaseModel):
    """The latest shadow run of the piece, begun by install command `seq` of the piece at `piece_version` and set to
    end at `ends_at`; `ended_at` is null while it runs (a person takes it out with an `undo` of `seq`). `replaces` says
    whether it names an automation to record beside it (`did` is then meaningful, else always 0). `would` and `did`
    count the firings kept, `firings` the newest of them, newest first."""

    seq: int
    piece_version: int
    started_at: datetime
    ends_at: datetime
    ended_at: datetime | None
    replaces: bool
    would: int
    did: int
    firings: list[ShadowFiring]


class PieceAutomation(BaseModel):
    """An automation piece's installing: `install_proposal` waiting on the person's approval (null when none is, or the
    piece changed since it was made), and `last_install`, what the latest install or undo of one did (null for a piece
    never installed). `unanswered_events` are the wake events the installed automation sends that no wake rule on an
    open bench of the household answers: Home Assistant sends them and nothing happens (empty when it is not installed,
    sends none, or every one has a rule)."""

    install_proposal: InstallProposal | None
    last_install: InstallState | None
    unanswered_events: list[str]
    shadow: ShadowState | None


def shadow_of(run: ShadowRun | None) -> ShadowState | None:
    if run is None:
        return None
    began = run.started
    return ShadowState(seq=began.install_seq, piece_version=began.version, started_at=began.started_at,
                       ends_at=began.ends_at, ended_at=run.ended_at, replaces=began.mirrors is not None,
                       would=run.would, did=run.did, firings=[ShadowFiring(kind=f.kind, at=f.at) for f in run.firings])


def automation_of(proposal: Proposal | None, last: InstallRecord | None, links: WakeLinks,
                  run: ShadowRun | None = None) -> PieceAutomation:
    shown = None if proposal is None else InstallProposal(
        seq=proposal.seq, piece_version=proposal.proposed.version, enabled=proposal.proposed.enabled,
        turn_off=proposal.proposed.turn_off, shadow=proposal.proposed.shadow)
    shadow = shadow_of(run)
    if last is None:
        return PieceAutomation(install_proposal=shown, last_install=None, unanswered_events=[], shadow=shadow)
    began = last.started
    state = InstallState(seq=began.seq, action=began.action, automation_id=began.automation_id, enabled=began.enabled,
                         turn_off=began.turn_off, started_at=last.started_at, install_ending=last.ending,
                         install_note=last.note, finished_at=last.finished_at)
    sends = began.wake_events if began.action == "install" and last.ending == "done" else ()
    return PieceAutomation(install_proposal=shown, last_install=state, unanswered_events=list(links.unanswered(sends)),
                           shadow=shadow)
