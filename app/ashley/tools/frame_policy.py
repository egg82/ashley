"""Whether a page may be shown in a frame on ours, decided from how the site answered (`page_fetch.Reply`), never from its
text. A non-2xx answer refuses (a challenge or an error page is no page to show). A `Content-Security-Policy`
`frame-ancestors` decides when there is one, as a browser lets it override `X-Frame-Options`: every policy the answer
carries must name our origin, `*` or `https:`; `'none'`, `'self'` (the site's own) and an empty list name nobody. Without
one, `X-Frame-Options` `DENY` or `SAMEORIGIN` refuses. `origin` is where this page is reached (`public_url`), empty when
unknown, in which case only `*` and `https:` allow."""

from urllib.parse import urlsplit

from .page_fetch import Reply


def frameable(reply: Reply, origin: str) -> bool:
    """Whether `reply` lets a page at `origin` frame it."""
    if not 200 <= reply.status < 300:
        return False
    policies = [_ancestors(p) for p in reply.headers.get("content-security-policy", "").split(",")]
    named = [sources for sources in policies if sources is not None]
    if named:
        return all(_allows(sources, origin) for sources in named)
    values = {v.strip().upper() for v in reply.headers.get("x-frame-options", "").split(",")}
    return not values & {"DENY", "SAMEORIGIN"}


def _ancestors(policy: str) -> list[str] | None:
    """The source list of the policy's `frame-ancestors`, None when it has none."""
    for directive in policy.split(";"):
        words = directive.split()
        if words and words[0].lower() == "frame-ancestors":
            return words[1:]
    return None


def _allows(sources: list[str], origin: str) -> bool:
    parts = urlsplit(origin)
    return any(_matches(source.lower(), parts.hostname or "", parts.port) for source in sources)


def _matches(source: str, host: str, port: int | None) -> bool:
    if source in ("*", "https:"):
        return True
    if not host or source.startswith("'") or source.endswith(":"):
        return False
    wanted = source.removeprefix("https://")
    if "://" in wanted:
        return False
    name, _, given = wanted.partition(":")
    if given not in ("", "*") and given != str(port or 443):
        return False
    return host == name or (name.startswith("*.") and host.endswith(name[1:]))
