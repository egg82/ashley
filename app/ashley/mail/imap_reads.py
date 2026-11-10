"""The reads of the IMAP adapter over one `Imap` session: the folders and labels, a search, one message. Folder names,
ids and the ordering of a search are decided here and nowhere else; the wire is `imap_wire`, a message's records are
`imap_message`.

A search lists the newest `SCAN_MAX` uids of each folder it covers, orders them by when Bridge received them, and reads
the page from the full messages (as Gmail's does, since attachments are only known from the parts). Its cursor is how many
hits came before, so a page asked for after new mail arrived can repeat or skip one message."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import imap_message
from .config import MailConfig
from .imap_find import LABELS, SCAN_MAX, SEARCHED, SYSTEM, Found, labelled, locate
from .imap_terms import Criteria, criteria, day
from .imap_wire import Fetched, Imap
from .model import Header, Label, MailFailed, MailQuery, Message, Page


@dataclass(frozen=True)
class _Hit:
    received: datetime
    folder: str
    imap: str
    uid: int


def labels(session: Imap, config: MailConfig) -> tuple[Label, ...]:
    names = session.folders()
    folders = [Label(n, True) for n, imap in SYSTEM.items() if imap in names]
    users = [Label(n[len(LABELS):], False) for n in names if n.startswith(LABELS) and len(n) > len(LABELS)]
    return (*folders, *users)[:config.labels_max]


def search(session: Imap, query: MailQuery, config: MailConfig) -> Page[Header]:
    offset = _offset(query.page)
    names = session.folders()
    needed = _needed_labels(query)
    wanted = criteria(query)
    hits, truncated = _ranked(session, _sources(query, names, needed), wanted, offset)
    window = hits[offset:offset + SCAN_MAX]
    items: list[Header] = []
    used = 0
    for start in range(0, len(window), config.search_max):
        chunk = window[start:start + config.search_max]
        for built in _build(session, names, chunk, query, needed, config):
            used += 1
            if built is not None and _kept(built, query, needed):
                items.append(built)
            if len(items) == config.search_max:
                break
        if len(items) == config.search_max:
            break
    more = offset + used < len(hits) or truncated
    return Page(tuple(items), more, str(offset + used) if more else "")


def read(session: Imap, message_id: str, config: MailConfig) -> Message:
    names = session.folders()
    found = located(session, names, message_id, config)
    got = session.fetch(found.imap, [found.uid], _full(config))
    if not got:
        raise MailFailed("not_found")
    raw = imap_message.parse(got[0].body)
    text, files = imap_message.text_and_attachments(raw)
    members = _members(session, names, [found.received], config)
    head = imap_message.header(raw, config.message_id_chars, config.snippet_chars, text, len(files),
                               members.get(imap_message.ident(raw, config.message_id_chars), ()), found.folder,
                               "\\seen" not in got[0].flags, found.received)
    return imap_message.full(raw, head, config.body_chars)


def located(session: Imap, names: tuple[str, ...], message_id: str, config: MailConfig) -> Found:
    """The message `message_id` names. Raises MailFailed `not_found` for an id that names none (or cannot be one)."""
    if not imap_message.valid(message_id, config.message_id_chars):
        raise MailFailed("not_found")
    found = locate(session, names, message_id, config.message_id_chars)
    if found is None:
        raise MailFailed("not_found")
    return found


def _full(config: MailConfig) -> str:
    return f"BODY.PEEK[]<0.{config.message_bytes}>"


def _offset(page: str) -> int:
    if not page:
        return 0
    if not page.isascii() or not page.isdigit() or len(page) > 9:
        raise MailFailed("refused")
    return int(page)


def _needed_labels(query: MailQuery) -> list[str]:
    """The labels a hit must carry: `label`, and `folder` when it is not one of the folders."""
    folder = query.folder.strip()
    return [n.strip() for n in (query.label, "" if folder.lower() in SYSTEM else folder) if n.strip()]


def _sources(query: MailQuery, names: tuple[str, ...], needed: Sequence[str]) -> list[tuple[str, str]]:
    """(the port's folder, Bridge's) to search: the label folder of the first needed label (the folder is then found per
    message), else the folder asked for, else `SEARCHED`; those Bridge does not have are left out."""
    if needed:
        found = labelled(names).get(needed[0].lower())
        return [("", found)] if found else []
    asked = query.folder.strip().lower()
    wanted = (asked,) if asked in SYSTEM else SEARCHED
    return [(f, SYSTEM[f]) for f in wanted if SYSTEM[f] in names]


def _ranked(session: Imap, sources: Sequence[tuple[str, str]], wanted: Criteria, offset: int) -> tuple[list[_Hit], bool]:
    hits: list[_Hit] = []
    truncated = False
    for folder, imap in sources:
        uids = session.search(imap, wanted)
        keep = uids[-(offset + SCAN_MAX):]
        truncated = truncated or len(keep) < len(uids)
        got = session.received(imap, keep)
        hits += [_Hit(got[u], folder, imap, u) for u in keep if u in got]
    return sorted(hits, key=lambda h: h.received, reverse=True), truncated


def _build(session: Imap, names: tuple[str, ...], chunk: Sequence[_Hit], query: MailQuery, needed: Sequence[str],
           config: MailConfig) -> list[Header | None]:
    fetched: dict[tuple[str, int], Fetched] = {}
    for imap in dict.fromkeys(h.imap for h in chunk):
        for item in session.fetch(imap, [h.uid for h in chunk if h.imap == imap], _full(config)):
            fetched[imap, item.uid] = item
    members = _members(session, names, [h.received for h in chunk], config)
    built: list[Header | None] = []
    for hit in chunk:
        item = fetched.get((hit.imap, hit.uid))
        if item is None:
            built.append(None)
            continue
        raw = imap_message.parse(item.body)
        ident = imap_message.ident(raw, config.message_id_chars)
        folder = hit.folder or _folder_of(session, names, ident, config)
        text, files = imap_message.text_and_attachments(raw)
        built.append(imap_message.header(raw, config.message_id_chars, config.snippet_chars, text, len(files),
                                         members.get(ident, ()), folder, "\\seen" not in item.flags, hit.received))
    return built


def _folder_of(session: Imap, names: tuple[str, ...], ident: str, config: MailConfig) -> str:
    found = locate(session, names, ident, config.message_id_chars)
    return found.folder if found else ""


def _kept(header: Header, query: MailQuery, needed: Sequence[str]) -> bool:
    have = {l.lower() for l in header.labels}
    if any(n.lower() not in have for n in needed):
        return False
    asked = query.folder.strip().lower()
    if asked in SYSTEM and header.folder != asked:
        return False
    return query.has_attachment is None or (header.attachments > 0) == query.has_attachment


def _members(session: Imap, names: tuple[str, ...], received: Sequence[datetime | None],
             config: MailConfig) -> dict[str, tuple[str, ...]]:
    """Each message id to the household's labels carrying it, looked for among the messages of each label folder received
    since the oldest of `received` (a day earlier, since a search by day cannot be finer)."""
    known = [r for r in received if r is not None]
    since = Criteria(("SINCE", day((min(known) - timedelta(days=1)).date())) if known else ())
    found: dict[str, list[str]] = {}
    for imap in labelled(names).values():
        uids = session.search(imap, since)
        for item in session.fetch(imap, uids, "BODY.PEEK[HEADER.FIELDS (MESSAGE-ID DATE FROM SUBJECT)]"):
            ident = imap_message.ident(imap_message.parse(item.body), config.message_id_chars)
            found.setdefault(ident, []).append(imap[len(LABELS):])
    return {i: tuple(v) for i, v in found.items()}
