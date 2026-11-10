"""The hybrid recall eval with the real embedder: `hybrid_cases.json` seeded into a throwaway database made beside
the one `DATABASE_URL` names (so the spend ledger and facts of the real one are untouched) and recalled twice, by
full-text alone and by full-text with the nearest facts by embedding, as the app does.

Needs the embedding model at `EMBED_MODELS_DIR` (the image has it) and a role that can create databases. Logs
`eval.memory_recall_hybrid` once: cases, hit rates, duration_ms. Never a case's text."""

import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import replace
from typing import Any

import psycopg

from .. import logs, services, wiring
from ..db.database import Database
from ..db.migrate import migrate
from ..memory.eval import hybrid
from ..memory.memory import Memory
from ..memory.postgres import PostgresMemory
from ..memory.recall_policy import RecallPolicy, load as load_policy
from ..settings import Settings
from . import scratch_db

log = logging.getLogger("ashley.evals")


def _household(url: str) -> tuple[int, int]:
    """A household and one conversation of it, for the facts to name."""
    with psycopg.connect(url) as conn:
        home = conn.execute("INSERT INTO households (name) VALUES ('eval') RETURNING id").fetchone()
        assert home is not None
        talk = conn.execute("INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                            (home[0],)).fetchone()
        assert talk is not None
        return int(home[0]), int(talk[0])


async def run(settings: Settings) -> str:
    """The report. Raises ValueError, naming the problem, when nothing could be embedded: a hybrid score with no
    vectors would be the full-text score under another name."""
    data = hybrid.load()
    name, url = scratch_db.create(settings.database_url)
    started = time.perf_counter()
    closers: list[Callable[[], Coroutine[Any, Any, None]]] = []
    try:
        migrate(url)
        home, talk = _household(url)
        closers = wiring.wire(replace(settings, database_url=url))
        database = services.get(Database)
        await database.open()
        try:
            refs = await hybrid.seed(services.get(Memory), home, talk, data)
            policy = load_policy()
            _check_embedded(url, len(refs))
            text_only = await hybrid.score(PostgresMemory(database, RecallPolicy(policy.limit, 0)), home, refs, data)
            both = await hybrid.score(PostgresMemory(database, policy), home, refs, data)
        finally:
            await database.close()
    finally:
        for close in closers:
            await close()
        scratch_db.drop(settings.database_url, name)
    report = render(text_only, both, policy)
    logs.info(log, "eval.memory_recall_hybrid", cases=len(data["cases"]),
              duration_ms=int((time.perf_counter() - started) * 1000),
              **{f"{k}_{style}": f"{h}/{n}" for k, scored in (("text", text_only), ("hybrid", both))
                 for style, (h, n) in scored.hits.items()})
    return report


def _check_embedded(url: str, facts: int) -> None:
    with psycopg.connect(url) as conn:
        row = conn.execute("SELECT count(*) FROM facts WHERE embedding IS NOT NULL").fetchone()
    if not row or row[0] != facts:
        raise ValueError(f"{facts - (row[0] if row else 0)} of {facts} facts could not be embedded; is the model at "
                         "EMBED_MODELS_DIR?")


def render(text_only: hybrid.Scored, both: hybrid.Scored, policy: RecallPolicy) -> str:
    """Hits per style, full-text alone then with the `policy.vector_k` nearest by embedding, then facts returned."""
    lines = [f"{'':12}{'full-text':>12}{'hybrid k=' + str(policy.vector_k):>14}"]
    total = [0, 0, 0]
    for style in sorted(both.hits):
        (a, n), (b, _) = text_only.hits[style], both.hits[style]
        lines.append(f"{style:12}{f'{a}/{n}':>12}{f'{b}/{n}':>14}")
        total = [total[0] + a, total[1] + b, total[2] + n]
    lines.append(f"{'all':12}{f'{total[0]}/{total[2]} {total[0] / total[2]:.0%}':>12}"
                 f"{f'{total[1]}/{total[2]} {total[1] / total[2]:.0%}':>14}")
    lines.append(f"facts returned per case: {text_only.returned:.1f} -> {both.returned:.1f}")
    lines.append(f"facts returned for a remark nothing answers: {text_only.returned_for_nothing:.1f} -> "
                 f"{both.returned_for_nothing:.1f}")
    lines.append("source: authored (blind-written, then measured against the shipped model)")
    return "\n".join(lines)
