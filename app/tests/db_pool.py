"""A worker's databases made ahead of the test that takes them.

`CREATE DATABASE ... TEMPLATE` and `DROP DATABASE ... WITH (FORCE)` cost 0.1 to 0.6 s each on a busy server. The pool
runs both on background threads, so the next test's database is being cloned while the current test runs and the
last one's is dropped after it has finished. Every database is a fresh clone of the migrated template and is dropped,
never reused, so nothing a test leaves behind (rows, sequences, advisory locks, LISTEN channels, open connections,
prepared transactions) can reach the next test."""

import uuid
from concurrent.futures import Future, ThreadPoolExecutor

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


class DatabasePool:
    def __init__(self, admin: str, template: str) -> None:
        self._admin = admin
        self.template = template
        self._worker = ThreadPoolExecutor(max_workers=2, thread_name_prefix="db-pool")
        self._ready: Future[str] = self._worker.submit(self._create)
        self._drops: list[Future[None]] = []

    def take(self) -> str:
        """The connection string of a fresh database at the template's revision; the next is cloned meanwhile."""
        name = self._ready.result()
        self._ready = self._worker.submit(self._create)
        return make_conninfo(self._admin, dbname=name)

    def spare(self) -> str:
        """The name of the database being held ready for the next `take`."""
        return self._ready.result()

    def release(self, url: str) -> None:
        """Drop a database `take` returned, in the background."""
        self._drops.append(self._worker.submit(self._drop, str(conninfo_to_dict(url)["dbname"])))

    def close(self) -> None:
        """Drop the spare and wait for every pending drop; raises the first drop that failed."""
        self._drops.append(self._worker.submit(self._drop, self.spare()))
        self._worker.shutdown(wait=True)
        for drop in self._drops:
            drop.result()

    def _create(self) -> str:
        name = f"ashley_test_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(self._admin, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(name), sql.Identifier(self.template)))
        return name

    def _drop(self, name: str) -> None:
        with psycopg.connect(self._admin, autocommit=True) as conn:
            prepared = conn.execute("SELECT gid FROM pg_prepared_xacts WHERE database = %s", (name,)).fetchall()
        if prepared:
            with psycopg.connect(make_conninfo(self._admin, dbname=name), autocommit=True) as conn:
                for (gid,) in prepared:
                    conn.execute(sql.SQL("ROLLBACK PREPARED {}").format(sql.Literal(gid)))
        with psycopg.connect(self._admin, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
