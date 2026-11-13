# Mail

## Her mail is a port with two adapters, and Proton's runs as a leased Bridge

She reads, searches, drafts, labels and sends a person's email,
and a watch over their inbox wakes a standing errand that sorts it and tells them what matters. Households use
either provider, so mail is a port with two adapters from the start: **Gmail** over Gmail's API, connected through
Google OAuth, and **Proton**, which has no public API, over IMAP and SMTP to Proton Mail Bridge, which she runs in the
clusters as a leased singleton. Mail is the first source a stranger can write to at will, so every part of it rests
on "A turn that has read outside words asks before it does anything consequential the person did not ask for": no mail tool ships before `Outside` does.

**Fits into** Connections, Tools, Watches and Errands, with one new system, Mail:

- **Connections** carries what mail is the first to need, and every later kind reuses: who holds a connection is the
  connection's, not the kind's; what a connection reaches is a list of resources, each shared or kept; a kind's
  secret can come from OAuth. Proton is a kind whose connecting runs through Bridge.
- **Mail**, the new system: a port, `ashley.mail.mailbox.Mailbox`, over neutral records, with an adapter per
  provider. It meets the four tests in `docs/systems.md` as the Ledger does: many callers (her mail tools, the inbox
  watch kind, the sorting errand, and later her readers, open-work "Readers she sends out"); one question ("what is in
  this mailbox, and change it as asked"); a second implementation from the start; and it owns policy (what a
  mailbox's id means, what a cut says, whether an account is still syncing). Rejected: mail tools over the
  Connections port alone, as the code host tools are. A code host is read only, by one tool source; mail is written
  as well and read by a watch kind, and those callers must not each learn two providers. Bridge's keeping (below) is
  part of Mail, not a system of its own: it has one caller and one implementation.
- **Tools**: a source, `ashley.tools.mail.MailTools`, added per turn by `ashley.channels.turn_tools.for_turn`.
- **Watches**: a new kind, `mail_inbox`, whose `outside` is true, so its woken turn starts tainted.
- **Errands**: the sort is a standing errand in the sense open-work's "Errands" gives it (a method, what wakes it, the tools its
  turn may use, where what it finds goes), built as a watch that does not expire while its mailbox answers. No bot
  store, no second queue.

### A connection has settings its person sets

**What is particular to a household is a setting of the connection it concerns, never shipped code or data.** A kind
declares its settings as data (`ConnectionKind.settings`: a key, a title, a help line, a field shape and what it
`decides`, `taint`, `tier` or `plain`); a connection of a kind with settings has a settings page in the connections room,
drawn from that schema, with pickers over what the service has now (`ConnectionKind.catalogue`, `GET
/api/connections/{id}/catalogue`). Home Assistant's are `household_reads` (lists only the household writes to),
`service_reads` (answers from a service the household trusts), `reads` (scripts that only look something up) and
`consequential_entities` (always judged); a new household starts with all of them empty.

- **Stored whole, under a revision.** `connection_settings` holds one row per connection; a write carries the revision
  it read and a stale one is 409 `version_conflict`. `connection_settings_log` has a row per changed key, written in the
  same transaction and kept 400 days by the write itself. Ids are checked for shape, never against the service: a
  device that is offline stays listed and is marked "not found now".
- **Written by a person only.** Any member of the household may edit, as with connections; no roles. Only the member
  route and the wiring import `SettingsWriter`, held by a boundary test with a planted violation, so no tool, channel or
  model call can widen what she trusts. Log lines carry key names and counts, never values.
- **Read once per turn** (`Tools.for_turn`), so one turn never sees two versions; none, or settings that cannot be read,
  is the least trust: every read is outside words, and only the general tier rules judge a change.
- **Rejected:** a household key/value table beside connections (a second store for what belongs to the thing it
  configures and dies with it); per-kind subclasses for settings; a TTL cache (a list changing mid-turn could untaint a
  read already counted); collapsing `reads` and `service_reads` (it would taint a distance or untaint every script).

### Who holds a connection, and who sees what it reaches

**Holding is the connection's.** `ConnectionKind.holders` is the set of `household` and `person` a
kind allows: Sure and Home Assistant the household's, a code host and herdr a person's, Google and Proton either. A
connection's `person_id` stays the one field that says which. The person who added a personal connection hands it to
the household, or takes back one they handed over, with `PATCH /api/connections/{id}` and `holder`; only `added_by`
may take one back, and any member may hand over or remove a household one, as today. Moving reseals the secret bound
to its new holder, in the same transaction, since a secret is sealed bound to household, kind and person. A move
that would pass the kind's `most` for the new holder is 409 `too_many`.

**Seeing is the resource's.** A personal Google login reaches all of its owner's mail (and later calendars), so
sharing the household's address must not share the login. A connection lists its **resources** as the service names
them: for mail, a mailbox (a Gmail account is one; a Proton account in split address mode is one per address). The
kind lists them (`ConnectionKind.resources(opened)`) when the connection is stored and again whenever the
room is opened, and a resource that disappears is dropped. Each resource of a personal connection is **kept** until
its owner **shares** it with the household (`PATCH /api/connections/{id}/resources/{ref}`, owner only). Every
resource of a household connection is shared, since the household already holds the login.

**The gate is by resource.** Mail tools over a mailbox are offered on a turn when:

| Mailbox | Reads | Changes (draft, label, send) |
|---|---|---|
| kept | the reply reaches its owner alone (`ashley.channels.audience.owner_alone`) and the speaker is the owner | the same |
| shared | any turn of the mailbox's household | the channel names the speaker (`Inbound.speaker_id`), a member of that household |

A satellite or the hallway tablet can read the household's shared address aloud; a voice match never makes anyone
the speaker of a change ("A voice names the speaker as a hint, never as a credential"). A change in a tainted turn is
held only where agreement can follow, which `Outside` already requires.

**The table** `connection_resources` holds `household_id` (as every table carries it), `connection_id` (cascading), `ref` (the service's own id, 1 to 200
characters), `kind` (`mailbox` today), `name` (what the room shows), `shared` (boolean), unique on
(`connection_id`, `ref`). The service, not a table check, holds the rule that a connection's `person_id` agrees with its
kind's `holders`.

**How the gate is built** (`ashley.connections.resources.ConnectionResources`, `ashley.connections.moves.move`):

- **The gate is `ConnectionResources.usable(use, changing)`**, `use` being `ashley.connections.resources.Use`
  (household, the speaker the channel names, whether the reply reaches them alone; `ashley.channels.audience.use_of`
  makes it from an `Inbound`), since Connections may not import channels. The rule itself is
  `ashley.connections.resources.permits`. It answers each usable resource with its connection and the person to open
  the login for (`Usable.opens_for`).
- **A turn that is not the owner's opens the owner's login only through a resource the gate returned.** `usable`
  hands back a shared resource's connection with its owner as `opens_for`, and the mail tools call the service as that
  person; a kept resource is never returned to another turn, so nothing else holds the owner's id on another's turn. The
  sealed secret stays bound to its holder and is never unsealed on a person's behalf by anything else.
- **Refusals.** Taking back a connection the signed-in person did not add is 403 `forbidden`; keeping a resource of a
  household's connection is 409 `held_by_household` (sharing one is a no-op 200); a person who cannot see a connection
  (it is another's, kept or shared) gets 404 for it, as everywhere. A body carrying a label and a holder, or neither, is 422.
- **A connection taken back leaves every resource kept**, and one handed over has every resource shared, both in the
  move's transaction: sharing again after a take-back is the owner's deliberate act, not a memory of the last hand-over.
- **A move onto a label the new holder already uses is 409 `label_taken`, and nothing moves**; the person renames
  first. A silent rename would leave a connection under a name its owner never chose.
- **A mailbox's address is stored when the connection is** (`ashley.mail.resources.mailboxes`, the Google kind's
  `resources`, registered in `ashley.wiring.CONNECTION_KINDS`), refreshed after each opening of the room has been answered
  (the room lists stored rows and never waits on a service), and read on the first turn that uses a connection stored
  without one. A tool call naming a mailbox the turn may not use is
  refused from stored addresses and reaches no mail service. A service that cannot say what a connection reaches leaves
  what is stored.

### A kind's secret can come from OAuth

A kind declares how it is connected (`ConnectionKind.connect`): `Pasted` (an address and a secret a person
pastes), `OAuth` (`ashley.connections.oauth.OAuthProvider` and the scopes the kind asks
for), or Bridge's login (Proton, below). For an OAuth kind the
sealed secret is the refresh token, and the row also keeps the sealed access token and its expiry, so a pod on
either site reuses an access token another pod obtained instead of refreshing per call.

- **Connecting runs as Discord linking does** ("A person links their own Discord account"): a same-origin `POST`
  starts it, a pending row bound to the person who started it is keyed by the hash of its state and taken once, with
  a PKCE verifier sealed in it, and the callback (`/api/connections/oauth/{provider}/callback`, the one GET that
  writes) stores the connection only when the signed-in person is the one who started it. The pending table is its
  own, `connect_pending`, so a state from a sign-in or a Discord link cannot complete it. The pending row carries the
  kind, label and holder chosen, so the callback needs nothing from the query but the code and state. The start is
  `POST /api/connections/oauth/{provider}/start`; the callback returns to `/connections?connect=<outcome>`. A person who
  connects again under the label of a connection they hold replaces its tokens, clears its `needs` and keeps its id.
  A start naming `holder` `household` makes the household's connection, for a kind that allows it (422 `unsupported` for one that does not); a person who connects again under a label replaces the connection of that holder.
- **A connection is stored only after the service answers with it**, as every kind's is: the kind's check is one
  authenticated read with the new access token (Google's userinfo for the account's address), and the scopes Google
  says it granted are stored with the row. A person who unticks a scope on the consent screen gets a connection whose
  tools needing it are not offered, and the room says what is missing.
- **Renewal is a compare-and-set.** `connections.secret_version` is the version. A pod whose access token is within
  `refresh_margin_s` of expiry refreshes, then writes the new access token (and the new refresh token, when the
  provider sent one) only where `secret_version` is still the one it read, raising it. A pod that loses reads the row
  again and uses the winner's token. Google keeps its refresh token, and a provider that rotates (Microsoft) is
  covered by the same write, since two pods may refresh at once and the loser's token would otherwise overwrite the
  current one.
- **A refused refresh marks the connection, never deletes it.** `connections.needs` is null, `reconnect` (an
  OAuth grant refused: `invalid_grant`, revoked, expired) or `login` (a Proton account Bridge signed out, below). The
  room shows it, her tools over it answer `needs_reconnect` rather than empty results, and connecting again over it
  replaces the secret and clears it.
- **Google is the first provider**, for the `mail` port (the calendar is a later port of the
  same kind). The kind is `google`, one per owner, its scopes `openid`, `email` and `gmail.modify`. The client's `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` live in the
  deployment's secret store; unset, connecting answers 503 and the room says it is not set up.
- **The consent screen is published, unverified.** Google's own documentation says an app whose publishing status is
  Testing gets refresh tokens that expire after seven days, unless it asks only for `openid`, `email` and `profile`.
  Gmail's read, modify and compose scopes are restricted, so a published app that is not verified shows Google's
  unverified-app warning and is capped at 100 users, which a household never reaches; verification would mean a
  security assessment for an app nobody outside the household uses. Google also drops a refresh token unused for six
  months and keeps at most 100 per account and client, dropping the oldest. A reconnect replaces the stored token,
  so the limit only drops tokens she no longer holds, and a connection her tools use never sits unused that long.

### Bridge runs as a leased singleton whose vault outlives its pod

Bridge's state is an encrypted vault (`vault.enc`: the Proton sessions and the IMAP passwords it issues), the keychain that opens it (`pass` with a GPG key, all files), and a message cache it rebuilds from Proton.
Measured on Bridge 3.27.1:

- The vault opens on another host. Moved alone with its keychain to a container with another hostname, after the
  first Bridge was killed, every address logged in over IMAP within seconds with the same passwords, and nobody
  logged in again.
- Proton rotates the refresh token on each refresh, and Bridge refreshes as it starts. A copy of the vault taken
  before a refresh was refused (`Invalid refresh token`, code 10013) and served no mailbox; the current vault still
  worked afterwards.
- Bridge rewrites the vault on each refresh (the first came about half an hour after login), on a settings change and
  when a sync finishes.
- A cache written by another Bridge is ignored: the new one resyncs from nothing (18 minutes for an 816 MB
  account) and serves every mailbox empty until it finishes, then ends with the same counts.

So the vault is the state worth keeping, it must be written back every time it changes, and two Bridges must never
run from copies of one vault.

**The pieces.**

- **The record**, `ashley.mail.proton_bridge.ProtonBridge`, a service behind the locator (Postgres; a Null
  Object that raises, so no Proton kind is offered): one row holding the vault and the keychain, each sealed under
  `CONNECTIONS_KEY` as connection secrets are; `generation`, raised on each write-back; `epoch`, raised each time a
  holder starts a new Bridge pod; the site and pod the epoch belongs to; `heartbeat_at`; and the TLS certificate
  fingerprint the pod last reported. Beside it, a row per Proton account Bridge holds: its Proton user id, the
  connection it is, its state (`connected`, `signed_out`, `locked`) and `synced_epoch`, the epoch in which Bridge last
  reported its sync finished.
- **The pod**, built from `deploy/mail-bridge/Containerfile` (Bridge's release, pinned, and the keeper), made
  by the singleton through `ashley.runs.kube_api.KubeApi`, as code runs and the warm look pod are. Its cache is an
  `emptyDir`, never shipped.
- **The keeper**, `deploy/mail-bridge/keeper.py`, a small program in the pod that imports nothing from
  `ashley` (its tests run in that image, as the CAD helper's do). It starts Bridge with its gRPC frontend, watches
  `vault.enc`, relays Bridge's IMAP and SMTP from its loopback to the pod's ports, and talks to the app over internal
  routes, `app/ashley/api/mail_bridge.py`, with a token minted per epoch whose hash the record keeps. The gRPC
  calls and events named here are in Bridge's `bridge.proto`; that the frontend runs with no GUI attached, and that
  3.27.1 has the same calls, was checked against a real 3.27.1 (below).
- **The singleton**, `ashley.mail.proton_bridge_job.run`, under `ashley.referee.lease.Lease` named
  `proton_bridge`, so it runs only on the site whose Patroni member leads. Each move between sites therefore costs
  one full resync (about 18 minutes for that account), accepted because moves are rare and her tools say
  `syncing` meanwhile.

**Exactly one Bridge, fenced by the epoch.**

1. A holder that takes the lease reads the record. A pod of the current epoch in its own site whose last heartbeat is
   within `fence_s` is adopted as it is, so a rollout of the app moves the lease without restarting Bridge or costing a
   resync. Otherwise it raises `epoch`, which retires any older pod at its next heartbeat, and waits until the older
   epoch's last heartbeat is `fence_s` plus `fence_margin_s` old before it makes a pod. A pod of the other site is
   always retired this way, never adopted; so is a pod of this site running another image than `MAIL_BRIDGE_IMAGE`, so a
   new image reaches Bridge through a raised epoch, with the fence wait, never by replacing a pod whose keeper still runs.
2. The keeper fetches the vault and keychain for its epoch, writes them into the pod, starts Bridge, and heartbeats
   every `heartbeat_s`. Every heartbeat and every write-back names the epoch, and the route refuses one that is not
   current (409) or cannot be written (503: the database is read-only during a demotion, or unreachable).
3. **Every time Bridge replaces `vault.enc`, the keeper writes it back before it handles anything else**, with the
   generation it holds, and the row takes it only at that generation and the current epoch. Bridge refreshes as it
   starts, so the first write-back follows each start within seconds.
4. **A keeper that cannot write back stops Bridge.** A refused or failed write-back, a refused heartbeat, or no
   heartbeat answered for `fence_s` kills Bridge and ends the pod. A Bridge must never run on with tokens nobody has
   stored, because the next start would be from a stale vault and be logged out.
5. The singleton sees its pod end and makes the next under a new epoch after `restart_s`, while it still holds the
   lease. A holder that loses the lease does not delete its pod: on a rollout the next holder adopts it, and on a
   failover the epoch and the keeper's own fence end it.

The fence is why the new holder can start without hearing from the old site: a pod cut off from the record stops by
itself within `fence_s`, and the new holder waits longer than that.

**One residual is accepted.** A refresh Bridge makes in the seconds between the database becoming read-only and the
keeper stopping it rotates a token nobody stored. The next Bridge then starts logged out of that account, and its
person logs in again from the room. It takes a refresh landing inside a window of seconds at a failover. It is
shown, not silent: the account's state is `signed_out` and its connection's `needs` is `login`.

**Logging in happens once, from the room.** A Proton account is added in the connections room like any kind: its
person types the Proton username and password, then the 2FA code (and the mailbox password, for an account with
two). The app relays each step to the keeper, which calls Bridge's `Login`, `Login2FA` and `Login2Passwords`. Nothing
typed is stored or logged: Bridge keeps the session in the vault, and the write-back stores it. Once Bridge reports
the user `connected`, the keeper turns on split address mode, the connection is stored with the account's Bridge
password as its sealed secret, and its addresses become its resources. A login cut off by a failover is started
again; it is the one Bridge step that is a person's, and it is never part of a failover.

**"Still syncing" is a field.** Bridge serves a new pod's mailboxes empty until its sync finishes. The keeper relays
Bridge's typed user events (`SyncStartedEvent`, `SyncProgressEvent`, `SyncFinishedEvent`, `UserBadEvent`, a user
signed out) to the record. A Proton mailbox whose account's `synced_epoch` is not the current epoch answers every read
`syncing` with the progress Bridge last reported, never an empty mailbox; the room shows the same. Neither the record
nor the tools read Bridge's log lines.

**How the Bridge pieces are built.**

- **Signatures, routes, environment.** The keeper's routes are `GET` and `PUT /api/mail-bridge/keeper/vault`, `POST
  .../heartbeat` and `POST .../events`, each with `Authorization: Bearer <token>` and the epoch in the body (the query on
  the `GET`); the room's are `POST /api/mail-bridge/login`, `/login/verified`, `/login/two-factor` and `/login/mailbox-password` (each
  with the label) and `GET /api/mail-bridge/accounts`. The keeper's own control port answers `POST /login`, `/login/verified`, `/login/two-factor`,
  `/login/mailbox-password` and `/forget`. The pod's environment is listed in `ashley.mail.proton_pod`; the app's is
  `MAIL_BRIDGE_IMAGE`, `_NAMESPACE`, `_APP_URL` and `_KEEPER_URL`, which is a comma-separated list of each site's own
  Bridge Service address, this site's first, since the pod runs in one cluster and no single address reaches it from both.
  A login step goes to the first address that accepts a connection; only a failure to connect moves on, not an HTTP answer
  and not a failed certificate check (a mismatch means a stale pod). The same list serves part 5's IMAP and SMTP.
- **What protects each link.** The control port (a typed Proton password, code and mailbox password, and the IMAP password
  coming back) is served over TLS under a per-pod certificate the app makes with the token and hands the pod in its Secret,
  and the app trusts only that certificate for that pod, beside the bearer token and the network policy; the keeper's calls
  to the app (the vault and keychain, heartbeat, events) go to an `https` address checked against the image's trust store,
  which settings insist on for `MAIL_BRIDGE_APP_URL` and `_KEEPER_URL`, each carrying the epoch's token; the keeper reaches
  Bridge over its loopback gRPC, TLS under Bridge's own certificate with its `server-token`; the vault is sealed in the
  database and never in the Secret, which holds only the token and the control port's key. The token and the control
  port's certificate (not the key) are also sealed into the Bridge record when the epoch is raised, so the site that does
  not run Bridge, whose cluster has no such Secret, relays a login too; the pod reads its Secret, the app reads the record.
- **"Written back before anything else" is the keeper's turn.** Every action the keeper takes for anyone starts in
  `Keeper.turn()`, which first reads `vault.enc` and writes it back when Bridge replaced it, so on the app's side a `vault`
  write precedes every later heartbeat, event and login answer, and `generation` rises by one each time. A login's wait for
  Bridge sits outside the turn so a slow login cannot starve the heartbeat, and its answer goes through one.
- **The keeper talks to Bridge over gRPC**, `bridge --grpc`, over TLS on the file socket named in `grpcServerConfig.json`
  with its token as `server-token` metadata; the stubs are generated from the pinned `bridge.proto` at image build. The keeper
  sees only `keeper_link.BridgeLink`, which tests fake; `keeper_grpc.GrpcBridge` is the one place that knows the wire. The
  keeper's rules are tested in the app's `tests` job, being standard library only; the image's test runs it against a real
  Bridge. Against a real 3.27.1 the start, `GuiReady`, the event stream, `GetUserList` and `ExportTLSCertificates` were
  exercised, and a second pod opened the vault and keychain the first wrote back; the login calls and user events need a
  Proton account and were not.
- **Proton's human check is done in the person's own browser, as Bridge's app does it.** When Bridge answers a login with
  `hvRequested` the keeper returns `human_verification` with Proton's page (an https page on proton.me, which the app checks
  before handing it on, and which carries a token so it is never logged); the room links to it, and the person's password
  sent again to `/login/verified` retries the same login with `useHvDetails`. Every other login event has its own named
  handling: a code is asked for after `tfaOrFidoRequested` too, a key-only account is refused as `security_key` (the key
  would have to be plugged into the pod), and each way Bridge ends a login is a typed refusal reason, none read as `other`
  unless the keeper does not know the event.
- **A refused heartbeat stops Bridge at once; an unanswered one after `fence_s`.** 409 (not the current epoch) and 503 (the
  record cannot be written) are the app answering that this Bridge must not run on, so waiting only widens the window the
  residual below describes; silence may be a network blip, and `fence_s` is what the new holder already waits out.
- **The keychain travels with the vault.** It is a tar of the `pass` store, the GPG home and Bridge's two marker files,
  written back in the same call as the vault (one generation, one atomic row), so a vault is never stored beside a keychain
  that cannot open it. A first start makes the GPG key (no passphrase) and `pass init` itself; Bridge fills the store.
- **`syncing` lives on the account row.** `Account.syncing` is true while the account is connected and its `synced_epoch` is
  not the record's epoch; the room reads it from `GET /api/mail-bridge/accounts`, and part 5's mailbox asks
  `ProtonBridge.accounts()` for the same. An account's addresses are kept on that row; `connection_resources` (part 3) is
  filled from them when the two parts meet.
- **Kubernetes calls for secrets.** `KubeApi` has `create_secret`, `secret`, `secrets` (by label) and `delete_secret`; the
  token Secret is named for its pod and made when the epoch is raised, for the pod to mount; the app reads the token and
  certificate from the record (`ProtonBridge.keeper_access`), never from the Secret. Every epoch but the current one has its pod and Secret deleted.

**What the app needs from the cluster repo** (both sites through the shared base): on each site, a Bridge Service of its
own with a fixed LoadBalancer address (as Postgres has), reaching the pod when it runs in that site's cluster; the image
built by CI as `apps/ashley-mail-bridge:<hash>`, pinned as the other pod images are; and a namespace
(`MAIL_BRIDGE_NAMESPACE`) in which the app's ServiceAccount may `create`, `get`, `list` and `delete` pods and Secrets; a
Service selecting `ashley.yggdrasil.pub/mail-bridge=true` on ports 8080 (keeper), 2143 (IMAP) and 2025 (SMTP), whose
`https` address, with the other site's, is `MAIL_BRIDGE_KEEPER_URL`; a network policy admitting the app alone to the keeper port, the pod to the app
(`MAIL_BRIDGE_APP_URL`, an `https` address with a certificate the image trusts) and to Proton, and nothing else; the image digest as `MAIL_BRIDGE_IMAGE`; and `SANDBOX_TOKEN_FILE`
and `CONNECTIONS_KEY` set where it is. Its keeper runs under whichever `Lease` is wired; without etcd there is no `SITE`,
so the pod's site is `local`. The pod runs as uid 1000 with a read-only root. The app pins
Bridge's TLS certificate by the fingerprint the keeper reports, as it pins a herdr bridge's.

### The mail port and her tools

The port's records are `ashley.mail.model`: `Header` (id, from, to, subject, date, a snippet, labels,
folder, unread, attachment count), `Message` (a header, the body as text, attachments by name, type and size),
`MailQuery` (from, to, subject words, text words, after, before, folder, label, unread, has attachment, page),
`Draft` (to, cc, subject, body, the message it replies to), `Target` (a message's id with the sender and subject the
person was shown) and `MailChange` (labels to add and remove, a folder to move to, read or unread). `MailQuery.page` is the cursor of the answer before, and a
`Page` is newest first, marked `cut`. The adapters are `ashley.mail.gmail.GmailMailbox` and
`ashley.mail.imap.ImapMailbox` (IMAP to Bridge, SMTP for sending); each is the only code that reads its provider's field
names. A message id is the adapter's: Gmail's message id; for Proton the `Message-ID` header (a hash of date, sender
and subject for a message with none), since Bridge assigns new UIDs when it resyncs and an id she was given before a
failover must still find its message. Bodies are turned to text
in code, HTML included. Failures are `MailFailed(reason)`: `refused`, `unreachable`, `syncing`, `needs_reconnect`,
`not_found`.

Her tools, in `ashley.tools.mail.MailTools`, name a mailbox by its address, never a connection id she may lose
between messages:

| Tool | `reads` | `outside` | What |
|---|---|---|---|
| `mail_boxes` | true | false | the mailboxes this turn may see: address, shared or kept, still syncing, and `unavailable` when it cannot be used now |
| `mail_labels` | true | false | a mailbox's folders and labels, set up by the household |
| `mail_search` | true | true | headers matching a `MailQuery`, newest first, capped and marked `cut` |
| `mail_read` | true | true | one message, paged with `start` and `next_start` as `git_read_file` is |
| `mail_draft` | false | false | a `Draft` saved in the mailbox's drafts |
| `mail_label` | false | false | a `MailChange` applied to listed message ids, at most `max_change_ids` |
| `mail_send` | false | false | a `Draft` sent from the mailbox |

Reading mail taints the turn, so every change after it is held for `carry_out`, and the held receipt shows each held
call's arguments in full: the recipients, subject and body of a send, the messages and labels of a sort. A label's
arguments carry each message's sender and subject beside its id, so the person agrees to messages they can recognise,
and the adapter refuses a call whose sender or subject does not match the id. `max_body_chars`
for a draft must fit `max_argument_chars` in `app/ashley/tools/outside.json`, and a test holds the two together, since a held call
past that limit is refused. A send or draft in a turn that has read nothing outside (an email the person dictates)
runs, as any change does. Moving to the trash is offered; deleting forever is not. A connection granted only the read
scope answers each change `needs_reconnect` (the room already lists the scope it is missing).

**How changes are made** (`ashley.mail.mailbox.Mailbox.draft`, `send` and `change`,
`ashley.tools.mail_change_specs`, `ashley.tools.mail_args`):

- **The gate for changing is `ConnectionResources.usable(use, True)`**, so a shared mailbox is changed only on a turn
  whose channel names a household member, and the three tools are offered only where one mailbox passes it.
- **A label call names `messages`, each with `id`, `from` and `subject`**, and `Mailbox.change` takes them as `Target`s. The
  adapter reads every message first and refuses the whole call (`refused`) unless each one's sender and subject begin
  with what was given, then makes one `batchModify`. Labels are named by the household's own labels only, so a system
  label (`TRASH`, `SPAM`, `INBOX`, `UNREAD`) cannot be reached by a name; moving is the folder (`inbox`, `archive`, `spam`,
  `trash`, each leaving the other folders it was in) and read state is `unread`.
- **A send is posted once and never retried**; a timeout answers `unreachable`, which leaves open whether it went.
- **Scopes.** The Google kind asks for `gmail.modify`, which includes the reads; a connection granted only
  `gmail.readonly` keeps reading.

**Settings are data**, `app/ashley/mail/mail.json`: page sizes and caps, `max_body_chars`, `max_recipients`,
`max_change_ids`, the OAuth `refresh_margin_s`, and Bridge's `heartbeat_s`, `fence_s`, `fence_margin_s`, `restart_s`
and the pod's cache size.

### The inbox watch and the sort

**`mail_inbox`** is a watch kind (`ashley.watches.mail_inbox.MailInbox`) whose target is a mailbox. Each read
takes the newest `max_items` messages in the inbox, each an item keyed by its message id and tracking `from`,
`subject`, `unread` and `labels`. Its default `when` is `[[new]]`, so a message read or labelled elsewhere wakes
nothing. Its `outside` is true: senders and subjects are written by strangers. A read answered `syncing` records no
check and is tried again at `retry_s`, so a failover's resync neither pauses the watch nor reads as every message
gone; the check's outcome for it is `ashley.watches.model.Later`. A message that arrives and leaves the
window between two checks is not seen, which `interval_s` keeps rare. The watch's target is the mailbox's address, as
the mail tools name one, and a read opens it as the person who armed the watch, in a turn that reaches them alone, so a
kept mailbox is read only for its owner and a shared one for any member. `Later` is also what the kind's read answers, so
a read and its check are the same value.

**The sort is a standing watch.** A watch carries `brief` (what this watch's turn is for, as a reminder's brief is:
people's data, never logged) and `standing`. A standing watch's `expires_at` moves forward by `hours` on every
successful read, so it lasts while its mailbox answers and ends only when disarmed or after its source has failed
for `hours`. A watch that is not standing still always ends. She arms one when asked ("sort my mail and tell me what
matters"), with `tools` naming the mail tools; naming tools that act makes arming a proposal agreed with
`arm_reminder`, as for any watch. Its woken turn starts tainted, so each change it would make goes by its tier, and the
held receipt goes out even when there is nothing else worth saying. The brief tells it to sort what is in the inbox,
not only the new message, so a later wake's proposal replacing an unanswered one covers the same messages. A `Later` read
(the mailbox still syncing) is not a successful read and does not move a standing watch's `expires_at`. `mail_inbox` is
offered to a person only while one of their connections can read mail and has no `needs`, so a person with none is never
offered a watch that could not read.

**The sort's changes go by their tier.** A label added or removed, a read state and a draft are tier b, so the woken turn
makes them without asking and each is recorded and shown under her reply (`decisions.md`, "A turn that has read outside
words asks before it does anything consequential the person did not ask for"). A move to the archive, spam or trash
and a send are tier c: they go to the action judge, and a move to spam or trash only when the provider marks every message
as spam or promotions (`Mailbox.junk`), else it waits for the person's OK. The household's labels are the mailbox's user
labels, which a label call names, and a system label can only be reached through `folder`, so a stranger's message can
choose which messages get a label but cannot reach a move. The brief need not name the mailbox for a label to run.

**What survives a failover:** the connection rows, resources, OAuth tokens, the Bridge vault, its epoch and the
watches are in Postgres. A pod on either site serves the Gmail tools on its next call. Proton mail answers `syncing`
until the new site's Bridge has resynced, then answers in full; message ids still resolve. A held send or label is a
proposal row and runs once.

**Logs:**

- `connections.refreshed` and `connections.refresh_refused` (connection id, kind, lost the race or not, reason);
  `connections.moved` and `connections.resource_shared` (connection id, holder or shared);
- `mail.call` (connection id, mailbox's resource id, call, status, count, duration_ms);
- `proton_bridge.started`, `.adopted`, `.retired`, `.stopped` (epoch, site, reason); `proton_bridge.written_back`
  (epoch, generation, bytes); `proton_bridge.refused` (epoch, which call, reason); `proton_bridge.sync` (epoch, Proton
  account's row id, started, progress or finished);
- the watch kind logs through the `watches.*` lines.

None carries an address, a subject, a body, a query, a token, a password or the vault.

**Measured by:**

- Blind contract tests per piece (`app/tests/mail_*_blind`), written from this section by an agent that has not seen
  the implementation, then a planted-mutant run:
  - holders: a move reseals and a sealed value moved without it does not open; only `added_by` takes one back; a kept
    mailbox is not offered on a shared channel, and a shared one is;
  - OAuth: two pods refreshing at once leave one current secret and both answer; a callback taken by another person
    is refused; a refused grant sets `needs` and keeps the row;
  - Bridge: a write-back at a stale generation or epoch is refused; a keeper whose heartbeat is refused stops Bridge;
    a new holder waits out the old epoch's fence; a same-site pod is adopted and a cross-site one retired; a mailbox
    of an account not synced this epoch answers `syncing`;
  - the port: each adapter, against captured provider responses, gives the same records for the same mailbox;
  - the watch: `syncing` records no check; a standing watch's expiry moves on success and not on failure;
  - the sort's tiers: in its woken turn a label added or removed, a read state and a draft run and are recorded, while a
    move to the archive, spam or trash and a send are held.
- Mutants to plant include: the compare-and-set dropped from renewal; a move judged by tool name alone; adopting a pod of the other site; a keeper that
  logs a failed write-back and runs on; `synced_epoch` compared to any epoch; a kept mailbox gated by the household;
  `mail_read` with `outside` false.
- The keeper's fence as a test in its image, run against a real Bridge: kill its database route and Bridge stops
  within `fence_s`.
- An eval, `python -m ashley.evals` over cases in data, measuring and never gating: "what did the school send" calls
  `mail_search` on the right mailbox; a message asking her to forward something holds the send and says it waits; a
  sort's wake labels, and tells the person only what its brief says matters.

**Rejected, and why:**

- **Rejected: Proton's SMTP submission tokens with no Bridge.** They send only, and only from custom-domain addresses.
- **Rejected: hydroxide.** It is archived and its IMAP is unfinished.
- **Rejected: a Bridge Deployment on each site that campaigns for the lease itself.** It would copy `Lease` and the
  Patroni leader check into a second program. The app already makes pods and already holds leases.
- **Rejected: shipping the cache.** Bridge ignores a cache another Bridge wrote and resyncs from nothing anyway, ending
  with the same mail.
- **Rejected: the vault in object storage.** Its write must be refused to a retired pod, and a row with a
  compare-and-set on the epoch does that in the store every other piece of her state is already in.
- **Rejected: deleting the pod when the lease is lost.** Every deploy would cost a full resync.
- **Rejected: telling "still syncing" from message counts or Bridge's log text.** An empty inbox is a real state, and
  log text is words. Bridge's events are typed.
- **Rejected: UIDs as message ids for Proton.** A resync assigns new ones.
- **Rejected: holding every send even in an untainted turn.** A send the person dictated in their own words is their
  change, as any other is; a reply to mail has read the mail and is held.
- **Rejected: a Google app left in testing.** Its refresh tokens die weekly.
- **Rejected: the sort as a repeating reminder.** New mail is a change with no event, which is what watches are for,
  and a reminder on a clock either wakes for nothing or lags the mail.
- **Rejected: a per-label grant agreed with the watch.** Labels are tier b, so the sort runs without one; a second
  mechanism beside the tiers would have to be kept in step with them. Moving, archiving and sending are tier c, which a
  grant never covered.
- **Rejected: one connection per mailbox.** A Google login reaches every mailbox and calendar of its owner; splitting
  it would mean consenting once per resource. Sharing is per resource inside one connection.

### The build, in parts

Each part is one merge request with its own blind suite, and ships alone. Mail's read tools wait for `Outside`.

1. **OAuth secrets**: `OAuthProvider`, `connect_pending`, the callback, renewal, `needs` and the `google` kind. First,
   because Gmail needs it.
2. **The mail port and Gmail's read tools**, personal connections only, so the gate is `owner_alone`.
3. **Holders and resources**, before Proton because the household's shared address is the first resource someone shares.
4. **Bridge as a leased singleton**, with no mail tool, so the fence is proven before any turn depends on it. The
   addresses are kept on the account row; `connection_resources` is filled from it.
5. **Proton's mailbox**: `ImapMailbox` behind the same tools.
6. **Changes to mail** on both adapters, the body limit held against `app/ashley/tools/outside.json`.
7. **The inbox watch** and the `Later` check.
8. **The sort**: `brief` and `standing` on watches.

**How Proton's mailbox is built** (`ashley.mail.imap.ImapMailbox`, `ashley.mail.routed.RoutedMailbox`):

- **One Mailbox in the locator, routed by kind.** `ashley.wiring` registers `RoutedMailbox`, which sends each call to the
  adapter of `Account.kind`; the Proton adapter is in it only where Bridge is wired, and a connection of a kind with no
  adapter is `refused`. `Account` carries `kind` and `address` (the mailbox of a Proton connection the call is for, since one
  connection reaches one per address), which the tools and the inbox watch fill from the connection and its resource. The
  tools hold no provider branch. `can_read` and `can_change` take the connection's kind with its scopes and the router asks
  that kind's adapter alone: a Proton connection has no scopes, so an empty scope list means nothing about the kind;
  `Mailbox.still_syncing` gives `mail_boxes` its `syncing` column. A mailbox the turn may see but not use is listed with
  an `unavailable` enum (`ashley.tools.mail_boxes`), never dropped: she reports the reason instead of inventing one. A
  mailbox its owner kept, on a turn that does not reach them alone, is a row with no address.
- **Every call signs in afresh** as the address with the Bridge password the connection holds, to the first site's Bridge
  Service address that accepts a connection, over STARTTLS (IMAP and SMTP are the relay's `proton_pod` ports; Bridge's own
  default is STARTTLS). The certificate is not checked against a name: its SHA-256 must be the fingerprint the keeper last
  reported (`Holder.certificate_sha256`), else the call is `unreachable` and no password is sent. `imaplib` and `smtplib`
  run in a thread. Before any connection the record is read: an account Bridge signed out is `needs_reconnect`, one not yet
  synced in this epoch is `syncing`, an address the account does not hold is `not_found`.
- **A message id is the `Message-ID` header without its brackets, cut to `message_id_chars`.** A message is found again by
  an IMAP `SEARCH HEADER Message-ID` (a substring match, which the cut id still satisfies) in `INBOX`, `Archive`, `Sent`,
  `Drafts`, `Trash` and `Spam`, and the answer is checked for the same id. A message with no `Message-ID` is named
  `nomid-` and a hash of its date, sender and subject, and found by reading the newest 200 of each folder. An id is
  the header's first `message_id_chars` (64) characters, not a hash of it: the same id after a resync, found by the same
  substring search, no table to keep. Real ids (Gmail's, Outlook's, list
  software's) are under 100 characters and carry their entropy at the front, so two messages share a 64-character prefix
  only in a pathological mailbox; the first match is read, and a change is checked against the sender and subject the
  person was shown.
- **Folders and labels as Bridge keeps them.** A label is the folder `Labels/<name>` holding a copy of each message with
  it; a search with no folder covers inbox, archive, sent and drafts, orders the hits by when Bridge received them, and
  cursors by offset; `has_attachment` is filtered on the message, as IMAP cannot search it.
- **Changes.** A draft is `APPEND` to `Drafts` with `\Draft`; a send is SMTP, once, to the first address that connects (Bridge
  keeps the sent message); a label is added by copying into its folder and removed by deleting from it; a move is a copy and a
  delete; read state is `\Seen`. Every target is read first and checked against what the person was shown
  (`ashley.mail.targets.shown`) before any is changed; IMAP has no batch, so a failure part way leaves the earlier ones changed.

Later consumers, not designed here: her readers (open-work, "Readers she sends out") use the read tools as they are;
the calendar is a second port on the `google` kind.
