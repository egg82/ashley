"""SearXNG as a connection kind of the `search` port, and the web search that reads its address on each use. The address
is on the operator's own network and takes no key, so the secret a connection stores is placeholder text
(`ashley.connections.address_seed.NO_SECRET`); it is a `deployment` kind held by the first household."""

import time

import httpx2

from ..connections.address_in_force import AddressInForce
from ..connections.kinds import ConnectionKind, Refusal
from ..inference.key_check import answered
from ..inference.model import ToolCall, ToolResult
from . import searching
from .search_config import SearchConfig
from .tools import Catalogue
from .web_search import WebSearch, WebSearchTools

NAME = "searxng"


async def check(base: str, secret: str, person_id: int) -> Refusal | None:
    """One search asking for JSON, the way she searches: None when SearXNG answers with a JSON object; `key_refused`
    when it refuses JSON (its `search.formats` lacks `json`); `unreachable` for no answer in time or an error."""
    async with httpx2.AsyncClient() as http:
        return await answered(http, base + "/search?q=ping&format=json", {})


KIND = ConnectionKind(
    name=NAME, title="SearXNG", what="web search",
    blurb="A SearXNG instance on your own network, which she searches the web through. It must serve JSON "
          "(`json` among `search.formats` in its settings).",
    connected="Connected. She searches the web through it from now on.",
    removed="Removed. She does not search the web until one is connected.",
    holders=frozenset({"household"}), schemes=frozenset({"https", "http"}),
    address_placeholder="http://searxng:8080", secret_field="api_key",
    secret_label="Key (any text; SearXNG takes none)", secret_noun="key", check=check,
    ports=frozenset({"search"}), deployment=True,
    refusals={"bad_url": "that is not an address SearXNG is reached at (https, or http on your own network)",
              "key_refused": "that SearXNG does not serve JSON; add `json` to `search.formats` in its settings",
              "unreachable": "nothing answered at that address in time",
              "wrong_service": "what answered there is not SearXNG's JSON"})


class ConnectedWebSearch(WebSearch):
    """`WebSearchTools` over the address in force now. With none, the search is not offered, as with no address set."""

    def __init__(self, http: httpx2.AsyncClient, config: SearchConfig, address: AddressInForce) -> None:
        self._http = http
        self._config = config
        self._address = address

    async def catalogue(self) -> Catalogue:
        found = await self._address()
        return await WebSearchTools(self._http, self._config, found).catalogue() if found else Catalogue((), None)

    async def numbered(self, call: ToolCall, first: int) -> tuple[ToolResult, list[str]]:
        found = await self._address()
        if not found:
            return searching.failed(call, "unavailable", time.monotonic(), "web search is not set up"), []
        return await WebSearchTools(self._http, self._config, found).numbered(call, first)
