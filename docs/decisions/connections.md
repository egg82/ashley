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
- **A connection is stored only after the service answers with it**: the kind's one authenticated read (Sure's
  accounts, Home Assistant's `GET /api/`, a code host's `GET /user`). A refusal says why (`bad_url`, `key_refused`,
  `unreachable`, `wrong_service`), in the kind's own words, and stores nothing. Sure's address is https; Home Assistant's may be http, since most are
  served on the household's own network with no certificate (`http://homeassistant.local:8123`, say). No redirect is
  followed, since one would carry the key wherever it points.
- **Her money tools are offered only where the reply reaches the speaker alone**
  (`ashley.channels.audience.owner_alone`): the channel names the speaker, its audience is `owner`, it is not shared,
  and no device's screen shows the thread. A person's web chat, their bench talk and their Discord DM qualify; a
  satellite, the hallway tablet and a household's Discord channel never do, voice match or not.
- **She only reads**, through the Ledger (below; Sure's REST API behind it) with `ashley.tools.money.MoneyTools`: accounts, transactions by date,
  account, category, words and type, categories, and net worth. Each answer is compact, capped
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

- **Reads only.** The interface has no write, so no adapter can write; categorising is a separate piece (`open-work.md`).
- **`Entry` is not `criteria.record.Transaction`.** A tool shows a row the criteria cannot judge (no id, no amount, an
  undated one), so the ledger's record keeps every field optional the way the backend does, and the sense derives the
  judged record from it (`ashley.senses.ledger_transactions.deposit_from`). Rejected: one record for both, which would
  make `id` and `day` optional for every predicate.
- **Failures are `LedgerFailed(reason)`** (`refused`, `unreachable`, `unrecognised`), `LedgerUnavailable` when the
  household's link cannot be read, `NotConnected` when it has none. The tools' error texts still say Sure (and
  `not_sure` for `unrecognised`), since the model is told the source is Sure; they change with the first second backend.
- Rejected: an adapter per tool. The records are the contract, and four tools plus the sense share one reader.

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
- **Not keys, so not connections:** a local OpenAI-compatible server (`LOCAL_LLM_URL`) and Wyoming speech-to-text
  (`WYOMING_STT_URL`) stay settings. Each is an address on the operator's own network, usually with no key, while a
  pasted connection is a secret its service checks; and they run beside the pods, where the env is set anyway.
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
