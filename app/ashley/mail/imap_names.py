"""Folder names as IMAP writes them: modified UTF-7 (RFC 3501, 5.1.3) inside a quoted string, and a `LIST` answer's line
read back into the name."""

import base64
import re

_LIST = re.compile(r'^\((?P<flags>[^)]*)\) (?P<delimiter>"(?:[^"\\]|\\.)*"|NIL) (?P<name>.*)$', re.DOTALL)


def encode(name: str) -> str:
    """`name` in modified UTF-7."""
    out: list[str] = []
    pending: list[str] = []

    def flush() -> None:
        if pending:
            raw = base64.b64encode("".join(pending).encode("utf-16-be")).decode().rstrip("=")
            out.append("&" + raw.replace("/", ",") + "-")
            pending.clear()

    for char in name:
        if " " <= char <= "~":
            flush()
            out.append("&-" if char == "&" else char)
        else:
            pending.append(char)
    flush()
    return "".join(out)


def decode(name: str) -> str:
    """The text of a modified UTF-7 `name`; a malformed run is left as it came."""
    def one(found: re.Match[str]) -> str:
        run = found.group(1)
        if not run:
            return "&"
        try:
            padded = run.replace(",", "/") + "=" * (-len(run) % 4)
            return base64.b64decode(padded).decode("utf-16-be")
        except ValueError:
            return found.group(0)

    return re.sub(r"&([^-]*)-", one, name)


def quoted(name: str) -> str:
    """`name` as an IMAP quoted string, encoded."""
    return '"' + encode(name).replace("\\", "\\\\").replace('"', '\\"') + '"'


def listed(line: bytes, literal: bytes | None = None) -> str | None:
    """The folder name in one `LIST` answer line (its name as a literal when `literal` is given); None for a line that
    is not one, or a folder that cannot be selected."""
    found = _LIST.match(line.decode("utf-8", "replace"))
    if found is None or "\\noselect" in found.group("flags").lower():
        return None
    raw = found.group("name").strip()
    if literal is not None:
        return decode(literal.decode("utf-8", "replace"))
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        raw = re.sub(r"\\(.)", r"\1", raw[1:-1])
    return decode(raw)
