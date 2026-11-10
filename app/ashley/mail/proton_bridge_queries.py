"""The statements of `proton_bridge_postgres.PostgresProtonBridge`. Each write from a pod carries `CURRENT`, so a pod
whose epoch is no longer the record's changes nothing."""

from typing import LiteralString

CURRENT = "id = 1 AND epoch = %(epoch)s"
ACCOUNT_COLUMNS = ("a.id, a.connection_id, a.proton_user_id, a.state, a.addresses, a.synced_epoch, b.epoch, "
                   "a.sync_progress")

HOLDER = ("SELECT epoch, site, pod, extract(epoch FROM now() - greatest(heartbeat_at, started_at)), "
          "certificate_sha256 FROM proton_bridge WHERE id = 1")
RAISE = ("UPDATE proton_bridge SET epoch = epoch + 1, site = %(site)s, pod = NULL, token_sha256 = %(token)s, "
         "keeper_access = %(access)s "
         "WHERE id = 1 AND epoch = %(expected)s RETURNING epoch")
POD_STARTED = (f"UPDATE proton_bridge SET pod = %(pod)s, started_at = now() WHERE {CURRENT} AND pod IS NULL "
               "RETURNING epoch")
KEEPER_ACCESS = f"SELECT keeper_access FROM proton_bridge WHERE {CURRENT}"
AUTH = "SELECT epoch, token_sha256 FROM proton_bridge WHERE id = 1"
HEARTBEAT = ("UPDATE proton_bridge SET heartbeat_at = now(), "
             f"certificate_sha256 = coalesce(%(certificate)s, certificate_sha256) WHERE {CURRENT} RETURNING epoch")
VAULT = f"SELECT generation, vault, keychain FROM proton_bridge WHERE {CURRENT}"
WRITE_BACK = ("UPDATE proton_bridge SET vault = %(vault)s, keychain = %(keychain)s, generation = generation + 1 "
              f"WHERE {CURRENT} AND generation = %(generation)s RETURNING generation")

ACCOUNTS = (f"SELECT {ACCOUNT_COLUMNS} FROM proton_bridge_accounts a, proton_bridge b WHERE b.id = 1 "
            "AND (%(user)s::text IS NULL OR a.proton_user_id = %(user)s) ORDER BY a.id")
ADD_ACCOUNT = (
    "INSERT INTO proton_bridge_accounts (household_id, connection_id, proton_user_id, state, addresses, synced_epoch) "
    "SELECT household_id, id, %(user)s, 'connected', %(addresses)s::text[], %(synced)s FROM connections "
    "WHERE id = %(connection)s "
    "ON CONFLICT (proton_user_id) DO UPDATE SET connection_id = EXCLUDED.connection_id, state = 'connected', "
    "addresses = EXCLUDED.addresses, synced_epoch = greatest(proton_bridge_accounts.synced_epoch, EXCLUDED.synced_epoch) "
    "RETURNING proton_user_id"
)
SET_STATE = ("UPDATE proton_bridge_accounts SET state = %(state)s WHERE proton_user_id = %(user)s AND "
             "(SELECT epoch FROM proton_bridge WHERE id = 1) = %(epoch)s RETURNING id, connection_id")
NEEDS_LOGIN = "UPDATE connections SET needs = 'login' WHERE id = %(connection)s"
CLEAR_LOGIN = "UPDATE connections SET needs = NULL WHERE id = %(connection)s AND needs = 'login'"

_SYNC_WHERE = "WHERE proton_user_id = %(user)s AND (SELECT epoch FROM proton_bridge WHERE id = 1) = %(epoch)s"
SYNC: dict[str, LiteralString] = {
    "started": f"UPDATE proton_bridge_accounts SET synced_epoch = 0, sync_progress = 0 {_SYNC_WHERE} RETURNING id",
    "progress": ("UPDATE proton_bridge_accounts SET sync_progress = least(1, greatest(0, %(progress)s::double precision)) "
                 f"{_SYNC_WHERE} RETURNING id"),
    "finished": (f"UPDATE proton_bridge_accounts SET synced_epoch = %(epoch)s, sync_progress = 1 {_SYNC_WHERE} "
                 "RETURNING id"),
}
