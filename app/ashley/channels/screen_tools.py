"""Her tools on the household's screens, for one turn (`channels.turn_tools`): read a screen, and change it through the
Commands a person's routes build (`workshop.commands`), made by her and applied by `Workshop.apply_screen`, so her
change is decided, logged, undoable and announced on Live as a person's is. With a known speaker, every screen of the
household (a device of form `other`) is in reach; on a turn on a screen's own thread (`Inbound.device_id`), that screen
alone, whoever speaks. A refusal comes back as a tool error naming its reason, and nothing changes."""

import time
from collections.abc import Mapping

from .. import services
from ..connections.connections import ConnectionsUnavailable
from ..connections.kinds import CatalogueUnavailable
from ..inference.model import ToolCall, ToolResult
from ..tools import bench_results, screen_specs
from ..tools.bench_args import BadArguments, check_names
from ..tools.tools import Catalogue, Tools
from ..workshop import rules as workshop_rules
from ..workshop import screen_controls
from ..workshop.commands import Edit, ScreenCommand
from ..workshop.json_shape import list_of
from ..workshop.model import Piece
from ..workshop.rules import Rules
from ..workshop.workshop import Applied, ScreenNotFound, ScreenView, Workshop, WorkshopUnavailable
from . import screen_args
from .devices import Devices, DevicesUnavailable
from .kiosk.controls import ControlRefused
from .kiosk.house_domains import domains

RULES = workshop_rules.load_screen()


class _Failed(Exception):
    """A call that ends as an error result of `outcome`, `reason` saying why in words that name no value."""

    def __init__(self, outcome: str, reason: str) -> None:
        super().__init__(outcome)
        self.outcome, self.reason = outcome, reason


class ScreenTools(Tools):
    def __init__(self, household_id: int, person_id: int | None, device_id: int | None,
                 rules: Rules = RULES) -> None:
        self._household, self._person, self._device = household_id, person_id, device_id
        self._rules = rules

    async def catalogue(self) -> Catalogue:
        """The screen tools when a screen is in reach, else none; none while the devices cannot be read, which a call
        says again."""
        try:
            reach = await self._in_reach()
        except DevicesUnavailable:
            return Catalogue((), None)
        return Catalogue(screen_specs.specs(self._rules), screen_specs.INSTRUCTIONS) if reach else Catalogue((), None)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises for what the screen or the model did: each is an error result, logged `tools.call` with the
        device and piece ids and the outcome, never a label or an entity."""
        started = time.monotonic()
        if call.name not in {s.name for s in screen_specs.specs(self._rules)}:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        fields: dict[str, object] = {}
        try:
            check_names(call.arguments, next(s for s in screen_specs.specs(self._rules) if s.name == call.name))
            return await self._run(call, started, fields)
        except _Failed as e:
            return bench_results.failed(call, started, e.outcome, e.reason, **fields)
        except BadArguments as e:
            return bench_results.failed(call, started, "bad_arguments", str(e), **fields)
        except ValueError:
            return bench_results.failed(call, started, "bad_text", bench_results.BAD_TEXT_HINT, **fields)
        except ScreenNotFound:
            return bench_results.failed(call, started, "no_such_screen", "that screen is gone", **fields)
        except (WorkshopUnavailable, DevicesUnavailable, ConnectionsUnavailable, CatalogueUnavailable):
            return bench_results.failed(call, started, "unavailable", "the screen cannot be reached right now", **fields)

    async def _in_reach(self) -> tuple[int, ...]:
        """The ids of the screens this turn may use. Raises DevicesUnavailable."""
        screens = {d.device.id for d in await services.get(Devices).of_household(self._household) if d.form == "other"}
        if self._device is not None:
            return (self._device,) if self._device in screens else ()
        return tuple(sorted(screens)) if self._person is not None else ()

    async def _run(self, call: ToolCall, started: float, fields: dict[str, object]) -> ToolResult:
        reach = await self._in_reach()
        wanted = screen_args.device_of(call.arguments)
        if wanted is None and call.name == "screen_read" and len(reach) != 1:
            return await self._screens(call, started, reach)
        device = _chosen(wanted, reach)
        fields["device"] = device
        if call.name == "screen_read":
            return await self._read(call, started, device)
        return await self._change(call, started, device, fields)

    async def _screens(self, call: ToolCall, started: float, reach: tuple[int, ...]) -> ToolResult:
        if not reach:
            raise _Failed("no_such_screen", "no screen is in reach")
        names = {d.device.id: d for d in await services.get(Devices).of_household(self._household)}
        listed = [{"device_id": i, "name": names[i].device.name, "place": names[i].device.place} for i in reach]
        return bench_results.ok(call, started, {"screens": listed}, outside=False, screens=len(listed))

    async def _read(self, call: ToolCall, started: float, device: int) -> ToolResult:
        view = await services.get(Workshop).screen(self._household, device)
        body: dict[str, object] = {"device_id": device, "laid_out": view.laid_out, "undo_next": view.undo_next,
                "pieces": [_shown(p, view) for p in view.pieces],
                "kinds_addable": [k for k in self._rules.kinds if not any(p.kind == k for p in view.pieces)],
                "sizes": ["small", "medium", "large", "full"]}
        return bench_results.ok(call, started, body, outside=False, device=device, pieces=len(view.pieces))

    async def _change(self, call: ToolCall, started: float, device: int, fields: dict[str, object]) -> ToolResult:
        applied = await services.get(Workshop).apply_screen(self._household, device, await self._command(call, device))
        fields.update(seq=applied.seq)
        return _result(call, started, applied, fields)

    async def _command(self, call: ToolCall, device: int) -> ScreenCommand:
        args = call.arguments
        if call.name == "screen_buttons":
            return await self._buttons(args, device)
        if call.name == "screen_undo":
            return screen_args.undo_of(await self._undo_next(device))
        if call.name == "screen_add":
            return screen_args.add_of(args, self._rules)
        return screen_args.move_of(args) if call.name == "screen_move" else screen_args.remove_of(args)

    async def _undo_next(self, device: int) -> int:
        undo_next = (await services.get(Workshop).screen(self._household, device)).undo_next
        if undo_next is None:
            raise _Failed("nothing_to_undo", bench_results.HINTS["nothing_to_undo"])
        return undo_next

    async def _buttons(self, args: Mapping[str, object], device: int) -> Edit:
        if self._person is None:
            raise _Failed("needs_speaker", "the buttons name lights of the house, which only a person you know can pick")
        found = await domains(self._household, self._person) if list_of(args.get("buttons")) else {}
        try:
            edit, _ = screen_args.buttons_of(args, found, self._rules)
        except ControlRefused as e:
            raise _Failed(e.reason, _BUTTON_HINTS[e.reason]) from e
        view = await services.get(Workshop).screen(self._household, device)
        piece = next((p for p in view.pieces if p.id == edit.piece_id), None)
        if piece is not None and self._rules.kinds[piece.kind].format != "controls":
            raise BadArguments("piece_id is not a controls piece")
        return edit


_BUTTON_HINTS: dict[str, str] = {
    "too_many": f"a screen holds at most {screen_controls.MAX_CONTROLS} buttons",
    "bad_label": "a label is 1 to 40 characters",
    "bad_id": "an id is 1 to 40 of a-z, 0-9 and -",
    "duplicate_id": "an id is used twice",
    "unknown_entity": "a button's light or scene must be one of the house's, in its action's domain"}


def _chosen(wanted: int | None, reach: tuple[int, ...]) -> int:
    if not reach:
        raise _Failed("no_such_screen", "no screen is in reach")
    if wanted is None:
        if len(reach) == 1:
            return reach[0]
        raise BadArguments("device_id names the screen; screen_read without it lists them")
    if wanted not in reach:
        raise _Failed("no_such_screen", "that is not a screen you can arrange")
    return wanted


def _shown(piece: Piece, view: ScreenView) -> dict[str, object]:
    shown: dict[str, object] = {"id": piece.id, "kind": piece.kind, "order": piece.place.order, "size": piece.place.size,
                                "last_changed_by": view.last_changed_by.get(piece.id, "ashley")}
    if piece.kind == "controls":
        shown |= {"version": piece.version, "buttons": [
            {"id": c.id, "label": c.label, "action": c.action, "entity_id": c.entity_id}
            for c in screen_controls.decode(piece.text.body)]}
    return shown


def _result(call: ToolCall, started: float, applied: Applied, fields: dict[str, object]) -> ToolResult:
    if applied.outcome == "accepted":
        return bench_results.ok(call, started, {"seq": applied.seq, "piece_id": applied.piece_id}, outside=False, **fields)
    return bench_results.failed(call, started, applied.outcome, bench_results.HINTS[applied.outcome], **fields)
