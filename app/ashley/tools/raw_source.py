"""The address that serves a page's source as plain text, for the two hosts whose ordinary page wraps it in chrome and
loses its indentation and blank lines when stripped to text: a Pastebin paste and a GitHub file view. Judged on the
parsed URL's host and path, never on text around it; any other URL has none."""

import re
from urllib.parse import urlsplit

_PASTE = re.compile(r"^/([A-Za-z0-9]{8})$")
_BLOB = re.compile(r"^/([^/]+)/([^/]+)/blob/([^/]+)/(.+)$")


def raw_url(url: str) -> str | None:
    """The plain-text address of the paste or file `url` shows; None for any other URL."""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.port is not None or parts.username is not None:
        return None
    if parts.hostname == "pastebin.com":
        found = _PASTE.match(parts.path)
        return None if found is None else f"https://pastebin.com/raw/{found[1]}"
    if parts.hostname == "github.com":
        blob = _BLOB.match(parts.path)
        return None if blob is None else "https://raw.githubusercontent.com/" + "/".join(blob.groups())
    return None
