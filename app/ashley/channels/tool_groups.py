"""One line for each group of tools a turn can offer (`turn_tools.for_turn`'s source keys), which is how the loader tool
(`on_demand.LOADER`) tells her what a group is for. Written here, never derived from the tools' descriptions;
`tests/test_tool_groups.py` fails for a key `for_turn` offers that has no line."""

from collections.abc import Mapping

SUMMARY: Mapping[str, str] = {
    "everyday": "the house's lights, devices and lists, search and places, and what she remembers",
    "readers": "send readers to look several things up at once",
    "errand": "set when she looks again at an errand",
    "method": "a standing errand's method",
    "bench": "read and edit the pieces of a bench",
    "tidy": "mark a tidy finding on a bench as fine",
    "automations": "read and write the house's automations on a bench",
    "skills": "the household's skills for a kind of work on a bench",
    "files": "make a file piece on a bench",
    "printables": "a Printables model's files, added to a bench",
    "look": "look at a bench piece as an image",
    "image": "draw a picture onto a bench",
    "media": "watch or listen to a recording on a bench",
    "jobs": "hand a bench job to a worker",
    "open_bench": "open a new bench",
    "page": "move the person's page to a room or a bench",
    "printing": "printers, AMS slots and the print library",
    "stock": "the filament spools in stock",
    "calendar": "the household's calendars",
    "todo": "the household's to-do lists",
    "camera": "look through the cameras and list their recordings",
    "money": "accounts, transactions, categories and net worth",
    "print_queue": "put a print in the queue",
    "print_upload": "add a bench's STL or 3MF to the print library",
    "code_host": "the person's GitLab and GitHub projects, files and snapshots",
    "claude_code": "the person's Claude Code sessions",
    "watches": "watch something and be told when it changes",
    "discord_read": "the Discord channel's recent messages",
    "reminders": "set, list, change and cancel reminders",
    "devices": "the household's devices: satellites, tablets, servers and the house",
    "screen": "arrange the household's screens and what they show",
    "house_change": "change the house's configuration: automations, scripts, areas, names",
    "mail": "read, search, label and send mail",
    "code": "run code",
    "bench_run": "run a bench's code pieces",
    "browser": "drive a web browser",
    "home": "act in her Discord home channel",
}


def summary(key: str) -> str:
    """The line for group `key`; the key alone when it has none."""
    return SUMMARY.get(key, key)
