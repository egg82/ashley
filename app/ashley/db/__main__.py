"""`python -m ashley.db migrate`: run the migrations against DATABASE_URL."""

import sys

from .. import logs
from ..settings import from_env
from .migrate import migrate


def main(argv: list[str]) -> int:
    if argv != ["migrate"]:
        print("usage: python -m ashley.db migrate", file=sys.stderr)
        return 2
    logs.setup()
    migrate(from_env().database_url)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
