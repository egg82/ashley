"""Her Home Assistant automation tools on one bench, for one turn of its talk (`channels.turn_tools`), offered while
the bench's household has a house (`House.offered`): read the house's automations, read one's config as a
piece's body, propose installing a piece (a Propose command by her, through `Workshop.apply`), and read where its
install stands. Nothing here writes to the house: an install is the person's Install command, carried out by
`workshop.install_piece`."""

import time
from collections.abc import Mapping
from datetime import tzinfo

from .. import services
from ..home_assistant.homes import house_of
from ..home_assistant.house import ConfigItem, House, HouseUnavailable, has_action
from ..inference.model import ToolCall, ToolResult
from ..people.zone import zone_of
from ..stamp import stamp
from ..workshop import automation_config, wake_action
from ..workshop.commands import Propose
from ..workshop.installs import InstallRecord, Installs, InstallsUnavailable
from ..workshop.model import HER, Owner
from ..workshop.workshop import BenchClosed, BenchNotFound, Workshop, WorkshopUnavailable
from . import bench_results
from .bench_args import BadArguments, check_names, piece_id_of
from .bench_automation_specs import LIST, PROPOSE, READ, SPECS, instructions
from .tools import Catalogue, Tools

NO_SUCH = "the house has no automation by that id; house_automations lists them"
NO_ENTITY = "turn_off names no automation of the house by entity id (automation.<x>); house_automations lists them"


class BenchAutomationTools(Tools):
    def __init__(self, household_id: int, person_id: int, bench_id: int) -> None:
        self._owner = Owner(household_id, person_id)
        self._bench = bench_id
        self._catalogue: Catalogue | None = None

    async def catalogue(self) -> Catalogue:
        """Empty while the household has no house, or which one cannot be read now. The house is asked once for the
        turn these tools were built for."""
        if self._catalogue is None:
            house = await self._house()
            self._catalogue = (Catalogue(SPECS, instructions(await has_action(house, wake_action.SERVICE)))
                               if house.offered() else Catalogue((), None))
        return self._catalogue

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises for what the house, the bench or the model did: each is an error result, logged `tools.call`
        with the bench, piece and seq ids."""
        started = time.monotonic()
        spec = next((s for s in SPECS if s.name == call.name), None)
        if spec is None:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        try:
            check_names(call.arguments, spec)
            if call.name == LIST:
                return await self._list(call, started)
            if call.name == READ:
                return await self._read(call, started)
            if call.name == PROPOSE:
                return await self._propose(call, started)
            return await self._state(call, started)
        except BadArguments as e:
            return bench_results.failed(call, started, "bad_arguments", str(e), bench=self._bench)
        except ValueError:
            return bench_results.failed(call, started, "bad_text", bench_results.BAD_TEXT_HINT, bench=self._bench)
        except BenchNotFound:
            return bench_results.failed(call, started, "not_found", "this bench is gone", bench=self._bench)
        except BenchClosed:
            return bench_results.failed(call, started, "closed", "this bench is closed and takes no change",
                                        bench=self._bench)
        except (WorkshopUnavailable, InstallsUnavailable, HouseUnavailable):
            return bench_results.failed(call, started, "unavailable", "the house or the bench cannot be reached "
                                        "right now; nothing changed", bench=self._bench)

    async def _house(self) -> House:
        return await house_of(self._owner.household_id)

    async def _list(self, call: ToolCall, started: float) -> ToolResult:
        listed = await (await self._house()).configs("automation")
        zone = await zone_of(self._owner.household_id)
        return bench_results.ok(call, started, {"automations": [_listed(a, zone) for a in listed]}, bench=self._bench,
                                count=len(listed))

    async def _read(self, call: ToolCall, started: float) -> ToolResult:
        automation_id = call.arguments.get("automation_id")
        if not isinstance(automation_id, str) or not automation_id:
            raise BadArguments("automation_id is a non-empty string")
        config = await (await self._house()).config("automation", automation_id)
        if config is None:
            return bench_results.failed(call, started, "no_such_automation", NO_SUCH, bench=self._bench)
        alias = config.get("alias")
        body: dict[str, object] = {"automation_id": automation_id, "alias": alias if isinstance(alias, str) else None,
                "kind": "automation", "body": automation_config.body_of(config)}
        return bench_results.ok(call, started, body, bench=self._bench)

    async def _propose(self, call: ToolCall, started: float) -> ToolResult:
        piece = piece_id_of(call.arguments)
        version, enabled, turn_off = (call.arguments.get(k) for k in ("base_version", "enabled", "turn_off"))
        if type(version) is not int or not isinstance(enabled, bool):
            raise BadArguments("base_version is a whole number and enabled true or false")
        if turn_off is not None and not isinstance(turn_off, str):
            raise BadArguments("turn_off is an entity id")
        if turn_off is not None and turn_off not in {a.thing for a in await (await self._house()).configs("automation")}:
            return bench_results.failed(call, started, "no_such_automation", NO_ENTITY, bench=self._bench, piece=piece)
        applied = await services.get(Workshop).apply(self._owner, self._bench,
                                                     Propose(HER, piece, version, enabled, turn_off))
        if applied.outcome != "accepted":
            return bench_results.failed(call, started, applied.outcome, bench_results.HINTS[applied.outcome],
                                        bench=self._bench, command="propose", seq=applied.seq, piece=piece)
        body: dict[str, object] = {"seq": applied.seq, "piece_id": piece, "version": version,
                                   "waiting_on": "the person's approval"}
        return bench_results.ok(call, started, body, bench=self._bench, command="propose", seq=applied.seq, piece=piece)

    async def _state(self, call: ToolCall, started: float) -> ToolResult:
        piece = piece_id_of(call.arguments)
        view = await services.get(Workshop).read(self._owner, self._bench)
        proposal = view.proposals.get(piece)
        last = (await services.get(Installs).latest_on_bench(self._owner.household_id, self._bench)).get(piece)
        body: dict[str, object] = {
            "piece_id": piece,
            "waiting_on_approval": None if proposal is None else {
                "seq": proposal.seq, "version": proposal.proposed.version, "enabled": proposal.proposed.enabled,
                "turn_off": proposal.proposed.turn_off},
            "last": None if last is None else _record(last)}
        return bench_results.ok(call, started, body, bench=self._bench, piece=piece)


def _listed(a: ConfigItem, zone: tzinfo | None) -> Mapping[str, object]:
    row: dict[str, object] = {"automation_id": a.id, "entity_id": a.thing, "name": a.name, "enabled": a.enabled}
    if zone is not None:
        row["last_triggered"] = None if a.last_ran is None else stamp(a.last_ran, zone)
    return row


def _record(record: InstallRecord) -> Mapping[str, object]:
    began = record.started
    return {"seq": began.seq, "action": began.action, "automation_id": began.automation_id, "enabled": began.enabled,
            "turn_off": began.turn_off, "ending": record.ending,
            "note": record.note if record.ending is not None else "no ending recorded: it is still being carried out, "
            "or its runner stopped part way and the house may be partly changed"}
