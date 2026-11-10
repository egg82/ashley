"""Whether a tool or action name is one of a list of names, as data lists them (`home_assistant.json`, a wake rule's
`tools`)."""


def is_excluded(name: str, excluded: tuple[str, ...]) -> bool:
    """Whether `name` is one of `excluded`: equal to an entry, or the entry after a `domain__` prefix (a tool named
    `<domain>__<its own name>`)."""
    return any(name == e or name.endswith("__" + e) for e in excluded)
