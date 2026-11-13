"""The prompt-sizes eval wired as the app is: her real turn's system prompt and tools (`channels.turn_prompt.build`
over `Landing`, the tools as `tool_loop.answer` offers them) for a household's speaker, counted with the Anthropic key
the app uses (the deployment's provider-key connection, else the env's). Reads only: no turn is stored."""

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import anthropic
from anthropic import AsyncAnthropic, Omit, omit
from anthropic.types import MessageParam, MessageTokensCount, OutputConfigParam, TextBlockParam, ToolParam

from .. import logs, services
from ..channels import aside, speaker, turn_prompt
from ..channels.landing import Landing
from ..channels.limits import load as load_limits
from ..channels.model import Inbound, Kind
from ..connections.connections import Connections
from ..inference import anthropic_wire
from ..inference.model import Route
from ..inference.provider_keys import ConnectionProviderKeys, KeysUnavailable
from ..inference.reply import Reply
from ..inference.routes import Routes
from ..people.people import People
from ..persona import persona
from ..settings import Settings
from ..tools.tools import Catalogue
from .prompt_sizes import Count, Request, Sizes, measure
from .prompt_sizes_report import Meta, render, to_json

log = logging.getLogger("ashley.evals")

KINDS: tuple[Kind, ...] = ("command", "chat")
CHANNELS = ("web", "voice")
PLACE = "kitchen"


def inbound(kind: Kind, channel: str, household_id: int, person_id: int, ask: str) -> Inbound:
    """The ask as the channel shapes it: `web` is the person's own chat, `voice` a shared satellite that heard them."""
    thread = f"prompt-sizes-{uuid.uuid4()}"
    if channel == "voice":
        return Inbound(household_id, thread, ask, kind, "spoken", "present", None, True, PLACE, "voice", heard_as=person_id,
                       later=True, taint=None, overhears=True)
    return Inbound(household_id, thread, ask, kind, "text", "owner", person_id, False, None, "web", later=True,
                   later_by="turn", opens_benches=True, on_page=True, taint=None)


def counted_route(routes: Routes, kind: Kind) -> tuple[Route, str]:
    """The first Anthropic route of `kind` (the only provider `count_tokens` counts for) and, when it is not the
    first route, the first one as `provider/model`. Raises ValueError when `kind` has no Anthropic route."""
    listed = routes.for_task(kind)
    for route in listed:
        if route.provider == "anthropic":
            first = listed[0]
            return route, "" if first is route else f"{first.provider}/{first.model}"
    raise ValueError(f"{kind} has no Anthropic route to count on")


def keeping(into: list[Routes]) -> Callable[[Routes], Routes]:
    """A `wiring.wire` `narrow` that leaves the routes as loaded and keeps them in `into`."""
    def narrow(routes: Routes) -> Routes:
        into.append(routes)
        return routes
    return narrow


async def client(settings: Settings) -> AsyncAnthropic:
    """A client on the key the app calls with. Raises ValueError when it cannot be read or none is set."""
    keys = ConnectionProviderKeys(lambda: services.get(Connections), ("anthropic",),
                                  {"anthropic": settings.anthropic_api_key})
    try:
        found = (await keys.in_force()).get("anthropic")
    except KeysUnavailable as e:
        raise ValueError("the Anthropic key could not be read") from e
    if found is None:
        raise ValueError("no Anthropic key is set, as a connection or in the env")
    return AsyncAnthropic(api_key=found.secret)


class Counts(Protocol):
    """What of the SDK's `messages` resource `counting` calls."""

    async def count_tokens(self, *, model: str, messages: list[MessageParam], system: list[TextBlockParam] | Omit,
                           tools: list[ToolParam] | Omit, output_config: OutputConfigParam | Omit) -> MessageTokensCount:
        ...


def counting(messages: Counts) -> Count:
    """A `Count` over `messages` (`AsyncAnthropic.messages`). Raises ValueError for a refusal or a connection failure,
    naming the status or the exception type."""
    async def count(model: str, request: Request) -> int:
        schema = request.reply_schema
        try:
            got = await messages.count_tokens(
                model=model, messages=request.messages, system=request.system or omit, tools=request.tools or omit,
                output_config=omit if schema is None else OutputConfigParam(
                    format={"type": "json_schema", "schema": dict(schema)}))
        except anthropic.APIStatusError as e:
            raise ValueError(f"count_tokens answered {e.status_code}") from e
        except anthropic.APIConnectionError as e:
            raise ValueError(f"count_tokens could not be reached: {type(e).__name__}") from e
        return got.input_tokens
    return count


@dataclass(frozen=True)
class Options:
    kind: Kind
    channel: str
    household_id: int
    person_id: int | None
    ask: str


async def _person(options: Options) -> int:
    if options.person_id is not None:
        return options.person_id
    household = await services.get(People).household(options.household_id)
    if household is None or not household.people:
        raise ValueError("that household has no one to ask as")
    return min(p.id for p in household.people)


async def run(count: Count, routes: Routes, options: Options, json_path: Path | None) -> str:
    """The table for `options` counted with `count`, the JSON written to `json_path` when given. Raises ValueError for
    what cannot be measured: no Anthropic route, a household with nobody in it, a count refused."""
    started = time.perf_counter()
    route, first = counted_route(routes, options.kind)
    ask = inbound(options.kind, options.channel, options.household_id, await _person(options), options.ask)
    who = await speaker.who(ask)

    prompted = await turn_prompt.build(ask, who, Landing(ask, (0, 0), load_limits()), turn_prompt.nothing_carried())
    variant = route.variant if route.variant in prompted.system else "default"
    catalogue = prompted.catalogue or Catalogue((), None)
    specs, owners = catalogue.specs, catalogue.owners
    offered = aside.offered(specs) if ask.holds and specs else specs
    sizes = await measure(count, route.model, persona.stable_parts(ask.kind, prompted.context)[variant],
                          prompted.system[variant], offered, owners, anthropic_wire.reply_schema(Reply))
    meta = Meta(options.kind, options.channel, route.provider, route.model, first, len(options.ask))
    logs.info(log, "eval.prompt_sizes", kind=options.kind, channel=options.channel, model=route.model, tools=len(offered),
              tokens=sizes.whole, counts=sizes.calls, duration_ms=int((time.perf_counter() - started) * 1000))
    return _written(sizes, meta, json_path)


def _written(sizes: Sizes, meta: Meta, json_path: Path | None) -> str:
    if json_path is not None:
        json_path.write_text(to_json(sizes, meta) + "\n")
    return render(sizes, meta)
