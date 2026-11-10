"""Her eyes on a bench, for one turn of its talk (`channels.turn_tools`): `bench_look` gives her a piece or the whole
bench as an image in the result. An image piece is always given from its own bytes, oriented, optionally cropped to a
`region` and scaled to fit (`ashley.looks.pictures`), never drawn; anything else (a document, code, a design, the whole
bench) is a screenshot of the bench's page, a model's from one `view` of it, taken by a headless browser
(`ashley.looks.looker.Looker`). The picture is kept in the object store under the looks' own prefix (`ashley.looks.keys`; a copy, for an image piece) and recorded against the person turn that asked
(`ashley.looks.looks.Looks`), so the page shows what she saw, and a turn takes at most `max_looks_per_turn` of them.
It changes nothing, so its spec is a read."""

import asyncio
import time
import uuid
from dataclasses import replace

from .. import services
from ..files.intake import key_of as file_key
from ..files.store import NullStore, ObjectStore, StoreUnavailable
from ..inference.model import Image, ToolCall, ToolResult, ToolSpec
from ..looks import config as looks_config
from ..looks import pictures
from ..looks.looker import Looker, LookUnavailable, Target
from ..looks.looks import LooksUnavailable
from ..looks.pictures import CannotPrepare, Region
from ..looks.views import VIEWS
from ..workshop import rules as workshop_rules
from ..workshop import stored_file
from ..workshop.model import Owner, Piece
from ..workshop.workshop import BenchNotFound, Workshop, WorkshopUnavailable
from . import bench_picture, bench_results
from .bench_args import BadArguments, check_names, piece_id_of
from .bench_look_args import region_of, view_of
from .tools import Catalogue, Tools

CONFIG = looks_config.load()
RULES = workshop_rules.load()
LOOK = "bench_look"
SPEC = ToolSpec(LOOK, "Look at this bench the way the person sees it: one piece (give piece_id), or the whole bench as "
                "laid out (give none). The picture comes back to you in this result, and it is kept with this message so "
                "the person can see what you saw. An image piece is the picture itself, from its own pixels. region zooms "
                "into part of the picture, as fractions of its width and height from the top left, taken from the original "
                "pixels: use it to see a detail a photo holds instead of asking the person to measure or describe it. view "
                f"frames a model piece from one side ({', '.join(VIEWS)}); pick the side the detail is on.",
                {"type": "object", "properties": {
                    "piece_id": {"type": "integer"},
                    "region": {"type": "object", "properties": {k: {"type": "number"} for k in ("x", "y", "w", "h")}},
                    "view": {"type": "string"}}}, reads=True, outside=True)
INSTRUCTIONS = ("bench_look shows you a piece or the whole bench as an image; use it for what you cannot read as text "
                "(an image the person uploaded, how a document or the pieces are laid out, a design), and read text "
                "with bench_read_piece instead. A message takes only a few looks, so look once at what matters.")
NO_BROWSER = " Only an image piece can be looked at here: nothing is wired to draw the rest of a bench."


class Cannot(Exception):
    """A look that cannot be taken, for `outcome`; `reason` is what she is told."""

    def __init__(self, outcome: str, reason: str) -> None:
        super().__init__(outcome)
        self.outcome = outcome
        self.reason = reason


def instructions(renders: bool) -> str:
    return INSTRUCTIONS + ("" if renders else NO_BROWSER)


class BenchLookTools(Tools):
    def __init__(self, household_id: int, person_id: int, bench_id: int, conversation_id: int, turn_id: int) -> None:
        self._owner = Owner(household_id, person_id)
        self._bench = bench_id
        self._said = (conversation_id, turn_id)

    async def catalogue(self) -> Catalogue:
        """Empty when no object store is wired: a picture is kept before she is given it."""
        if isinstance(services.get(ObjectStore), NullStore):
            return Catalogue((), None)
        return Catalogue((SPEC,), instructions(services.get(Looker).renders()))

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises for what the bench, the browser or the model did: each is an error result, logged `tools.call`
        with the bench and piece; a look logs its bytes and whether it was the piece's own bytes (`how`)."""
        started = time.monotonic()
        if call.name != LOOK:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        try:
            check_names(call.arguments, SPEC)
            piece_id = piece_id_of(call.arguments) if "piece_id" in call.arguments else None
            region = region_of(call.arguments, CONFIG.min_region)
            view = view_of(call.arguments)
            return await self._look(call, started, piece_id, region, view)
        except BadArguments as e:
            return bench_results.failed(call, started, "bad_arguments", str(e), bench=self._bench)
        except Cannot as e:
            return bench_results.failed(call, started, e.outcome, e.reason, bench=self._bench)
        except BenchNotFound:
            return bench_results.failed(call, started, "not_found", "this bench is gone", bench=self._bench)
        except LookUnavailable as e:
            return bench_results.failed(call, started, "unavailable", f"the bench could not be drawn ({e})",
                                        bench=self._bench)
        except (WorkshopUnavailable, StoreUnavailable, LooksUnavailable):
            return bench_results.failed(call, started, "unavailable", "the bench or its storage cannot be reached "
                                        "right now; nothing was looked at", bench=self._bench)

    async def _look(self, call: ToolCall, started: float, piece_id: int | None, region: Region | None,
                    view: str | None) -> ToolResult:
        shown = await services.get(Workshop).read(self._owner, self._bench)
        piece = None if piece_id is None else next((p for p in shown.pieces if p.id == piece_id), None)
        if piece_id is not None and piece is None:
            return bench_results.failed(call, started, "no_such_piece", "no piece with that id is on the bench's "
                                        "layout; bench_read lists them", bench=self._bench, piece=piece_id)
        over = await bench_picture.over_limit(self._owner.household_id, self._said[1], call.id,
                                           CONFIG.max_looks_per_turn)
        if over is not None:
            return bench_results.failed(call, started, "limit", over, bench=self._bench, piece=piece_id)
        if view is not None and (piece is None or piece.kind != "model"):
            raise BadArguments("view is for a model piece")
        own = await self._own_bytes(piece)
        how = "piece" if own is not None else "screenshot"
        picture, px = await (self._drawn(piece_id, view, region) if own is None else self._prepared(own, region))
        await bench_picture.keep(self._owner.household_id, self._said, call.id, self._bench, piece_id, picture)
        body: dict[str, object] = {"of": "the whole bench" if piece_id is None else f"piece {piece_id}", "how": how,
                "media_type": picture.media_type, "picture": "follows in this result"}
        looked = list(shown.pieces) if piece is None else [piece]
        written_outside = any(p.outside for p in looked)
        done = bench_results.ok(call, started, body, outside=written_outside or RULES.shows_outside([p.kind for p in looked]), bench=self._bench,
                                piece=piece_id, how=how, region=int(region is not None), view=view or "-",
                                bytes=len(picture.data), px=px or "-")
        return replace(done, images=(picture,))

    async def _own_bytes(self, piece: Piece | None) -> bytes | None:
        """The stored bytes of an image (a piece of a stored-file kind whose file is of an image type); None for any other
        piece or the whole bench."""
        kind = None if piece is None else RULES.kinds.get(piece.kind)
        if piece is None or kind is None or kind.family != "large":
            return None
        file = stored_file.file_of(piece.text.body)
        if file is None or not file.media_type.startswith("image/"):
            return None
        data = await services.get(ObjectStore).get(file_key(self._owner.household_id, file.sha256))
        if data is None:
            raise Cannot("gone", "that image's bytes are no longer in the store")
        return data

    async def _prepared(self, data: bytes, region: Region | None) -> tuple[Image, int]:
        try:
            made = await asyncio.to_thread(pictures.prepare, data, region, CONFIG)
        except CannotPrepare as e:
            raise Cannot(e.outcome, e.reason) from e
        return Image("image/jpeg", made.data), made.px

    async def _drawn(self, piece_id: int | None, view: str | None, region: Region | None) -> tuple[Image, int]:
        looker = services.get(Looker)
        if not looker.renders():
            raise Cannot("no_browser", "only an image piece can be looked at here; read the rest with bench_read_piece")
        target = Target(self._owner.household_id, self._owner.person_id, self._bench, piece_id, view)
        shot = await looker.look(f"look-{uuid.uuid4().hex[:12]}", target)
        if len(shot.data) > CONFIG.max_image_bytes:
            raise Cannot("too_large", "the picture of that came out larger than a picture may be here; look at one piece "
                         "of the bench instead, or say what you can without looking")
        if region is None:
            return Image("image/jpeg", shot.data), pictures.longest_side(shot.data) or 0
        return await self._prepared(shot.data, region)
