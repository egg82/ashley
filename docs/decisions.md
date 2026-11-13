# Decisions

**North star: one assistant for the household that is always there.** She keeps working when a site, an ISP or
a cluster goes down, and never becomes two assistants with two memories.

A decision says how a part of her works now and why, with what was rejected. They live in `docs/decisions/`, one file
per system or group of systems (the systems are `systems.md`). Read this index, then the files for the systems a change
touches; `principles.md` and `two-sites.md` bind every change. Code and docs cite a decision by its title, quoted after a
mention of `decisions.md`: the title is an entry below, or a `###` heading or bold lead inside one of the files, found with
`grep -rn "Title" docs/decisions/`. `app/tests/test_decision_citations.py` fails when a cited title resolves to nothing.

## Principles

- [Words used here](decisions/principles.md): a site, the active site and a singleton.
- [What she's for](decisions/principles.md): useful like a real assistant, fun and cool like Jarvis; the gaps that matter most are initiative and conversation.
- [Per person by default](decisions/principles.md): what she can reach, what she knows and how she behaves is set per person, never written for one named owner.
- [Python backend, TypeScript web app: a sibling app's stack](decisions/principles.md): FastAPI, Pydantic, psycopg 3, Alembic and the `anthropic` SDK behind a TypeScript web app built with esbuild.
- [Env var, file, connection or setting](decisions/principles.md): a value lives in the tier its changer and its failure name, not where it was easiest to read.

## Two sites and failover

- [Active/standby with one writer, not active/active](decisions/two-sites.md): every pod in both clusters serves requests; there is exactly one writable database and one site running singletons.
- [Work in flight survives its pod](decisions/two-sites.md): a rollout, a failover or a move between sites carries on whatever she was in the middle of, and nobody notices.
- [Failover is automatic, refereed by a 3-site etcd](decisions/two-sites.md): no MR, kubectl or other human step at failover time; a third site's vote breaks the tie.
- [One Postgres, managed by Patroni, with the house's site preferred](decisions/two-sites.md): Patroni on each cluster elects the primary through the same etcd; asynchronous streaming replication between sites.
- [Singletons hold an etcd lease](decisions/two-sites.md): a singleton runs only while its process holds a lease in the same etcd.

## Channels and conversations

- [A conversation is one thing; channels carry it, several at once](decisions/channels.md): a conversation has participants, history and a state, and belongs to no channel.
- [Every channel shares one turn loop; adapters live at the edge](decisions/channels.md): an adapter turns what arrived into an `Inbound` and delivers the `Outbound` that `channels.respond` returns.
- [Most channels are shared devices, so who is talking is its own answer](decisions/channels.md): every request carries the channel's audience and the speaker, which on a shared device starts out unknown.
- [A person reads back their earlier conversations](decisions/channels.md): a closed conversation is not gone; a person reads the ones they took part in, on any channel.
- [A composer never cuts what was typed](decisions/channels.md): the web composers grow to about eight lines, and the client does not enforce the length limit by truncating.

## Channel adapters

- [Web push](decisions/channel-adapters.md): web push is a channel like any other, its thread `push:<person id>`, sent by one singleton under the lease `push`.
- [The hallway tablet is her page, paired as a device](decisions/channel-adapters.md): `/kiosk` shows only what anyone in the hallway may see, and does what anyone there may do.
- [Discord is a bot, its Gateway a singleton](decisions/channel-adapters.md): she is one Discord bot; a DM is its account's own channel, and a household's server is a device.
- [She runs her own voice pipeline](decisions/channel-adapters.md): satellites talk to her directly over the ESPHome native API; STT and TTS sit behind the inference interface.
- [A voice names the speaker as a hint, never as a credential](decisions/channel-adapters.md): each wake's voiceprint is compared with the household's enrolled prints, and a close enough match names the speaker.

## Live and the person's page

- [Open screens learn what changed through Live](decisions/live-and-pages.md): every open screen holds one Server-Sent Events stream, fed by Postgres LISTEN/NOTIFY.
- [She moves the person's page herself](decisions/live-and-pages.md): where the channel is the speaker's own page, she can take it to another room rather than asking the person to go.
- [Her reply follows the page](decisions/live-and-pages.md): a turn that takes the speaker's page to a bench is that bench's turn from the next model step on, and her reply is said there.

## People and sign-in

- [People sign in through OIDC](decisions/people.md): anything of hers with a login uses OIDC with the household's SSO, each account mapped explicitly to a person.
- [An admin changes what the deployment shares](decisions/people.md): state that is the whole deployment's, such as a model provider's key, only an admin changes; `ADMIN_GROUP` chooses who is one.
- [A person links their own Discord account](decisions/people.md): a signed-in person links Discord in the connections room through Discord's OAuth2, scope `identify` only.

## Memory

- [Every fact has an owner, a household and one of four visibilities](decisions/memory.md): each fact carries `household_id`, an owner and a visibility.
- [What she knows lives where the thing that would make it wrong lives](decisions/memory.md): what would make a thing stale decides its home, where she meets it on the way to using it.
- [Memory is atomic facts in Postgres that are superseded, never edited](decisions/memory.md): one row per fact, current while `valid_to` is null; a correction closes the old row and points it at the new one.
- [People see, correct and forget what she knows of them](decisions/memory.md): a signed-in person reaches the facts that concern them through `/api/memory/facts`.

## Connections and the ledger

- [A household connects its own services](decisions/connections.md): a household's links to services outside her are Connections, each a kind, a label, a base URL and a secret sealed at rest.
- [Her money is read through a neutral ledger](decisions/connections.md): her money tools and the deposit sense read `Ledger`'s neutral records, never Sure; Sure is the first adapter. Her one write, a transaction's category, is a judged change through the gate every change uses.
- [A model provider's key is a connection](decisions/connections.md): a deployment's model provider keys are connections, added or rotated in the connections room with no redeploy.

## Mail

- [Her mail is a port with two adapters, and Proton's runs as a leased Bridge](decisions/mail.md): Gmail over its API, and Proton over a Bridge she runs as a leased singleton; she reads, searches, drafts, labels, sends and sorts.

## Homes

- [Her house is general: Home Assistant's REST and WebSocket APIs behind a port](decisions/homes.md): what she sees and does in the house is a `House` port over neutral records.
- [Home Assistant is a tool, not the host](decisions/homes.md): she is her own service; HA is one of the systems she calls, as a sense, a tool and a channel.

## Tools

- [Search: SearXNG for the web, Photon for places](decisions/tools.md): Tools is a Composite over its sources; she never reads search results, a sub-agent does, called as one tool, `look_up`.
- [For code and the cluster she is a front for Claude Code](decisions/tools.md): she reaches the talking person's own Claude Code sessions through a bridge that narrows herdr.

## Outside words

- [A turn that has read outside words asks before it does anything consequential the person did not ask for](decisions/outside-words.md): a turn that has read text written outside the household is tainted, and each change it would make goes by its tier.
- [A tap agrees to what was held](decisions/outside-words.md): a held receipt and its push notification offer Agree, a person turn carrying `agree: <proposal id>`.

## Workshop

- [The workshop: benches of pieces, changed only by Commands](decisions/workshop.md): a bench is where she and a person make something together, and only Commands change it.
- [She reacts to a person's bench change](decisions/workshop.md): when a person's commands on a bench stop for a pause, she gets one turn there and may say something or stay silent.
- [Her bench's text is checked for what editing left stale](decisions/workshop.md): her notes rot as she edits them; the guidance says to state a thing once, and a check flags passages for her to verify.

## Bench files

- [Benches carry files, photographs and 3D](decisions/bench-files.md): uploads and downloads are large pieces in the object store; 3D is her work in code, seen by the person.

## Skills and taste

- [Her skills are method documents she edits](decisions/skills.md): a skill is data, a method document per kind of work, and kinds of work are hers.
- [A household may override her taste, never her contract](decisions/skills.md): units and language follow the household by field; the persona's taste is the household's, its contract ships.

## Code runs, bench jobs and errands

- [She runs a script in a gVisor pod of its own](decisions/runs-and-jobs.md): `run_code` runs a short script once, on-prem, each run its own pod, and gives her what it printed.
- [She hands a bench job to workers and stays with the person](decisions/runs-and-jobs.md): a job of many runs or a long loop goes to a worker with `bench_hand_off`, and she goes on talking.
- [What she could not do for want of a source, she does once it answers, and says so next time](decisions/runs-and-jobs.md): an ask she could not carry out because a tool source was out of reach is recorded as owed, done later, and told.

## Senses, reminders and initiative

- [Whether she speaks unprompted is decided in code](decisions/senses.md): on a wake rule that greets, code scores the facts of the moment gathered before the turn, a roll seeded from the wake's id picks full, short or silent, and her `says` can still decline; any other wake goes out on `says` alone; an aside (a remark on a Discord message that does not address her) is a seeded roll, a cap counted from stored remarks, focus and night refusals, and a refusal of any line she already sent, all in code.
- [Home Assistant wakes her; she decides](decisions/senses.md): HA detects, she decides; an automation's wake action carries structured data only.
- [Reminders are wakes she sets for herself](decisions/senses.md): a reminder is a row of the `wakes` queue, kind `reminder`, taken up by the same singleton.
- [Her proposals are one store](decisions/senses.md): a proposal is a pending OK for a typed payload, taken only from a later person turn of the conversation it was made in.
- [Reminders she shapes](decisions/senses.md): a reminder is a small set of fields she fills per ask, so no repeat, end or action is a special case.
- [A reminder can wait on a deposit](decisions/senses.md): a reminder gains a trigger of kind `event` beside its time, the event a deposit into the household's Sure.
- [Rules she writes are composed from general predicates](decisions/senses.md): a money rule adds typed predicates she composes per ask, so the classification stays hers.

## Watches

- [Watches wake her when what a read returns changes, until a condition or a time](decisions/watches.md): a watch is a read she repeats on a schedule with no model in the check; when what it returns changes, she is woken.

## Inference

- [Inference sits behind an interface](decisions/inference.md): anything that could move to a local model sits behind an interface; any reachable model can answer, and which one is data.
- [A household chooses the model for its chat](decisions/inference.md): a household picks the model for its chat-facing tasks in the Usage room, a third layer over the routes.
