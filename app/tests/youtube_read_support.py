"""The captured YouTube watch page (`youtube_captured/`) and a server for it."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx2

from search_support import Fake

CAPTURED = Path(__file__).parent / "youtube_captured"
WATCH_HTML = (CAPTURED / "watch_page.html").read_text(encoding="utf-8")
VIDEO = "x7Kq2LmN9Rp"
WATCH = f"https://www.youtube.com/watch?v={VIDEO}"
PLAYER: dict[str, Any] = json.loads(WATCH_HTML.split("ytInitialPlayerResponse = ")[1].split(";var meta")[0])


def youtube(pages: Mapping[str, httpx2.Response]) -> Fake:
    """Serves each address its response; any other is a 404."""
    return Fake(lambda request: pages.get(str(request.url), httpx2.Response(404)))
