"""A guessed number is shown to the person as a choice row is (`Surfaced`), so the `asked` flag on a measurements row
goes: each stored `asked: true` on a guessed number becomes a `Surfaced` of the bench's log, hers, naming the number as
the person would have been shown it, and the key leaves every stored body, the log's included."""

import json
from typing import Any

from alembic import op

revision: str = "0119"
down_revision: str | None = "0118"


def _object(value: object) -> dict[str, Any] | None:
    loose: Any = value
    return dict[str, Any](loose) if isinstance(value, dict) else None


def _items(body: object) -> list[dict[str, Any]] | None:
    try:
        loaded = _object(json.loads(body)) if isinstance(body, str) and body.strip() else None
    except ValueError:
        return None
    raw: object = None if loaded is None or set(loaded) != {"items"} else loaded["items"]
    loose: Any = raw
    listed = list[object](loose) if isinstance(raw, list) else None
    found = None if listed is None else [_object(i) for i in listed]
    return [i for i in found if i is not None] if found is not None and None not in found else None


def _stripped(body: object) -> str | None:
    """`body` without any row's `asked`; None when it is not a measurements body or holds none."""
    items = _items(body)
    if items is None or not any("asked" in i for i in items):
        return None
    return json.dumps({"items": [{k: v for k, v in i.items() if k != "asked"} for i in items]}, ensure_ascii=False)


def _asked(body: object) -> list[dict[str, str]]:
    return [{"name": i["name"], "value": f"{format(float(i['value']), '.15g')} {i['unit']}"}
            for i in _items(body) or () if i.get("asked") is True and i.get("source") == "guessed"]


def _cleaned(node: object) -> object:
    """`node` with `asked` stripped from every `body` text under it."""
    loose: Any = node
    if isinstance(node, dict):
        return {k: (_stripped(v) or v) if k == "body" else _cleaned(v) for k, v in dict[str, Any](loose).items()}
    if isinstance(node, list):
        return [_cleaned(v) for v in list[Any](loose)]
    return node


def upgrade() -> None:
    conn = op.get_bind()
    pieces = conn.exec_driver_sql(
        "SELECT bench_id, household_id, piece_id, body, outside FROM bench_pieces WHERE kind = 'measurements' "
        "AND body LIKE '%%asked%%' ORDER BY bench_id, piece_id").fetchall()
    shown: dict[int, list[tuple[int, int, list[dict[str, str]]]]] = {}
    for bench_id, household_id, piece_id, body, outside in pieces:
        rows = [] if outside else _asked(body)
        if rows:
            shown.setdefault(bench_id, []).append((household_id, piece_id, rows))
        text = _stripped(body)
        if text is not None:
            conn.exec_driver_sql("UPDATE bench_pieces SET body = %s WHERE bench_id = %s AND piece_id = %s",
                                 (text, bench_id, piece_id))
    logged = conn.exec_driver_sql(
        "SELECT bench_id, seq, command::text, effect::text FROM bench_commands "
        "WHERE command::text LIKE '%%asked%%' OR effect::text LIKE '%%asked%%'").fetchall()
    for bench_id, seq, command, effect in logged:
        raw_command, raw_effect = json.loads(command), None if effect is None else json.loads(effect)
        clean_command, clean_effect = _cleaned(raw_command), _cleaned(raw_effect)
        if (clean_command, clean_effect) != (raw_command, raw_effect):
            conn.exec_driver_sql("UPDATE bench_commands SET command = %s::jsonb, effect = %s::jsonb "
                                 "WHERE bench_id = %s AND seq = %s",
                                 (json.dumps(clean_command), None if clean_effect is None else json.dumps(clean_effect),
                                  bench_id, seq))
    for bench_id, groups in shown.items():
        next_seq = conn.exec_driver_sql("SELECT next_seq FROM benches WHERE id = %s", (bench_id,)).scalar_one()
        for household_id, piece_id, rows in groups:
            conn.exec_driver_sql(
                "INSERT INTO bench_commands (bench_id, household_id, seq, person_id, command, outcome, effect) "
                "VALUES (%s, %s, %s, NULL, %s::jsonb, 'accepted', %s::jsonb)",
                (bench_id, household_id, next_seq,
                 json.dumps({"type": "surfaced", "piece_id": piece_id, "rows": rows}),
                 json.dumps({"type": "shown", "piece_id": piece_id, "rows": rows})))
            next_seq += 1
        conn.exec_driver_sql("UPDATE benches SET next_seq = %s WHERE id = %s", (next_seq, bench_id))


def downgrade() -> None:
    """Nothing to undo: what the flag said is in the log as a `Surfaced`."""
