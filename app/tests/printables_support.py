"""Helpers for the Printables suites: answers invented in the shape of Printables' public GraphQL API (`printables_captured/`,
shaped as the adapter's own query text asks for them) and three small invented design files,
served by an in-process transport that records each request."""

import json
from pathlib import Path
from typing import Any

import httpx2

from ashley.printables import config as printables_config
from ashley.printables import graphql
from ashley.printables.graphql import GraphqlPrintables
from ashley.tools import printables_fetch
from page_support import Resolver
from search_support import Fake

CAPTURES = Path(__file__).parent / "printables_captured"
CONFIG = printables_config.load()
STL_FILE, THREE_MF_FILE, STEP_FILE = "200101", "200201", "200301"
DOWNLOADS = {STL_FILE: "keychain.stl", THREE_MF_FILE: "peg.3mf", STEP_FILE: "washer.stp"}


def captured(name: str) -> Any:
    return json.loads((CAPTURES / f"{name}.json").read_text())


def file_bytes(name: str) -> bytes:
    return (CAPTURES / "files" / name).read_bytes()


def link_of(file_id: str) -> str:
    """The address Printables handed out for file `file_id`, as recorded."""
    return str(captured(f"link-{file_id}")["data"]["getDownloadLink"]["output"]["link"])


def api(answers: dict[str, Any], served: dict[str, httpx2.Response] | None = None) -> Fake:
    """Answers the API by what the request asks: a search with `search`, a detail with `detail-<id>`, a link with
    `link-<file id>`. Any other address is looked up in `served`, else a 404; each recorded design file is served at
    the address its link recorded."""
    files = {link_of(file): httpx2.Response(200, content=file_bytes(name), headers={"content-type": "application/sla"})
             for file, name in DOWNLOADS.items()}
    files.update(served or {})

    def answer(request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        if url != CONFIG.api_url:
            return files.get(url, httpx2.Response(404))
        sent = json.loads(request.content)
        variables = sent["variables"]
        if sent["query"] == graphql.SEARCH:
            return httpx2.Response(200, json=answers["search"])
        if sent["query"] == graphql.DETAIL:
            return httpx2.Response(200, json=answers[f"detail-{variables['id']}"])
        return httpx2.Response(200, json=answers[f"link-{variables['file']}"])
    return Fake(answer)


def recorded() -> dict[str, Any]:
    """Every recorded API answer, by file name without `.json`."""
    return {p.stem: json.loads(p.read_text()) for p in CAPTURES.glob("*.json")}


def adapter(fake: Fake, resolver: Resolver | None = None) -> GraphqlPrintables:
    """The real adapter and the real fetcher over `fake`'s transport."""
    client = fake.client({"User-Agent": "ashley-test"})
    return GraphqlPrintables(client, CONFIG, printables_fetch.fetcher(client, CONFIG, resolver or Resolver()))
