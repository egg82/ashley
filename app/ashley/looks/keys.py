"""Where a look's picture is kept: under its own prefix in the object store, apart from a bench's files
(`ashley.files.intake.PREFIX`), because a picture she was given outlives the piece it was of and a sweep of files no
piece names must never reach it."""

PREFIX = "look/"


def key_of(household_id: int, sha256: str) -> str:
    """Where a look's bytes are: under their household, as a file's are."""
    return f"{PREFIX}{household_id}/{sha256}"
