"""Which object-store keys a bench still names: the large pieces on any bench (shelved ones included) and those in the
last `undo_window` commands of a bench's log, since an Undo of a Remove brings the piece back and needs its bytes, and
the artifacts of the bench runs that remain (`code_runs.artifacts`; pruning a run drops them). This is what the files sweep (`ashley.files.sweep`) is told not to delete."""

from .. import services
from ..db.database import Database
from ..files.intake import key_of
from .rules import Rules
from .stored_file import file_of

_SQL = """
    SELECT household_id, body FROM bench_pieces WHERE kind = ANY(%(kinds)s)
    UNION
    SELECT c.household_id, c.effect->'piece'->>'body'
    FROM bench_commands c JOIN benches b ON b.id = c.bench_id AND b.owner_id IS NOT NULL
    WHERE c.outcome = 'accepted' AND c.effect->'piece'->>'kind' = ANY(%(kinds)s) AND c.seq >= b.next_seq - %(window)s
"""


_ARTIFACTS = """
    SELECT household_id, a->>'sha256' FROM code_runs, jsonb_array_elements(artifacts) a
"""


async def named_keys(rules: Rules) -> frozenset[str]:
    """The key of every stored file a bench names, and of every artifact a bench run kept; a body that names none is
    passed over."""
    kinds = [name for name, kind in rules.kinds.items() if kind.family == "large"]
    async with services.get(Database).connection() as conn:
        cur = await conn.execute(_SQL, {"kinds": kinds, "window": rules.undo_window})
        rows = await cur.fetchall()
        made = await (await conn.execute(_ARTIFACTS)).fetchall()
    named = ((household, file_of(body)) for household, body in rows if body is not None)
    files = {key_of(household, file.sha256) for household, file in named if file is not None}
    return frozenset(files | {key_of(household, sha) for household, sha in made})
