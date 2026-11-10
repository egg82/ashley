"""`python -m ashley.memory report --conversation N`: what she knew at each reply of a conversation, and what was
written from it. Reads log lines from stdin, needs DATABASE_URL, prints the report, which includes fact text (the
operator's terminal; the logs never carry it). From either site:

    kubectl --context <site> -n ashley logs deploy/app --since=24h \\
      | kubectl -n ashley exec -i deploy/app -- python -m ashley.memory report --conversation N

or Loki's export of the same lines. Exit 2 with a usage message on bad arguments or an unset DATABASE_URL, else 0,
including when nothing was found."""

import argparse
import asyncio
import os
import sys
from typing import NoReturn

import psycopg

from . import postgres_queries as q
from .report import render, seen


class _Usage(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _Usage(message)


async def _report(database_url: str, conversation_id: int, lines: list[str]) -> str:
    replies, writes = seen(lines, conversation_id)
    ids = sorted({i for r in replies for i in (*(r.standing or ()), *(r.recalled or ()), *r.used)}
                 | {i for w in writes for i in w.inserted})
    async with await psycopg.AsyncConnection.connect(database_url) as conn:
        facts = await q.by_ids(conn, ids)
        writers = await q.writers(conn, conversation_id)
    return render(conversation_id, replies, writes, facts, writers)


def main(argv: list[str]) -> int:
    parser = _Parser(prog="python -m ashley.memory", add_help=False)
    parser.add_argument("command", choices=["report"])
    parser.add_argument("--conversation", type=int, required=True)
    try:
        args = parser.parse_args(argv)
        database_url = os.environ["DATABASE_URL"]
    except (_Usage, KeyError) as e:
        print(f"usage: python -m ashley.memory report --conversation N (DATABASE_URL set); {e}", file=sys.stderr)
        return 2
    print(asyncio.run(_report(database_url, args.conversation, sys.stdin.read().splitlines())), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
