"""The printing tools as the model sees them, and their arguments checked. All only read (`ToolSpec.reads`).
`printing_ams` is the one household-only result: it carries the printers' names, filament types, colours, remaining
amounts and the spool ids, and no text a person outside the household writes. A print's name, a library file's name and a
file's filament types come from models made elsewhere (a MakerWorld download names itself), so the tools that return
them are `outside`."""

import re
from dataclasses import dataclass

from ..inference.model import ToolSpec
from .printing_config import PrintingConfig

PRINTERS = "printing_printers"
AMS = "printing_ams"
FILES = "printing_files"
NEEDS = "printing_needs"
NAMES = (PRINTERS, AMS, FILES, NEEDS)

_ID = re.compile(r"^[0-9]{1,12}$")
_NO_ARGS: dict[str, object] = {"type": "object", "properties": {}}

INSTRUCTIONS = ("The printing tools read the household's 3D printing in Bambuddy: each printer's state, the print it is "
                "on with its progress and time left, any problems it reports, each AMS slot's filament, colour and "
                "amount left with the unit's humidity, the print library and the filaments a library file needs. "
                "Colours are hex. Slots count from 1. A slot's spool_id is the spool the household recorded in it, as "
                "stock_spools gives it. Humidity is the AMS's own reading; say it as given. You can suggest which spool "
                "to swap into which slot for a file's needs, but you cannot change a slot or start a print: a person "
                "does that at the printer.")


def specs(config: PrintingConfig) -> tuple[ToolSpec, ...]:
    files = {"type": "object", "properties": {
        "search": {"type": "string", "description": "words in the model's name"},
        "limit": {"type": "integer", "minimum": 1, "maximum": config.files_max,
                  "description": f"how many, newest first; {config.files_default} unless given"}}}
    needs = {"type": "object", "properties": {
        "file_id": {"type": "string", "description": "the library file, by the id printing_files gives"}},
             "required": ["file_id"]}
    return (
        ToolSpec(PRINTERS, "The household's printers: state, the print each is on with progress, time left in minutes "
                 "and layers, and any problems reported.", _NO_ARGS, reads=True, outside=True),
        ToolSpec(AMS, "The AMS units of each of the household's printers: per slot the filament, colour, percent left "
                 "and the stock spool recorded in it, and each unit's humidity.", _NO_ARGS, reads=True, outside=False),
        ToolSpec(FILES, "The print library's files, newest first, with name, type, print time, filament used and the "
                 "printer it was sliced for; how many matched, and whether the list was cut.", files, reads=True,
                 outside=True),
        ToolSpec(NEEDS, "The filaments a library file needs: per filament its slot, type, colour and grams.", needs,
                 reads=True, outside=True),
    )


@dataclass(frozen=True)
class FilesQuery:
    search: str | None
    limit: int


def files_query(arguments: dict[str, object], config: PrintingConfig) -> FilesQuery | str:
    """`printing_files`'s arguments checked, or the reason they are wrong, which names no value."""
    search, limit = arguments.get("search"), arguments.get("limit")
    if search is not None:
        if not isinstance(search, str) or not search.strip() or len(search) > config.search_chars:
            return f"search is some words, at most {config.search_chars} characters"
        search = search.strip()
    if limit is None:
        limit = config.files_default
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= config.files_max:
        return f"limit is a whole number from 1 to {config.files_max}"
    return FilesQuery(search, limit)


def file_id(arguments: dict[str, object]) -> str | None:
    """`printing_needs`'s file id, None when it is not an id as `printing_files` gives."""
    given = arguments.get("file_id")
    return given if isinstance(given, str) and _ID.match(given) else None
