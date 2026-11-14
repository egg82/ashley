# Homes

How she reaches a household's Home Assistant.

## Her house is general: Home Assistant's REST and WebSocket APIs behind a port

She has the household's Home Assistant admin token and may see and change anything in it. What she
sees and does is a `House` (`ashley.home_assistant.house`): neutral records (things with a state, devices, entities,
areas, floors, labels, integrations, configs, actions) and the operations over them, implemented for Home Assistant by
`ha_house.HaHouse` over its REST API (states, history, logbook, actions, automation and script configs, diagnostics) and its
WebSocket API (the registries, helpers, config entries), one command per connection. Swapping the house changes the adapter
alone. What each API offers in HA 2026.10.4 (read from a live house's `/api/config`; each row checked read-only there or on a scratch container):

| For | REST | WebSocket | MCP (`mcp_server`) |
|---|---|---|---|
| States | `GET /api/states` | `get_states` | `GetLiveContext`, exposed entities, no ids |
| History, logbook | `/api/history/period/<ts>`, `/api/logbook/<ts>` | `history/history_during_period`, `logbook/get_events` | none |
| Device, entity, area, floor, label registries | none | `config/<x>_registry/list`, `create`, `update`, `delete`; `get_entries` (aliases) | none |
| Integrations (config entries) | `/api/config/config_entries/entry` | `config_entries/get` | none |
| Automation and script config | `/api/config/automation/config/<id>`, `.../script/...` (GET, POST, DELETE) | none | none |
| Helpers | none | `<input_boolean, input_number, ..., timer>/list`, `create`, `update`, `delete` | none |
| Calling actions | `POST /api/services/<domain>/<name>`, `?return_response` | `call_service`, `get_services` | Assist intents, scripts and lists exposed to Assist |
| Name resolution | `POST /api/conversation/process` | `conversation/process` | the intents, exposed entities only |
| A device's details (ESPHome) | `/api/diagnostics/config_entry/<id>` | device registry: model, firmware | none |

URLs: developers.home-assistant.io/docs/api/rest, /docs/api/websocket, /docs/entity_registry_index, /docs/device_registry_index,
/docs/area_registry_index, /docs/config_entries_index, /docs/intent_index, /docs/core/integration_diagnostics, and
home-assistant.io/integrations/mcp_server and /integrations/esphome. Aliases are written `[None, ...]`: the null is
the entity's own name, and plain strings drop it from Assist.

- **Her tools are general primitives, not HA's tools.** `house_state` (the live map of the devices the household lists
  for her by name, `all` for everything), `house_find` (devices, entities, areas, floors, labels, integrations,
  automations, scripts, helpers, actions and their fields, and what an integration reports about itself, by kind),
  `house_history` (a thing's changes, or the logbook), `house_ask` (an action that only returns data) and `house_do` (any
  other action). An action's fields are a JSON object as text (`data`), because Gemini, her chat model, fills an object whose fields the
  schema does not name with `{}`. Things are named by exact id, or by `name`, `area` and `domain` resolved in code against the house's own
  names, aliases and areas (`house_targets.resolve`): an exact name wins, then the one the household lists, and a name
  fitting several acts on none and says which. Caps are data (`house_look.json`); every list in an answer is whole or says
  it is not (`complete`, `narrow_by`).
- **Configuration she changes on her own; what cannot be undone needs the person's OK.** `house_change` writes automations,
  scripts and helpers, creates areas, floors and labels, and sets entities' and devices' fields, offered where the speaker is
  known. Which operations need an OK is data (`irreversible.json`: patterns over operation keys such as `delete:*`,
  `remove:*`, `perform:homeassistant.restart`), judged on the change's key and nowhere else. Such a change is not made: it is
  proposed (`senses.proposals.Proposals`, "Her proposals are one store"), she tells the person what it would do, and
  `house_confirm` is offered only in a later person turn of the conversation, where it carries out the stored change and nothing
  else. Proposing and confirming need the reply to reach the speaker alone. This is the money reminder's proposal pattern
  (`arm_money_reminder`), one store with a house-change payload. `house_do` refuses an irreversible action outright.
- **Her instructions are her own guidance over the devices the household lists**, not HA's `Assist` prompt: `home_assistant.md`,
  then one line per area of the entities exposed to Assist (`house_roster.roster`, `House.states` entries that are `featured`),
  fetched when the catalogue is and kept for `catalogue_ttl_s`, then one line of the house's devices (name and model of the
  registry's devices that have a maker or model, as many as `devices_chars` holds and a count of the rest). The exposure is
  the household's curation of what she is told up front and the tie-break between equal names; it does not limit what she
  can reach. The devices line is what makes a question about one ("can the Atom Echos also be Bluetooth proxies?") a lookup:
  without it she answers from what she knows of the product and calls no tool; with it she reads the device's record and
  its integration's diagnostics.
- **Some of the house's actions she is never offered, as data** (`home_assistant.json`, actions as `domain.name`):
  `assist_satellite.announce` is excluded because her route to the rooms is the outbox. The scripts that only look something up
  are the household's `reads` setting ("A connection has settings its person sets"); an action the house says only returns data is a read too. The kiosk's controls run `house_do`
  by code and name none of the excluded.
- **She reads the house's state through `house_state`, answered in code** (`house_query` narrows like a map, `house_render` caps it): one
  `GET /api/states` plus the registries per call, nothing cached on a pod. Every list holds every child; an answer over
  `house_state.json`'s cap shows names or counts instead, with `complete` false and `narrow_by`. `name` matches the entities'
  own fields, every word; `matched` 0 is final.
- **Structured reads that code acts on go through HA's REST API**, not a tool: presence decides who is talking, so no
  model sits between the state and the decision. The event stream will use HA's websocket. The Workshop's install goes
  through the House port like her tools: `configs("automation")` names each automation's thing, whether it is on and
  when it last ran (one written in YAML has no config id), `write_config` writes it, `shown_as` waits for the house to
  show it (`house.json`'s `entity_tries` and `entity_wait_s`) and `set_enabled` turns it on or off.
- **Rejected: HA's MCP server as a second adapter, and as the first.** Measured on a scratch HA 2026.10.4 with aliases and
  areas, twelve asks (ten everyday, two names the house lacks): MCP's intents resolved 10, the registry-backed resolver 12; the two MCP misses were area
  aliases ("the lounge lights", "the main bath light"). Reads are the same matcher either way. MCP also reaches only what is
  exposed to Assist, and gives no registries, history, logbook, config or device details, so keeping it would be a second
  implementation of the same questions that drifts. `HomeAssistantTools`, `McpClient` and the `GetLiveContext` parser are gone.
  House eval, two runs a case on a scratch house carrying the eval's names: MCP 22/22; the port 22/22, and 21/22 on a
  rerun (one `unknown-sauna` run asked `house_do`); step-limit hits 0 and 1. Her first step reads about 1,200 more input
  tokens (five house tools, `house_change`, the devices line).
- **Rejected: a sub-agent in front of HA** (one `house` tool, Haiku over HA's tools). It cut her main call about 3x
  (11.6k to 4.0k tokens a step) but made five read-only asks slower (sum about 49 s before, 75 to 87 s after): two
  model steps per house call on HA's guidance, and a name that matched nothing came back as prose she re-asked in
  new words, up to 11 steps in one turn.
- **Rejected: vector search or tool search over HA's tools.** The definitions cost little (about 70 ms of first
  token); the results were the cost.
- **Music on the house's speakers is the house primitives, not a music port.** Play, pause, skip and volume are
  `media_player` actions through `house_do` (`tiers.json` runs the `media_player` domain without a judge), and what a
  speaker is playing is its attributes in `house_state` (`media_title`, `media_artist`, `volume_level`), whose result
  is outside words since a track's title is whoever published it (`house_state.json`'s `outside_domains`). A port with
  a plain `media_player` adapter would be a second `house_do`. Search and play from a service needs a source the house
  holds: Music Assistant (`music_assistant.search` returns data, so `house_ask` reads it as outside; `play_media` is a
  `house_do`), or a service's own connection behind a port once a service it lacks is wanted. The deployment's house,
  read in November 2026, ran no Music Assistant and no music service; its speakers were Cast, most with no area, so
  "in the kitchen" resolves only once a person gives them areas in Home Assistant.

## Home Assistant is a tool, not the host

Ashley is her own service; HA is one of the systems she calls. HA's conversation-agent model can't carry
long-term memory, initiative or tools outside the house. HA has three roles: a **sense** (state changes), a
**tool** (actuating devices) and a **channel** (its notify and media players out, perhaps Assist text in).
