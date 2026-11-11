# People and sign-in

Who a person is, how they sign in, who is an admin, and the accounts they link.

## People sign in through OIDC

The web app, and anything else of hers with a login, uses OIDC, with the household's existing SSO as the provider. Each
OIDC account maps explicitly to a person, as each Discord account does, so a web session tells her who is
talking with nothing guessed. She keeps no passwords of her own.

- **Her web address is public from the start** (Cloudflare tunnel and the anycast gateway), so every route
  beyond `/api/health`, `/api/ready` and the page shell requires a signed-in person or device (below) from the day
  it is added, even before the web app has sign-in: an unauthenticated request gets 401, never data.
- **The provider is any OIDC one.** Authentik is the household's; CI signs in against a real Dex
  (`app/tests/test_signin_dex.py`) as the second, so nothing in sign-in is Authentik-specific. The account's username is
  `preferred_username`, else `name`.
- **Who may sign in is the IdM group `ashley_users`**, synced to the provider; the provider's application admits that
  group only. What belongs to one person (their memory, their Claude Code sessions) keys on the person an account
  maps to; the one role several people hold is admin (below), which the provider's groups may grant.
- **A device token works only from the LAN and the clusters.** Public traffic arrives only through the Cloudflare
  tunnel, and Cloudflare's edge sets `Cf-Connecting-IP` on what it forwards, which the gateway never does; so
  `POST /api/messages` answers a device token carrying that header with 401. A LAN client adding the header only locks
  itself out. Voice clips are not device-token routes: the random, short-lived token in the URL is their credential.
- **Each device has a rate limit kept in Postgres** (`device_requests`, a count per device and fixed window, counted by
  `Devices.allow` so every pod on both sites shares it): over it is 429 `rate_limited`. The numbers are
  `app/ashley/channels/device_rate.json`. Every refusal is one `api.device_refused` log line with the device id and
  its reason, never the token.
- **Every device carries every tool** until a device should not; scoping is decided per device then, not in advance.
- **An OIDC account maps to a person by its `sub`, which the admin maps after its first sign-in.** The
  provider's `sub` can be a hash of its user id, so nobody knows it beforehand. A sign-in by an account no person has is refused
  (`/?signin=unmapped`) and recorded with its OIDC username in `signin_unmapped`; the admin reads
  `python -m ashley.signin unmapped` and maps it with `python -m ashley.people add-account <person> oidc <sub>`.
  Rejected: mapping by username and pinning the `sub` at first sign-in, because a username can change or be reused
  at the provider, and until that first sign-in whoever holds the name would become that person. The username is only
  shown to the admin, never matched by code. The log line carries the first 12 hex of the sub's SHA-256, which the
  listing shows too.
- **A session is an opaque random token in a `__Host-` cookie** (Secure, HttpOnly, SameSite=Lax), stored as its
  SHA-256 in `sessions` with its account, so removing the account ends it. It lasts at most `session_days` and ends
  sooner when idle for `idle_days` (`app/ashley/signin/signin.json`); the database's clock decides, so pods on both
  sites agree. The sign-in in flight (PKCE verifier, nonce, return path) is in Postgres too, keyed by the hash of a
  state the browser holds in a cookie, taken once.
- **A write made with the session cookie must come from `PUBLIC_URL`'s origin, as JSON**: its `Origin` must match, or
  with no `Origin` its `Sec-Fetch-Site` must not name another site, and any body must be `application/json`. No CSRF
  token: every browser sends one of the two headers on a cross-site write, and a plain form cannot send JSON. The
  device rule above (`Cf-Connecting-IP`) does not apply to people: a session through the tunnel is the point.

## An admin changes what the deployment shares

Some state is the whole deployment's rather than one household's: a model provider's key pays for every household's
calls. Only an admin changes it. Who is an admin has two modes, chosen by `ADMIN_GROUP` (env, the sign-in client's
tier), and `GET /api/people` says which is in force (`admins_from`), so the client shows the grant controls only where
they work.

- **What is admin-only:** adding, replacing, renaming, removing or setting up a connection of a `deployment` kind
  (`ashley.api.admin_gate.may_change`), and granting or revoking admin. A route that is admin-only as a whole takes
  `admin_gate.Admin` as its signed-in person. Anyone else gets 403 `admin_only`. The person API carries `admin`, so the
  client hides what a person cannot do, but the server checks every change; hiding is never the check.
- **Not admin-only:** a household's own settings and connections stay any member's, as before. The settings that
  decide taint or judging are still written only by a person through the web; on a `deployment` connection that person
  must be an admin, since the setting then applies to every household.
- **The app decides (`ADMIN_GROUP` unset).** Admin is a field on the person (`people.admin`), not a system: People
  reads it and a narrow writer, `Admins` (`ashley.people.admins`), changes it, imported only by the sign-in and people
  routes and the wiring, so nothing she does on her own makes anyone an admin.
  - An admin grants and revokes admin from the web (`PUT /api/people/{id}/admin`), for the people of their own
    household. Revoking the last admin is refused (409 `last_admin`). Every admin write takes one transaction-scoped
    advisory lock (`people:admin`) before its conditional write, so two revokes at once on two sites cannot leave none.
  - Whenever no person is an admin, the earliest person of the first household (the lowest id) becomes one: each
    sign-in calls `Admins.ensure_one`, one conditional write under the same lock, so sign-ins racing on two pods make
    one admin, and always the same person. On a new deployment that person is the first to sign in. Sign-in already
    needs the provider to admit the account, so this is open to no stranger.
  - A deployment that had people when the flag arrived made every person of its first household an admin, which kept
    what they could do; an admin revokes the rest.
- **The provider decides (`ADMIN_GROUP` set).** The group of that name in the ID token's `groups` claim is the only
  source of truth; the sign-in asks for the `groups` scope as well. Each sign-in stores what the claim said on the
  session it opens and on every other live session of that person (`sessions.admin`), granting or revoking, and a
  person is an admin while that says so. It is written to `people.admin` too, but that is not read in this mode, so
  no earliest-person rule, no backfill and no grant made in the app carries over: a session opened before the group
  was set is no admin's, and every grant or revoke from the web is 409 `admins_from_provider`.
  - Unsetting `ADMIN_GROUP` returns to the app's own record: each person's flag as the group last set it at their
    sign-in (or as the app had it, for someone who has not signed in since the group was set), and if that leaves no
    admin, the earliest person of the first household becomes one at the next sign-in, whoever signs in.
  - **A change in the group takes effect at the person's next sign-in, not sooner.** Someone taken out of the group in
    the provider stays an admin on their open sessions until they sign in again or those sessions end (at most
    `session_days`, sooner when idle for `idle_days`; `app/ashley/signin/signin.json`). To revoke at once, remove them
    from the group and end their sessions (removing their account here ends every one).
  - Rejected: reading the claim again during a session. The app keeps no provider token to ask with, and a session
    would then depend on the provider being reachable for every request.
  - Rejected: reading `people.admin` in this mode as well. Grants made in the app before the group was set would then
    stand on every session not yet signed in again, for up to `session_days`.
- **Rejected:** "any person of the first household", which let a child or guest rotate the deployment's keys and gave
  one household control over every household's models and spend; a role per household, since what is gated is not
  any household's; making the first person to sign in the admin, which on a deployment the group had managed would
  hand it to whoever signed in next; a read-then-write for the first admin, which two sign-ins at once both pass; and
  the provider's group only granting, beside grants made here, which left anyone taken out of the group an admin for
  good.

## A person links their own Discord account

A signed-in person links their Discord account in the connections room through Discord's OAuth2, scope `identify` only,
which writes the same `accounts` row the admin CLI does (`system = discord`, the user's snowflake as `external_id`)
and its username as a `handle` shown to them alone. Their DMs to her are then theirs ("Discord is a bot"). The
Discord application's `DISCORD_OAUTH_CLIENT_ID` and `DISCORD_OAUTH_CLIENT_SECRET` live in the secret
store's `ashley-discord`, beside the bot token, whose ExternalSecret extracts every field; its redirect is
`<PUBLIC_URL>/api/accounts/discord/callback`. Unset, linking answers 503 and the room says it is not set up.

- **A link in flight is bound to the person who started it**, in `link_pending`, keyed by the hash of its state and
  taken once, as a sign-in's is. Starting it is a same-origin JSON `POST`. The callback is the one GET made with the
  cookie that writes, because Discord can only come back with a GET; it links only when the person signed in now is
  the one who started it (`?link=wrong_person` otherwise). That stops someone handing a person the callback for their
  own Discord account, which would let them DM her as that person. A link never shares a sign-in's table, so a state
  from one flow cannot complete the other.
- **A Discord account another person has is refused** (`?link=taken`) and left theirs: an account maps to at most
  one person, and moving it is the admin's call, since whoever linked it first may be right.
- **Discord's tokens are never stored.** The access token reads `GET /users/@me` once and is dropped.
- **A person unlinks only their own Discord accounts.** The account they sign in with is not theirs to unlink here:
  removing it ends their sessions, and only the admin can map it again.
