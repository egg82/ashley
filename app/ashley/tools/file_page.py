"""One page of a text file as `git_read_file` answers it: the longest stretch from `start` whose whole answer fits the
characters a result may have, so the tool loop never cuts it."""

from . import cut


def page(path: str, text: str, start: int, fetched_short: bool, result_chars: int) -> dict[str, object]:
    """`{path, start, text, total_chars, next_start, truncated}`: `next_start` is where the following page begins, null
    at the end of `text`; `truncated` is true when the host held more of the file than was fetched, so the end of
    `text` is not the end of the file."""

    def body(n: int) -> dict[str, object]:
        end = start + n
        return {"path": path, "start": start, "text": text[start:end], "total_chars": len(text),
                "next_start": end if end < len(text) else None, "truncated": fetched_short}

    return body(cut.fit(len(text) - start, body, result_chars))
