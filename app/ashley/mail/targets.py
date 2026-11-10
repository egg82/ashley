"""A change's targets as the person was shown them, the check every adapter makes before it changes a message."""


def shown(actual: str, given: str) -> bool:
    """Whether `actual` (a header's value) starts with `given`, the first words of it as the person was shown them, with
    runs of space counted as one; an empty `given` matches only an empty value."""
    a, g = " ".join(actual.split()), " ".join(given.split())
    return a.startswith(g) and (bool(g) or not a)
