# Connections and the ledger

A household's links to services outside her, the model providers' keys among them, and the ledger her money is read through.

## A household connects its own services

A household's links to services outside her are Connections (`ashley.connections.connections.Connections`), each a kind,
a label, a base URL and a secret, addressed by its id: Sure, the household's finance app, and Home Assistant, its house (a code host is a person's own, below).
Any person of the household adds, replaces and removes one in the connections room (`app/ashley/api/connections.py`):
there is no household admin role, and each household service's own tenancy is the household (every member's Sure key sees the
same family's accounts; one HA is the one house), so a key per person would add setup and no privacy.

- **The secret is sealed at rest** with AES-256-GCM under the app's one key, `CONNECTIONS_KEY` (the secret
  store's `ashley-connections`): a version byte naming the key, a random nonce, and the household and kind as
  associated data, so a sealed value copied to another row does not open (`ashley.connections.sealing`). It is never
  on the wire back and never logged. Without the key nothing can be added or read, and the room says it is not set up.
- **The deployment's own secrets are rows it makes for itself**, not connections: the key that signs file links and
  her Web Push key pair (`ashley.connections.deployment_secrets`). No outside service holds them, so there is nothing to
  check a value against, and no person edits them: a replaced VAPID pair orphans every browser's subscription and a
  replaced link key breaks every live link. Each is a row of `deployment_secrets` (the pair as one value, so no race can
  split it), sealed under `CONNECTIONS_KEY` bound to its name. Every pod settles them at start (`ashley.wiring_secrets`):
  a row wins; with none, the env's value (`FILES_LINK_KEY`, `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY`) is written, and
  with neither a fresh one from the system's CSPRNG, a P-256 pair for push. The write is `ON CONFLICT DO NOTHING` and is
  read back in the same transaction, so pods starting on both sites at once all keep the value written first, with no
  lease. Until a pod has settled (the database away, a row this key cannot open: logged and retried) the env's values
  answer; the push singleton and browsers' subscriptions start once it has. Without `CONNECTIONS_KEY` the env's values
  are all there is. Rejected: a `deployment` connection kind, which would offer the room's replace and remove, and a
  check, for values only she holds; one row per VAPID key, which two pods could fill from two different pairs.
- **A connection is stored only after the service answers with it**: the kind's one authenticated read (Sure's
  accounts, Home Assistant's `GET /api/`, a code host's `GET /user`). A refusal says why (`bad_url`, `key_refused`,
  `unreachable`, `wrong_service`), in the kind's own words, and stores nothing. Sure's address is https; Home Assistant's may be http, since most are
  served on the household's own network with no certificate (`http://homeassistant.local:8123`, say). No redirect is
  followed, since one would carry the key wherever it points.
- **Her money tools are offered only where the reply reaches the speaker alone**
  (`ashley.channels.audience.owner_alone`): the channel names the speaker, its audience is `owner`, it is not shared,
  and no device's screen shows the thread. A person's web chat, their bench talk and their Discord DM qualify; a
  satellite, the hallway tablet and a household's Discord channel never do, voice match or not.
- **She reads, and sets a transaction's category**, through the Ledger (below; Sure's REST API behind it) with `ashley.tools.money.MoneyTools`: accounts, transactions by date,
  account, category, words and type, categories, and net worth, and `money_categorise` (below). Each answer is compact, capped
  (`app/ashley/tools/money.json`) and marked `cut` when Sure holds more. Each answered read moves the connection's
  `checked_at`, which the room shows. So does an answered read of any kind: Sure's in `SureLedger`, a code host's in
  `RoutedCodeHost` (the `Access` carries its connection id), Home Assistant's on each JSON response of its client and each WebSocket command it answers successfully
  (`ConnectedHomes`; a rejected or refused command records nothing), all through `ashley.connections.answered.record`. Each is one write by primary key, with no
  throttle, since consecutive reads must each move it.
- **Everything that touches a house asks for its household's** (`ashley.home_assistant.homes.Homes`), with the
  household it already holds: her house tools and the look-up's places near the house, built once per household's
  Home and kept while its connection is unchanged (`ashley.tools.everyday.Everyday`), presence, room speakers, the
  hallway tablet's controls and a bench's automations. A household with none has no house tools, presence unknown and
  room speakers that fall back to the satellite. Each call reads the connection, so a replacement on either site is
  seen on the next one; while the connections cannot be read, the last client seen goes on answering.
- **The house wired for the whole process before is household 1's connection**: at start, with `HA_URL` and `HA_TOKEN`
  set, each pod seals them as household 1's `home_assistant` row where it has none (`ashley.home_assistant.seed`), so
  an existing deployment's house keeps answering after the deploy with no person step. Never over a row a person added. Until a row
  of household 1's has been seen (or with no `CONNECTIONS_KEY`), the env's HA answers for it, and a read tries the seed
  again at most once a minute, so a seed that failed at start (the database away during a rollout, a pod ahead of the
  migration) heals without a restart. Until the env is removed (`open-work.md`), a person who removes household 1's
  HA in the room sees it come back at the next pod start.
- **The kinds are the adapters' to declare** (`ashley.connections.kinds.ConnectionKind`, registered in
  `ashley.wiring.CONNECTION_KINDS`): a name, who may hold it (`holders`), the address rule (schemes, or one fixed address),
  the field that carries the secret, the check, the refusal texts, the panel's words and `most`. The routes are
  `POST /api/connections` (a new one, naming its kind and label) and `PUT`/`PATCH`/`DELETE /api/connections/{id}`
  (replace the address and secret, rename, remove); a body is typed by secret shape (`api_key` or `token`). A kind
  nothing registered is 404, and a body carrying the other field than the kind's is 422. A connection the signed-in
  person cannot see (another household's, or another person's code host) is 404, never 403. `GET /api/connections` serves the
  kinds, so the panel renders what the server offers. Refusal reasons are service-neutral (`wrong_service`), the
  service's name being in the text.
- **The `connections` table does not list kinds.** It has no check on `kind` and none tying `person_id` to the code
  hosts: the registry is the one list, and a copy in the table would be a second a new service must migrate. The service writes only registered kinds, refuses to read a row whose kind is gone
  (`ConnectionsUnavailable`), and a secret is sealed bound to its household, kind and person, so a row moved under
  another does not open. Rejected: a migration that rewrites the check from the registry, which would run per release
  and still lag a deploy that adds a kind.
- Rejected: `Tools.catalogue(household)` and `Tools.call(household, ...)`. Every source and wrapper would change for
  the one source that needs a household, and the turn already composes per-household sources (`turn_tools.for_turn`).
- Rejected: a Home Assistant client made per turn. The house tools' catalogue is cached per Home (`HouseTools`), and
  rebuilding it costs a turn several round trips.
- Rejected: a key per person in OpenBao. Sure's data is the household's either way, and only the admin can write
  OpenBao, so no one could connect their own household.
- Rejected: Sure's MCP server for reads. `/mcp` refuses an API key and asks for OAuth with scope `read_write`, more
  than reading needs.
- Rejected: refusing private or internal base URLs. A household's own services resolve to private addresses on
  split-horizon DNS (a Sure instance on a public name can resolve to a home-network address from her pods), and the caller is a
  signed-in member of that household.
- **How many connections of a kind one owner may hold is the kind's `most`, one for every kind today.** No case
  needs more: each one looked at is another kind (Gmail beside Proton, GitHub beside a local GitLab), a
  resource inside one connection (a person's mailboxes or calendars), or a personal kind's one per person (a herdr
  per person's machine). A connection is addressed by its id and carries its owner's label (at most 40 characters,
  unique per owner and kind), the owner being the household or, for a personal kind, the person. Adding past `most`
  is 409 `too_many` and a taken label 409 `label_taken`. A second account of one kind is that kind's `most`
  raised and its tools asking which one by label; storage, routes, the room and the service need no change.

- **A code host is a person's own connection, not the household's.** `gitlab` and `github` rows carry the person
  (`connections.person_id`, set for those kinds), so a household holds one of each per person,
  and a person lists, opens and removes only theirs (the service takes the person and shows a connection only to its
  owner; their secret is sealed bound to them as well). What she reads is what that person's token reads, as the herdr
  bridge will be per person. The token is a personal access token the person makes: GitLab `read_api` and
  `read_repository`, GitHub fine-grained with read-only Contents and Metadata. Rejected: one app token over all of
  one person's projects, which would show their repositories to whoever in the household asks.
- **She reads a code host through a neutral port**, `ashley.codehost.host.CodeHost` over `Project`, `Entry` and file
  bytes, with an adapter per forge (`ashley.codehost.gitlab.GitLabHost`, `ashley.codehost.github.GitHubHost`); swapping
  or adding a forge changes an adapter only. The port has no call that writes, so no adapter can. Her tools
  (`ashley.tools.code_host.CodeHostTools`: `git_projects`, `git_tree`, `git_read_file`, and on a bench
  `bench_add_from_git`) are offered only where the reply reaches the speaker alone and only to a person who connected a
  host; a file or a whole snapshot (a zip) reaches a bench as her file piece. Sizes and counts are data
  (`app/ashley/codehost/codehost.json`); logs carry forge, call, project, status and byte counts, never a token, a path
  inside a project or content. What names a project, path or ref is checked structurally before any URL is built
  (`ashley.codehost.addressing`): a GitLab numeric id or `group/.../name`, a GitHub `owner/repo`, no dot, empty or
  hidden-separator segment, each segment percent-encoded, so a request stays under the forge's API prefix; the tools
  refuse a bad `project` as a tool error and the adapters refuse it again (`not_found`, logged `codehost.refused`).
  A GitHub directory read as a file, and a `host` the person has not connected, are failures, not content or an
  empty list.
- **A cut is always said, and a long file is read in pages.** The tool loop never drops the end of a result silently:
  the model reads a leading marker with the characters shown and the total (`ashley.tools.cut`), because a cut
  mid-JSON loses any flag at the end and "it is not in the file" is then a false answer. `git_read_file` takes a
  `start` and returns `total_chars` and `next_start` (null at the end); each page is the most text whose whole result
  fits the smallest `max_tool_result_chars` of any kind (it is offered in voice commands too), measured on the
  serialized result, so the loop never cuts it. `claude_read` fits the end of the screen the same way. Rejected: a fixed `read_chars` setting, which has to be kept under
  the cap by hand; wrapping a cut result in JSON, which escapes the head
  and wastes the budget.

## Her money is read through a neutral ledger

Her money tools and the deposit sense read `ashley.ledger.ledger.Ledger`, never Sure: neutral records (`Account`,
`Category`, `NetWorth`, `Entry`, `ashley.ledger.model`) whose fields are documented in the ledger's terms, and a
`TransactionQuery` she fills (dates, account, category, words, which way, page). Sure is the first adapter,
`ashley.sure.ledger.SureLedger`, the only code that reads Sure's field names; a second app is a second adapter
registered in `ashley.wiring`, with no tool or rule rewritten. The household's ledger is its Sure connection until a
second kind exists; the adapter finds it, so a caller passes a household id.

- **One write: a transaction's category** (`Ledger.categorise`: one of the household's categories for a few
  transactions, each one's outcome `set`, `not_found` or `rejected`; `UnknownCategory` and nothing changed for a
  category that is not the household's). Sure's adapter checks the category (`GET /api/v1/categories/:id`) and puts
  each transaction (`PUT /api/v1/transactions/:id` with only `category_id`, which Sure then locks against its rules and
  syncs); Sure has no bulk update in its API. Its key must have Sure's write scope; a read-only key is `refused`.
- **Categorising goes through the gate every change uses, with no gate of its own.** `money_categorise` is a change
  (`reads` false), offered only where the money tools are, so only for a named person of the household with the reply
  reaching them alone, which is what `ConnectionResources.permits` asks to change a household connection's resource; a
  reads-only turn is not offered it. Its tier is `judged` (`decisions.md`, "A turn that has read outside words asks
  before it does anything consequential the person did not ask for"): it changes records the household's budgets and
  reports rest on, and a turn that read the transactions has read payee text written outside, so a categorisation the
  person's own words do not ask for is held for their OK and agreed with `carry_out` or the Agree tap. Rejected:
  `runs`, as mail labels are, since a stranger's memo could recategorise the books in bulk; a confirm tool of its own,
  which would duplicate the held proposal.
- **`Entry` is not `criteria.record.Transaction`.** A tool shows a row the criteria cannot judge (no id, no amount, an
  undated one), so the ledger's record keeps every field optional the way the backend does, and the sense derives the
  judged record from it (`ashley.senses.ledger_transactions.deposit_from`). Rejected: one record for both, which would
  make `id` and `day` optional for every predicate.
- **Failures are `LedgerFailed(reason)`** (`refused`, `unreachable`, `unrecognised`), `LedgerUnavailable` when the
  household's link cannot be read, `NotConnected` when it has none. The tools' error texts still say Sure (and
  `not_sure` for `unrecognised`), since the model is told the source is Sure; they change with the first second backend.
- Rejected: an adapter per tool. The records are the contract, and the tools plus the sense share one adapter.

## A model provider's key is a connection

A deployment's keys for Anthropic, OpenAI, Gemini and ElevenLabs are connections, so whoever runs the published image
adds or rotates one in the connections room, sealed like any other connection's secret, with no redeploy. It is an
instance of Connections, not a new store: each provider is a kind (`ashley.inference.kinds`) on a new port,
`inference`, checked by one authenticated read with the key before it is stored (the models list; ElevenLabs'
subscription, the read the Usage room already makes), and the router opens the port, never a kind.

- **The keys are the deployment's, held by its first household.** Inference is one service for every household and
  a call reaches a household only through the conversation it serves, and many calls serve none (memory writes,
  judges), so its keys cannot be per household. A kind marked `deployment` (`ConnectionKind.deployment`) is offered to
  `FIRST_HOUSEHOLD` alone, the household the env describes, as the Home Assistant seed already treats it; any other
  household is not offered the provider kinds, and adding one is 404 as for a kind nothing registered. Only an admin
  of the first household may add, replace or remove a key ("An admin changes what the deployment shares"); any other
  person of it sees the keys listed and is offered none of the provider kinds, and a change is 403 `admin_only`.
- **A row wins over the env.** The key in force for a provider is the first household's row of its kind when one
  exists, else the env's (`ANTHROPIC_API_KEY` and the rest), else none (`ashley.inference.provider_keys`). So a key
  rotated in the room is used and a changed env key is ignored while the row stands; removing the row brings the
  env's key back, and the next pod start seeds it again. To stop a provider whose key is in the env, remove it from
  the env too. Without `CONNECTIONS_KEY` the env's keys are used as before.
- **The env's keys seed the first rows** at each pod's start (`ashley.inference.key_seed`, beside the Home Assistant
  seed in `wiring.warmups`), never over a row. Every pod on both sites seeds at once, and that is safe with no lease:
  `Connections.seed` is one `INSERT ... WHERE NOT EXISTS ... ON CONFLICT DO NOTHING` against the unique index on
  household, kind, owner and label, so one pod writes the row and the rest see `kept`. A seed that fails (the database
  away during a rollout) changes nothing a call sees, since the env's key is in force while there is no row.
- **Each pod keeps a cache, not state** (`ashley.inference.keyed_providers.KeyedProviders`): the providers built from
  the keys in force, read again by the first call once the last read is 30 seconds old (`REFRESH_S`). A key added,
  rotated or removed on any pod reaches every pod's calls on both sites within that bound, with no restart and no
  message between pods. A provider is built again only when its key changed, and a rotated provider stops resting, so
  a spent key replaced in the room is tried on the next call. A read that fails keeps what was wired and is tried again
  after the same bound; before the first read succeeds the env's keys are wired, so a pod serves while the database is
  away. A replaced build's clients are closed at shutdown, not at the swap, since a call in flight may still use them.
- **Routes are checked against every provider a key could turn on**, built once with a placeholder key that is never
  sent, so a route's parameters fail at start even for a provider whose key arrives later from the room.
- **Any OpenAI-compatible provider is one kind, many per deployment** (`ashley.inference.compatible`): OpenRouter,
  Groq, Together, Mistral, DeepSeek, or the operator's own Ollama or vLLM, each a name, a base URL and a key, served by
  `OpenAICompatibleProvider` with no wrapper library. It is a `deployment` kind like the keyed ones, so the first
  household holds it and only its admins add, replace or remove one. Its label is the provider name routes use, so it
  is an identifier (`[a-z0-9][a-z0-9_-]{0,39}`) and never a name `providers.json` has; any other is 422 `bad_label`, on a
  rename too. Its address may be http, for a server on the operator's own network. The check is `GET <base>/models`.
  The keys cache builds one provider per connection, by label, so a connection added, replaced, renamed or removed
  reaches every pod within the same 30 seconds. Unlike other kinds' labels, this one is logged, as each call's provider.
- **Its calls are priced as the catalogue provider a person picked** (`connections.catalogue_provider`): adding one in
  the room is a pick over the model catalogue's providers that list a base URL (the `api` prefills the address) or a
  custom address, whose calls are unpriced, never $0 and never priced by the label.
- **`LOCAL_LLM_URL` and `LOCAL_LLM_API_KEY` seed the connection labelled `local`** at each pod's start
  (`ashley.inference.key_seed`), never over a row of that label, with no catalogue provider; the row then wins. Until
  there is one (or with no `CONNECTIONS_KEY`) the env's server answers as `local`, as before.
- Rejected: reading the catalogue provider from the base URL. The address is a proxy for the pick, and a regional or
  proxied endpoint of a listed provider would go unpriced or be priced as another.
- Rejected: routes naming a connection by its id. `routes.json` and `ROUTES_FILE` are written before any row exists;
  the label is the name both sides can know.
- **An address with no key is still a connection**: Wyoming speech-to-text (`ashley.inference.wyoming_kind`, an
  `inference` kind) and SearXNG (`ashley.tools.search_connection`, a `search` kind) are `deployment` kinds held by the
  first household, one each, at an address on the operator's own network. A connection stores a secret, so each stores
  placeholder text (`address_seed.NO_SECRET`) and its room form says any text will do, as the local OpenAI-compatible
  server's does. Each is checked by one read before it is stored: Wyoming answers `describe` with `info`, SearXNG answers
  a JSON search. `WYOMING_STT_URL` and `SEARXNG_URL` seed the rows at each pod's start (`ashley.connections.address_seed`),
  never over a row, and the row then wins; with no row the env's address answers, as the provider keys' do.
- **Wyoming is read as a provider is, SearXNG on each use.** Wyoming's transcriber is built from the address by the keys
  cache (`KeyedProviders`, `AddressedProvider`), so a row changed in the room reaches every pod within its 30 seconds; the
  media pod's address and the web search read the row on each use (`ashley.connections.address_in_force`), so a change is
  seen by the next transcription or search, and with no address the search is not offered.
- **Her Discord bot's token is a connection** (`ashley.channels.discord.token_kind`, a `chat` kind): a `deployment` kind
  held by the first household at Discord's one address, checked by one read of the bot's own user. `DISCORD_BOT_TOKEN`
  seeds the row at each pod's start (`ashley.channels.discord.token_seed`), never over a row, and the row then wins;
  with no row the env's token answers. The session follows a changed token (`channel-adapters.md`, "Discord is a bot,
  its Gateway a singleton").
- **Her file storage is a connection** (`ashley.files.store_kind`, a `files` kind): a `deployment` kind held by the first
  household, one S3-compatible bucket reached at one endpoint per site. Its address is the endpoints, comma-separated
  this site's first (`ConnectionKind.addresses`), and its one secret is the bucket and both keys as a JSON object, since a
  connection seals a single secret. It is checked by one signed listing at every endpoint, so a typo in a site's address
  is caught when it is saved. `FILES_ENDPOINTS`, `FILES_BUCKET`, `FILES_ACCESS_KEY` and `FILES_SECRET_KEY` seed the row at
  each pod's start (`ashley.files.store_seed`), never over a row, and the row then wins; with no row the env's store
  answers, and with neither every call is `StoreUnavailable` and the sweep and repair idle. The store is `ashley.files.connected_store.ConnectedStore`, a cache and not state: it reads the row again by the
  first call once the last read is `REFRESH_S` old, so a store added, replaced or removed in the room reaches every pod
  within that bound, and a read that fails keeps what was wired. It is registered whenever the env names a store or
  `CONNECTIONS_KEY` is set, and answers `ObjectStore.available()` with whether it holds a store now, which the bench
  file, look, media and printables tools ask before they are offered; the sweep and repair start with any real store
  and idle under their lease while none is held. Rejected: a connection per endpoint, which would make a person keep one bucket's keys in
  step across rows and leave "this site's first" to row order.
- **Her satellites' key is a connection** (`ashley.channels.voice.key_kind`, a `voice` kind): the Noise key a household's
  ESPHome devices share, held by the household at a fixed placeholder address and checked by its shape alone, since
  nothing answers for it. Household settings (`connection_settings`) are lists of ids on an existing connection and hold
  no secret, so the key is sealed like any credential. `ESPHOME_NOISE_PSK` seeds the first household's row at each pod's
  start (`ashley.channels.voice.key_seed`), never over a row; a satellite is reached with its own household's key, and the
  env's answers for the first household alone (`ashley.channels.voice.key_in_force`).
- Rejected: a store of its own for provider keys, which would repeat the sealing, the room and the check that
  Connections already has.
- Rejected: one `inference_provider` kind with the provider named in the label or address. The provider would then be
  read from text; as kinds, each provider's address, check and refusal words are a Type Object's fields.
- Rejected: per-household keys now. Every inference caller would have to carry a household, and a household that
  added a key would still be answered for calls made on behalf of no household (memory writes, judges).
- Rejected: telling every pod of a change over LISTEN/NOTIFY. A 30 second bound needs no channel, and a missed
  message would leave a pod on an old key with nothing to correct it; a bounded refetch corrects itself.
- Rejected: holding the lease to seed. The unique index already makes the write once, and a seed under the lease would
  wait for a leader that a single-machine deployment has only by advisory lock.
