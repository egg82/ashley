"""Where a site or video piece's URL comes from. She never types a URL she composed: she names a search result by its
number (`result`, and for a video `start`), and the server writes the result's URL from the turn's `results.Results`
into the body; or she gives a URL that the person wrote in the conversation or that a site or video piece on the bench
already holds, compared by exact string. Any other URL is refused `unlisted_url`, and an unknown number
`unknown_result`. The kind checks (`workshop.embed`) then run on the body as for any piece. Other kinds are not
checked: a document may hold links she writes in its text.

A reader piece holds the text of a page she read this turn: she names it by `result` as for a site, and the server writes
the body from the page `read_page` returned for that number (`results.Results.page`), never from anything she typed. A
result whose page was not read is refused `unread_page`. A recipe piece is the same, from the recipe the page publishes
(`bench_recipe_ref`).

A code or document piece may likewise be put up from a page she read, by `result` in place of a body: the body is the
page's text as read, with newline line ends, under one line naming its address, and a page longer than the kind allows, or cut short by the
byte limit on reading it, is refused `page_too_long` or `page_cut` rather than stored cut."""

import json
from collections.abc import Awaitable, Callable, Iterable, Mapping

from .. import services
from ..workshop import embed, reader
from ..workshop.model import Owner, Piece
from ..workshop.rules import Kind, Rules
from ..workshop.workshop import Workshop
from . import bench_recipe_ref
from .bench_args import BadArguments, piece_id_of, result_of, start_of
from .results import ReadPage, Results

NO_RESULT = ("no search result with that number this turn: look it up again, and name a result by the number "
             "look_up's references give")
UNREAD = ("a reader piece holds the text of a page that was read this turn, and that result's page was not: ask look_up "
          "for the page and to read it, in one question, and use the result number it gives")
TOO_LONG = "the page's text is longer than that kind of piece holds, so none of it was added; add less than the page, or say so"
CUT = "the page was longer than can be read, so its text ends early and none of it was added; say so"
UNLISTED = ("a site or video URL must come from the person or from this bench, never from memory: put a search result "
            "up by its number (the `result` argument; look_up's references name results by number), and when no "
            "result is the page or video itself, put nothing up and say so")
_CLOSING = ".,;:!?)]}>\"'"

Said = Callable[[], Awaitable[frozenset[str]]]
"""Reads the URLs the people of this conversation wrote in it (`channels.said_links.by_people`)."""


class SaidUnavailable(Exception):
    """The conversation could not be read."""


class Refused(Exception):
    """A reference the bench tool refuses before it reaches the Workshop: `outcome` is its reason code, `reason` what
    she is told. Neither holds a URL."""

    def __init__(self, outcome: str, reason: str) -> None:
        super().__init__(outcome)
        self.outcome = outcome
        self.reason = reason


def links_in(text: str) -> frozenset[str]:
    """The URLs written in `text`: from each `http://` or `https://` to the next whitespace, and the same with closing
    punctuation taken off one character at a time, since `text` is prose or JSON around the URL."""
    found: set[str] = set()
    for word in text.split():
        starts = [i for i in (word.find("http://"), word.find("https://")) if i >= 0]
        link = word[min(starts):] if starts else ""
        while link:
            found.add(link)
            link = link[:-1] if link[-1] in _CLOSING else ""
    return frozenset(found)


def body_of(fmt: str, url: str, start: int | None) -> str:
    """The body of a `site` or `video` piece that shows `url`."""
    if fmt == "site":
        return url
    return json.dumps({"url": url} if start is None else {"url": url, "start": start})


def _url_in(fmt: str, body: object) -> str | None:
    """The URL a body of that fmt holds, when it holds one the Workshop would read; else None."""
    if not isinstance(body, str):
        return None
    if fmt == "video":
        video = embed.video_of(body)
        return None if video is None else video.url
    return body.strip() if embed.https_host(body.strip()) is not None else None


def _text_of(read: ReadPage) -> str:
    """The page text without a first line that is only its title, which the piece holds as a field."""
    first, _, rest = read.text.partition("\n")
    return rest if read.title and first.strip() == read.title else read.text


class References:
    def __init__(self, owner: Owner, bench_id: int, rules: Rules, results: Results, said: Said | None) -> None:
        self._owner = owner
        self._bench = bench_id
        self._rules = rules
        self._results = results
        self._said = said

    async def resolve(self, name: str, args: Mapping[str, object]) -> Mapping[str, object]:
        """`args` of bench tool `name`, with a `result` replaced by the body it names. Raises BadArguments, Refused."""
        if name not in ("bench_add", "bench_edit"):
            return args
        pieces = await self._pieces() if name == "bench_edit" else ()
        kind = self._kind_of(name, args, pieces)
        fmt = None if kind is None else kind.format
        if fmt == "reader":
            return self._page(args)
        if fmt == "recipe":
            try:
                return bench_recipe_ref.resolved(name, args, self._results, pieces)
            except bench_recipe_ref.NoRecipe as e:
                raise Refused(e.outcome, e.reason) from e
        if "serves" in args:
            raise BadArguments("serves is for a recipe piece")
        if fmt in ("code", "markdown") and "result" in args and kind is not None:
            return self._text_page(kind, args)
        if fmt not in ("site", "video"):
            if "result" in args or "start" in args:
                raise BadArguments("result and start are for site, video, reader, recipe, code and document pieces")
            return args
        if "result" in args:
            return self._filled(fmt, args)
        if "start" in args:
            raise BadArguments("start goes with result")
        url = _url_in(fmt, args.get("body"))
        if url is not None and url not in await self._vouched(pieces):
            raise Refused("unlisted_url", UNLISTED)
        return args

    def shows_page(self, kind: str) -> bool:
        """Whether pieces of `kind` come from a result she names, not text she writes: a site, video, reader or recipe."""
        found = self._rules.kinds.get(kind)
        return found is not None and found.format in ("site", "video", "reader", "recipe")

    def _kind_of(self, name: str, args: Mapping[str, object], pieces: Iterable[Piece]) -> Kind | None:
        kind = args.get("kind") if name == "bench_add" else next(
            (p.kind for p in pieces if p.id == piece_id_of(args)), None)
        return self._rules.kinds.get(kind) if isinstance(kind, str) else None

    def _text_page(self, kind: Kind, args: Mapping[str, object]) -> Mapping[str, object]:
        """`args` of a code or document piece, its `result` replaced by the text of the page read for it."""
        body = args.get("body")
        if "start" in args or (isinstance(body, str) and body.strip()):
            raise BadArguments("a page's text is put up by result alone, the number of a page that was read")
        number = result_of(args)
        url = self._results.url(number)
        if url is None:
            raise Refused("unknown_result", NO_RESULT)
        read = self._results.page(number)
        if read is None:
            raise Refused("unread_page", UNREAD)
        if read.cut:
            raise Refused("page_cut", CUT)
        text = _text_of(read).replace("\r\n", "\n")
        source = f"Source: {url}\n" + ("\n" if kind.format == "markdown" else "")
        if len(source) + len(text) > kind.max_chars:
            raise Refused("page_too_long", TOO_LONG)
        kept = {k: v for k, v in args.items() if k != "result"}
        return {**kept, "body": source + text}

    def _page(self, args: Mapping[str, object]) -> Mapping[str, object]:
        """`args` of a reader piece, its `result` replaced by the body of the page read for it."""
        if "start" in args:
            raise BadArguments("start is for a video")
        body = args.get("body")
        if "result" not in args or (isinstance(body, str) and body.strip()):
            raise BadArguments("a reader piece is put up by result alone, the number of a page that was read")
        number = result_of(args)
        url = self._results.url(number)
        if url is None:
            raise Refused("unknown_result", NO_RESULT)
        read = self._results.page(number)
        if read is None:
            raise Refused("unread_page", UNREAD)
        kept = {k: v for k, v in args.items() if k != "result"}
        return {**kept, "body": self._fitted(url, read.title, _text_of(read))}

    def _fitted(self, url: str, title: str, text: str) -> str:
        """The reader body for `text`, cut at the end to the kind's `max_chars` when the page is longer: half the excess
        at a time, since an escaped newline takes two characters of body, so the cut never overshoots."""
        limit = next((k.max_chars for k in self._rules.kinds.values() if k.format == "reader"), None)
        body = reader.body_of(url, title, text)
        while limit is not None and len(body) > limit and text:
            text = text[:max(0, len(text) - (len(body) - limit + 1) // 2)]
            body = reader.body_of(url, title, text)
        return body

    def _filled(self, fmt: str, args: Mapping[str, object]) -> Mapping[str, object]:
        body = args.get("body")
        if isinstance(body, str) and body.strip():
            raise BadArguments("give a result or a body, not both")
        number = result_of(args)
        url = self._results.url(number)
        if url is None:
            raise Refused("unknown_result", NO_RESULT)
        if fmt == "site" and "start" in args:
            raise BadArguments("start is for a video")
        kept = {k: v for k, v in args.items() if k not in ("result", "start")}
        return {**kept, "body": body_of(fmt, url, start_of(args))}

    async def _pieces(self) -> tuple[Piece, ...]:
        view = await services.get(Workshop).read(self._owner, self._bench)
        return (*view.pieces, *view.shelf)

    async def _vouched(self, known: tuple[Piece, ...]) -> frozenset[str]:
        """The URLs she may give: those the person wrote in the conversation, and those in the bench's site and video
        pieces."""
        pieces = known or await self._pieces()
        found: set[str] = set()
        for piece in pieces:
            kind = self._rules.kinds.get(piece.kind)
            if kind is not None and kind.format in ("site", "video"):
                found |= links_in(piece.text.body)
        return frozenset(found | await self._person_links())

    async def _person_links(self) -> frozenset[str]:
        if self._said is None:
            return frozenset()
        try:
            return await self._said()
        except SaidUnavailable as e:
            raise Refused("unavailable", "the conversation cannot be read right now, so a URL cannot be checked") from e
