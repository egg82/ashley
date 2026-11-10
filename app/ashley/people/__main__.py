"""`python -m ashley.people <command>`: add households, people and their accounts, and set a household's profile.
Run where DATABASE_URL is set (`kubectl exec deploy/app`). Each add prints the new id; `list` prints a household's
people with their accounts, for the admin's own terminal."""

import argparse
import sys
from pathlib import Path

import psycopg

from ..settings import from_env
from . import admin


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="python -m ashley.people")
    sub = top.add_subparsers(dest="command", required=True)
    p = sub.add_parser("add-household", help="print the new household id")
    p.add_argument("name")
    p.add_argument("--timezone", required=True, help="an IANA name, e.g. America/Denver")
    p = sub.add_parser("set-profile", help="replace a household's profile with the text of FILE")
    p.add_argument("household_id", type=int)
    p.add_argument("file", type=Path)
    p = sub.add_parser("add-person", help="print the new person id")
    p.add_argument("household_id", type=int)
    p.add_argument("name")
    p = sub.add_parser("add-account", help="map SYSTEM's EXTERNAL_ID to a person; print the new account id")
    p.add_argument("person_id", type=int)
    p.add_argument("system", help="home_assistant, discord, oidc")
    p.add_argument("external_id")
    p = sub.add_parser("list", help="a household's people and their accounts")
    p.add_argument("household_id", type=int)
    return top


def execute(conn: psycopg.Connection, args: argparse.Namespace) -> str:
    """Run one command and return what to print. Raises ValueError, OSError, NotFound or psycopg.IntegrityError."""
    match args.command:
        case "add-household":
            return str(admin.add_household(conn, args.name, args.timezone))
        case "set-profile":
            admin.set_profile(conn, args.household_id, args.file.read_text(encoding="utf-8"))
            return f"profile set for household {args.household_id}"
        case "add-person":
            return str(admin.add_person(conn, args.household_id, args.name))
        case "add-account":
            return str(admin.add_account(conn, args.person_id, args.system, args.external_id))
        case _:
            return "\n".join(f"{i}\t{name}\t{system or '-'}\t{external or '-'}"
                             for i, name, system, external in admin.listing(conn, args.household_id))


def main(argv: list[str]) -> int:
    """0 done; 1 refused (the reason on stderr); 2 usage or an unset DATABASE_URL."""
    args = parser().parse_args(argv)
    try:
        url = from_env().database_url
    except KeyError:
        print("DATABASE_URL is unset", file=sys.stderr)
        return 2
    try:
        with psycopg.connect(url) as conn:
            out = execute(conn, args)
    except admin.NotFound:
        print("no such household or person", file=sys.stderr)
        return 1
    except (ValueError, OSError) as e:
        print(e, file=sys.stderr)
        return 1
    except psycopg.errors.IntegrityError as e:
        print(f"refused by the database: {e.diag.constraint_name or e.sqlstate}", file=sys.stderr)
        return 1
    except psycopg.OperationalError:
        print("database unreachable", file=sys.stderr)
        return 1
    if out:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
