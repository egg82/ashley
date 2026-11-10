"""Who may hear what: the one rule facts and turns pass before they reach a prompt (`decisions.md`, "Every fact has an
owner, a household and one of four visibilities"). Memory filters facts by it, Conversations the turns a reply
carries, both in SQL, so what may not be heard never leaves the database."""

from typing import Literal

Visibility = Literal["shared", "discreet", "members", "private"]
"""Who may hear a thing other than its owner: `shared` anyone in the household, unprompted; `discreet` anyone who asks
directly, never volunteered; `members` any known person of the household, only when they alone hear the reply, never
volunteered (household money); `private` no one, filtered out in SQL."""

MAY_HEAR = """(visibility = 'shared'
               OR (visibility = 'discreet' AND %(speaker)s::bigint IS NOT NULL)
               OR (visibility = 'members' AND %(owner_only)s::boolean AND %(speaker)s::bigint IS NOT NULL)
               OR (visibility = 'private' AND %(owner_only)s::boolean AND owner_id = %(speaker)s::bigint))"""
"""A SQL condition on a row's `visibility` and `owner_id`, with the parameters `speaker` (the person who will hear,
NULL when unknown) and `owner_only` (whether only that person will hear or read it). An unknown speaker hears shared
rows; a known one also discreet rows, `members` rows when they alone hear the reply, and private rows only when they
own them and alone hear the reply. A row whose
`owner_id` is NULL and is private is heard by no one."""
