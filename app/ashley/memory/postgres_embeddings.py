"""Embeddings in the `facts` table, each statement inside the caller's transaction."""

from .postgres_queries import Connection, Vector


async def missing(conn: Connection, model: str, limit: int) -> list[tuple[int, str]]:
    """Up to `limit` current facts, oldest first, whose embedding is absent or was made by a model other than `model`,
    as (id, text)."""
    cur = await conn.execute(
        "SELECT id, text FROM facts WHERE valid_to IS NULL AND embedding_model IS DISTINCT FROM %s "
        "ORDER BY id LIMIT %s", (model, limit))
    return [(int(r[0]), str(r[1])) for r in await cur.fetchall()]


async def store(conn: Connection, fact_id: int, vector: Vector) -> bool:
    """Sets the embedding of a current fact; False when the fact is no longer current."""
    cur = await conn.execute(
        "UPDATE facts SET embedding = %s::vector, embedding_model = %s WHERE id = %s AND valid_to IS NULL "
        "RETURNING id", (vector.literal, vector.model, fact_id))
    return await cur.fetchone() is not None
