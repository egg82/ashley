"""The piece kind `measurements` is renamed `facts`: `bench_pieces.kind`, the `kind` of every stored command and effect
that names it (an Add, the piece an effect carries), the refusal `bad_measurements` of a stored outcome, and the file a
model run left for the next one (`measurements.json`, now `facts.json`)."""

import json
from typing import Any

from alembic import op

revision: str = "0122"
down_revision: str | None = "0121"


def _renamed(node: object, old: str, new: str) -> object:
    """`node` with every object's `"kind": old` made `"kind": new`."""
    loose: Any = node
    if isinstance(node, dict):
        return {k: new if k == "kind" and v == old else _renamed(v, old, new) for k, v in dict[str, Any](loose).items()}
    if isinstance(node, list):
        return [_renamed(v, old, new) for v in list[Any](loose)]
    return node


def _rename(old: str, new: str, old_reason: str, new_reason: str, old_file: str, new_file: str) -> None:
    conn = op.get_bind()
    conn.exec_driver_sql("UPDATE bench_pieces SET kind = %s WHERE kind = %s", (new, old))
    conn.exec_driver_sql("UPDATE bench_commands SET outcome = %s WHERE outcome = %s", (new_reason, old_reason))
    logged = conn.exec_driver_sql(
        "SELECT bench_id, seq, command::text, effect::text FROM bench_commands "
        "WHERE command::text LIKE %s OR effect::text LIKE %s", (f'%"{old}"%', f'%"{old}"%')).fetchall()
    for bench_id, seq, command, effect in logged:
        raw_command, raw_effect = json.loads(command), None if effect is None else json.loads(effect)
        new_command, new_effect = _renamed(raw_command, old, new), _renamed(raw_effect, old, new)
        if (new_command, new_effect) != (raw_command, raw_effect):
            conn.exec_driver_sql("UPDATE bench_commands SET command = %s::jsonb, effect = %s::jsonb "
                                 "WHERE bench_id = %s AND seq = %s",
                                 (json.dumps(new_command), None if new_effect is None else json.dumps(new_effect),
                                  bench_id, seq))
    conn.exec_driver_sql(
        "UPDATE code_runs SET out_files = (out_files - %s) || jsonb_build_object(%s::text, out_files -> %s) "
        "WHERE jsonb_exists(out_files, %s)", (old_file, new_file, old_file, old_file))


def upgrade() -> None:
    _rename("measurements", "facts", "bad_measurements", "bad_facts", "measurements.json", "facts.json")


def downgrade() -> None:
    _rename("facts", "measurements", "bad_facts", "bad_measurements", "facts.json", "measurements.json")
