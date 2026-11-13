"""The statements of `postgres.PostgresConnections`. A connection is visible to a person when it is the household's or
theirs (`VISIBLE`, taking household and person)."""

COLUMNS = ("id, household_id, kind, base_url, added_by, added_at, checked_at, person_id, label, needs, scopes, "
           "catalogue_provider")
WIDTH = len(COLUMNS.split(", "))
"""How many columns `COLUMNS` names: a statement that selects more after them reads those from this index on."""
VISIBLE = "household_id = %(household)s AND (person_id IS NULL OR person_id = %(person)s)"

GRANT_VALUES = "%(access)s::bytea, now() + %(expires_in)s::double precision * interval '1 second', %(scopes)s::text[]"

LIST = f"SELECT {COLUMNS} FROM connections WHERE {VISIBLE} ORDER BY kind, label, id"
OPEN = f"SELECT {COLUMNS}, secret FROM connections WHERE id = %(id)s AND {VISIBLE}"
IDENTITY = f"SELECT kind, person_id FROM connections WHERE id = %(id)s AND {VISIBLE} FOR UPDATE"
LOCK = "SELECT pg_advisory_xact_lock(hashtextextended(%(owner)s, 0))"
ADD = (
    "INSERT INTO connections (household_id, kind, label, base_url, secret, added_by, person_id, access_token, "
    "access_expires_at, scopes, catalogue_provider) "
    "SELECT household_id, %(kind)s, %(label)s, %(base_url)s, %(secret)s, id, %(owner)s::bigint, "
    f"{GRANT_VALUES}, %(catalogue_provider)s FROM people "
    "WHERE id = %(person)s AND household_id = %(household)s AND (SELECT count(*) FROM connections "
    "WHERE household_id = %(household)s AND kind = %(kind)s AND person_id IS NOT DISTINCT FROM %(owner)s::bigint) "
    f"< %(most)s ON CONFLICT DO NOTHING RETURNING {COLUMNS}"
)
WHY_NOT_ADDED = (
    "SELECT EXISTS (SELECT 1 FROM people WHERE id = %(person)s AND household_id = %(household)s), "
    "EXISTS (SELECT 1 FROM connections WHERE household_id = %(household)s AND kind = %(kind)s AND label = %(label)s "
    "AND person_id IS NOT DISTINCT FROM %(owner)s::bigint)"
)
REPLACE = (
    "UPDATE connections SET base_url = %(base_url)s, secret = %(secret)s, added_by = %(person)s, added_at = now(), "
    "checked_at = now(), needs = NULL, secret_version = secret_version + 1, access_token = %(access)s::bytea, "
    "access_expires_at = now() + %(expires_in)s::double precision * interval '1 second', scopes = %(scopes)s::text[], "
    f"catalogue_provider = %(catalogue_provider)s WHERE id = %(id)s RETURNING {COLUMNS}"
)
RELABEL = f"UPDATE connections SET label = %(label)s WHERE id = %(id)s RETURNING {COLUMNS}"
REMOVE = f"DELETE FROM connections WHERE id = %(id)s AND {VISIBLE} RETURNING kind"
SEED = (
    "INSERT INTO connections (household_id, kind, label, base_url, secret) "
    "SELECT id, %(kind)s, %(label)s, %(base_url)s, %(secret)s FROM households WHERE id = %(household)s "
    "AND NOT EXISTS (SELECT 1 FROM connections WHERE household_id = %(household)s AND kind = %(kind)s "
    f"AND person_id IS NULL AND (%(label)s = '' OR label = %(label)s)) ON CONFLICT DO NOTHING RETURNING {COLUMNS}"
)

OAUTH = (f"SELECT {COLUMNS}, secret, access_token, extract(epoch FROM access_expires_at - now()), secret_version "
         f"FROM connections WHERE id = %(id)s AND {VISIBLE}")
SEALED_FOR = "SELECT household_id, kind, person_id FROM connections WHERE id = %(id)s"
RENEWED = (
    "UPDATE connections SET secret = coalesce(%(secret)s::bytea, secret), access_token = %(access)s::bytea, "
    "access_expires_at = now() + %(expires_in)s::double precision * interval '1 second', "
    "secret_version = secret_version + 1 WHERE id = %(id)s AND secret_version = %(version)s RETURNING id"
)
NEEDS_RECONNECT = (
    "UPDATE connections SET needs = 'reconnect', secret_version = secret_version + 1 "
    "WHERE id = %(id)s AND secret_version = %(version)s RETURNING id"
)
