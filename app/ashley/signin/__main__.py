"""`python -m ashley.signin unmapped`: the OIDC accounts refused at sign-in because no person has them, most recently
tried first, for the admin's own terminal: the sub, its first 12 hex of SHA-256 (what the refusal's log line carries),
the OIDC username, and when it last tried. Map one with
`python -m ashley.people add-account <person_id> oidc <sub>`; it then leaves this list. Run where DATABASE_URL is
set (`kubectl exec deploy/app`)."""

import argparse
import sys

import psycopg

from ..settings import from_env
from .identity import sub_prefix


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="python -m ashley.signin")
    sub = top.add_subparsers(dest="command", required=True)
    sub.add_parser("unmapped", help="OIDC accounts refused for want of a person")
    return top


def unmapped(conn: psycopg.Connection) -> list[tuple[str, str, str]]:
    """(sub, username, last tried as ISO 8601) for each refused OIDC account no person has yet."""
    rows = conn.execute(
        "SELECT u.external_id, u.username, u.last_seen_at FROM signin_unmapped u "
        "WHERE u.system = 'oidc' AND NOT EXISTS "
        "(SELECT 1 FROM accounts a WHERE a.system = u.system AND a.external_id = u.external_id) "
        "ORDER BY u.last_seen_at DESC").fetchall()
    return [(r[0], r[1], r[2].isoformat(timespec="seconds")) for r in rows]


def main(argv: list[str]) -> int:
    """0 done; 1 the database unreachable; 2 usage or an unset DATABASE_URL."""
    parser().parse_args(argv)
    try:
        url = from_env().database_url
    except KeyError:
        print("DATABASE_URL is unset", file=sys.stderr)
        return 2
    try:
        with psycopg.connect(url) as conn:
            rows = unmapped(conn)
    except psycopg.OperationalError:
        print("database unreachable", file=sys.stderr)
        return 1
    for sub, username, seen in rows:
        print(f"{sub}\t{sub_prefix(sub)}\t{username or '-'}\t{seen}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
