"""Helpers for the blind `Conversations.for_thread` tests: which conversation a thread points at, read from the
schema's `conversation_threads`, and a footprint that includes it so a call that must write nothing can be checked."""

from typing import Any

import psycopg
from conversations_support import footprint

ANY_KIND: Any = "not-a-kind"
"""Typed Any because a value outside `Kind` is the case under test."""


def target(url: str, thread: str) -> int | None:
    """The conversation `thread` points at, None when it points at none."""
    with psycopg.connect(url, autocommit=True) as conn:
        row = conn.execute("SELECT conversation_id FROM conversation_threads WHERE thread = %s", (thread,)).fetchone()
    return None if row is None else int(row[0])


def point(url: str, thread: str, household_id: int, conversation_id: int) -> None:
    """Point `thread` at a conversation directly, as a second thread carrying the same conversation would be."""
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("INSERT INTO conversation_threads (thread, household_id, conversation_id) VALUES (%s, %s, %s)",
                     (thread, household_id, conversation_id))


def conversation_count(url: str) -> int:
    with psycopg.connect(url, autocommit=True) as conn:
        row = conn.execute("SELECT count(*) FROM conversations").fetchone()
    assert row is not None
    return int(row[0])


def everything(url: str) -> tuple[str, ...]:
    """`footprint` plus every thread row."""
    with psycopg.connect(url, autocommit=True) as conn:
        row = conn.execute("SELECT coalesce(string_agg(t::text, '|' ORDER BY t::text), '') "
                           "FROM conversation_threads t").fetchone()
    assert row is not None
    return (*footprint(url), str(row[0]))
