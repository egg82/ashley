"""Wire models for an automation piece's installing into Home Assistant (`BenchPiece.automation`): her proposal waiting
on the person's approval, and what the latest install, or undo of one, did to the house."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from ..workshop.installs import Ending, InstallRecord
from ..workshop.proposals import Proposal


class InstallProposal(BaseModel):
    """Her proposal `seq` to install the piece as it is at `piece_version`: `enabled` or not once installed, turning off
    `turn_off` (an automation's entity id) with it, null for none. The person approves it with an `install` command
    naming `seq`."""

    seq: int
    piece_version: int
    enabled: bool
    turn_off: str | None


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


class PieceAutomation(BaseModel):
    """An automation piece's installing: `install_proposal` waiting on the person's approval (null when none is, or the
    piece changed since it was made), and `last_install`, what the latest install or undo of one did (null for a piece
    never installed)."""

    install_proposal: InstallProposal | None
    last_install: InstallState | None


def automation_of(proposal: Proposal | None, last: InstallRecord | None) -> PieceAutomation:
    shown = None if proposal is None else InstallProposal(
        seq=proposal.seq, piece_version=proposal.proposed.version, enabled=proposal.proposed.enabled,
        turn_off=proposal.proposed.turn_off)
    if last is None:
        return PieceAutomation(install_proposal=shown, last_install=None)
    began = last.started
    state = InstallState(seq=began.seq, action=began.action, automation_id=began.automation_id, enabled=began.enabled,
                         turn_off=began.turn_off, started_at=last.started_at, install_ending=last.ending,
                         install_note=last.note, finished_at=last.finished_at)
    return PieceAutomation(install_proposal=shown, last_install=state)
