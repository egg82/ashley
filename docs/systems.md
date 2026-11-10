# Systems

The inventory an agent checks before building something new (`CLAUDE.md`, the fit pass): what kind of thing is
this, and which row below already answers that question? Extend or combine that system; add a row only when none
fits, and say why in the open-work item's "Fits into:" line. Update this file in the same change that adds,
merges or retires a system.

## What counts as a system

A thing is a system only if all four hold:

1. **Many callers, across packages.** One caller is a function call.
2. **One question, behind a narrow interface.** If the interface keeps widening, it is two systems.
3. **A second implementation is plausible.** An A/B variant, a Null Object, a fast stand-in for tests.
4. **It owns a policy or state**, not a data shape.

## Infrastructure

### Failover referee

- **Owns (the question it answers):** Which site is active right now?
- **Where:**
  - etcd, its witness and PKI tools: `kubernetes:kustomization/etcd` (the cluster repo; shared with other apps)
- **Pattern:** 3-member Raft quorum across sites
- **Who asks, how:**
  - Patroni (primary election)
  - every singleton runs under `ashley.referee.lease.Lease` (`app/ashley/referee/`), only on the site whose Patroni
    member leads (`ashley.referee.active_site.ActiveSite`); what lives in one site's cluster, like the warm look pod,
    runs under `Lease.run_on_site`, held on each site at once
  - without etcd (one machine, or replicas sharing one Postgres) the `Lease` is
    `ashley.referee.postgres_lease.PostgresLease`, a Postgres session advisory lock per singleton, with no notion of a
    site; every singleton but fail-back runs under it
  - its first singleton, `ashley.referee.failback.FailBack`, reads and drives Patroni through
    `ashley.referee.patroni.Patroni`

### Live

- **Owns (the question it answers):** What should the open screens know changed, right now?
- **Where:**
  - `app/ashley/live/`
  - tunables are data, `app/ashley/live/live.json`
- **Pattern:**
  - Observer as a broadcast: service behind the locator, `ashley.live.live.Live`, Postgres implementation
    `ashley.live.postgres.PostgresLive` over LISTEN/NOTIFY (every pod reaches the one primary, so a NOTIFY from any pod
    reaches every pod; one listening connection per process, reopened after a failover), fanned out in-process to
    bounded per-screen queues by `ashley.live.fanout.Fanout`
  - who may be shown what is `ashley.live.events.shown_for`, and each screen, a person's (`ashley.live.events.Viewer`)
    or a device's (`ashley.live.events.DeviceViewer`), sees what `ashley.live.events.shown_to` allows
  - a Null Object that publishes nothing and refuses subscribers. Not the Outbox: nothing is claimed or kept, and a
    screen that missed something refetches
  - which people have a page open, across every pod of both sites, is `ashley.live.screens.Screens` (Postgres
    `ashley.live.postgres_screens.PostgresScreens`, table `live_screens`, a row per open stream refreshed at the
    heartbeat; a Null Object that raises): the fan-out above is per process and cannot say
- **Who asks, how:**
  - The turn loop publishes (`ashley.channels.live_turn.Showing`; a turn that ends with no reply after its request
    returned pending, `ashley.live.events.TurnFailed`), the Workshop a bench's change and her cue of a video piece's player (`ashley.live.events.BenchCued`, heard by the open
    screens only), her move of a person's
    page (`ashley.live.events.PageMoved`, from `ashley.tools.move_page.MovePageTools`, which each of their pages follows
    or offers to by `app/web/src/shell/her/moves.ts`), and the voice adapter her `listening` and `speaking`
    (`ashley.channels.voice.mark.Mark`; the end of playing is estimated, `ashley.channels.voice.config.Playback`)
  - people's screens subscribe through `GET /api/live` (`app/ashley/api/live.py`), the client's one owner of it being
    `app/web/src/session/live.ts`, and the kiosk through `GET /api/kiosk/live` (`app/ashley/api/kiosk.py`,
    `app/web/src/kiosk/live.ts`), both over `app/web/src/session/feed.ts`

## The assistant

### Channels

- **Owns (the question it answers):** What does she say to this message, and how does it reach them?
- **Where:**
  - `app/ashley/channels/`
  - limits are data, `app/ashley/channels/turns.json`, and a device's request rate
    `app/ashley/channels/device_rate.json`, counted in Postgres by `ashley.channels.devices.Devices.allow`
- **Pattern:**
  - One turn loop, `ashley.channels.respond.respond`, that every adapter calls with an `ashley.channels.model.Inbound`
  - a read identical in name and arguments to one already made in the reply is not run again, until a change has run: its result points at the earlier call (`ashley.channels.tool_loop.answer`)
  - adapters at the edge (the first, `app/ashley/api/messages.py`)
  - devices sign in through `ashley.channels.devices.Devices` (Postgres implementation
    `ashley.channels.postgres_devices.PostgresDevices`, written by the admin CLI
    `app/ashley/channels/devices/__main__.py`; a Null Object that raises)
  - a device's screen and its touch controls are the device's screen bench in the Workshop (`ashley.workshop.workshop.Workshop.screen`
    and `apply_screen`; the buttons are the body of its `controls` piece, `ashley.workshop.screen_controls`); a device's
    `device_controls` rows (`ashley.channels.kiosk.device_controls.DeviceControls`, Postgres implementation
    `ashley.channels.kiosk.postgres_device_controls.PostgresDeviceControls`) hold its list only until its bench exists
  - the voice adapter `app/ashley/channels/voice/`, its satellites held by one singleton under `Lease`,
    `ashley.channels.voice.satellites.Satellites`, each wake carried by `ashley.channels.voice.run.Run`, replies played
    from short-lived clips (`ashley.channels.voice.clips.Clips`, Postgres implementation
    `ashley.channels.voice.postgres_clips.PostgresClips`, served by `app/ashley/api/voice_clips.py`)
  - each wake's voiceprint, made while transcription finishes, either enrols an armed device's person or is matched by
    `ashley.channels.voice.heard_as.match` against the household's prints (`ashley.channels.voice.voices.Voices`,
    Postgres implementation `ashley.channels.voice.postgres_voices.PostgresVoices`, armed and forgotten by the admin
    CLI; a Null Object that knows no voices), in the run's speaker step `ashley.channels.voice.identify.Identify`,
    naming the person as `ashley.channels.model.Inbound.heard_as` only when the policy decides, which
    `ashley.channels.speaker.who` weighs after the channel's own `speaker_id`
  - tunables are data, `app/ashley/channels/voice/voice.json`
  - the Discord adapter `app/ashley/channels/discord/`, its Gateway session held by one singleton under `Lease`,
    `ashley.channels.discord.bot.Bot`, behind the port `ashley.channels.discord.client.Discord` (the only code importing
    the library, `ashley.channels.discord.client.HikariDiscord`), each message turned into an `Inbound` by
    `ashley.channels.discord.route.route` and claimed once through `ashley.channels.discord.seen.Seen` (Postgres
    implementation `ashley.channels.discord.postgres_seen.PostgresSeen`; a claim is settled once the turn loop has the
    message, and catch-up hands in again a claim never settled, as the same person turn by
    `ashley.channels.model.Inbound.source`), each household's server being a device with a
    home channel (`ashley.channels.devices.Devices.discord_servers`), tunables
    `app/ashley/channels/discord/discord.json`
  - spoken replies pass the household's pronunciation words, read at render (`ashley.channels.render.render`) from
    `ashley.channels.lexicons.Lexicons` (Postgres implementation `ashley.channels.postgres_lexicons.PostgresLexicons`,
    a Null Object with none), edited by any of its people in the Devices room (`GET /api/lexicon`)
  - replies said outside the response to a message (the answer after "let me check", and later Initiative's) go through
    the outbox, `ashley.channels.outbox.Outbox` (Postgres implementation
    `ashley.channels.postgres_outbox.PostgresOutbox`, a Null Object that raises; tunables
    `app/ashley/channels/outbox.json`), added from any pod and taken by the singleton holding the thread's channel:
    `ashley.channels.voice.later.drain` in the satellites singleton, announced on the satellite through
    `ashley.channels.voice.connection.Announcer`, and `ashley.channels.discord.later.drain` in the Discord one, and
    `ashley.channels.push.later.drain`, web push (its notification carries an Agree action for a reply that shows a held
    proposal, `ashley.channels.model.Outbound.agree`), a singleton of its own under `Lease` that sends a person's
    `push:<person id>` thread to every browser they subscribed (`ashley.channels.push.subscriptions.Subscriptions`,
    Postgres implementation `ashley.channels.push.postgres_subscriptions.PostgresSubscriptions`, wired only with her
    VAPID identity, `ashley.channels.push.config.vapid`, else a Null Object that raises; written by a person's push
    routes, `app/ashley/api/push.py`), through the port `ashley.channels.push.sender.Sender` (the only code importing
    pywebpush, `ashley.channels.push.sender.WebPushSender`; tunables `app/ashley/channels/push/push.json`), and each
    fired reminder from her stored answer, its delivery recorded on the reminder (`ashley.channels.push.reminders`)
  - a spoken reply's `text` reaches that thread when the model sets `to_phone` on `ashley.inference.reply.Reply` and the
    turn offered the speaker's phone (`ashley.channels.to_phone.reachable`), queued with her turn
    (`ashley.channels.to_phone.copy`)
  - a reply's tool loop, `ashley.channels.tool_loop.answer`, does not run a read again that it made earlier in the
    reply unless a change (`ashley.inference.model.ToolSpec.reads` false) has run since, and logs it `tools.repeat`
  - a result longer than its kind's `max_tool_result_chars` is cut with a leading marker saying how much of how much
    follows (`ashley.tools.cut.visible`), logged `tools.cut`; a tool that pages fits each page under the smallest cap
    of any kind (`ashley.tools.cut.fit`), so the loop never cuts it
  - on a turn that can hold, every tool offered takes her `aside` (`ashley.channels.aside.offered`), stripped before
    the call reaches its tool (`ashley.channels.aside.Stripped`)
  - past its kind's `hold_after_s` with no answer, even mid-round, the tool loop holds on her latest aside
    (`ashley.channels.tool_loop.Held`, `by` `aside_budget`), resumed by `ashley.channels.tool_loop.resume`
  - past its kind's `deadline_s`, the tool loop's next step must answer, logged `respond.deadline`
  - on a kind whose limits say `escalates`, a turn that reaches its round limit or deadline with no answer, or whose
    reply (`ashley.inference.reply.Reply`) sets `escalate`, goes on once on the stronger route from its entries
    (`ashley.channels.escalation.Escalation`, built by `ashley.channels.escalation.of`; the loop stops with
    `ashley.channels.escalation.Escalating` and `ashley.channels.tool_loop` holds its line, `Held` by `escalate`), recorded
    in the checkpoint (`ashley.channels.checkpoint.Checkpoint.escalated`, `ashley.channels.steps.Steps.escalate`) and
    logged `respond.escalated`
  - a step whose reply has nothing for the medium to deliver is asked again once as a wrap-up under tool choice `none` (the note every closing step after a lookup carries), then answers with the fixed line
    (`ashley.channels.unsaid.LINE`), logged `respond.reply_empty`
  - a turn that ends after its first line went out without its answer never ends silent: a refusal is wrapped up on a
    route of another provider (`ashley.channels.refused.wrapped`, task `wrap_up`), a model that cannot be reached is
    told once and the work kept for the sweep after a backoff (`ashley.channels.settled.settle`,
    `ashley.channels.inflight_config.Config.unavailable_retry_s`, `ashley.conversations.inflight.InFlight.defer`), and
    each ending is logged `respond.ended` (`ashley.channels.ending.record`)
  - the web chat adapter `app/ashley/api/chat.py`, a signed-in person's own thread, whose held answers are only stored
    (`ashley.channels.model.Inbound.later_by`), each open page reading the conversation back when Live says the thread
    got a turn, and earlier conversations of any channel read back through `app/ashley/api/history.py` (the kiosk's too,
    announced to its device by `ashley.channels.model.Inbound.device_id`); its Agree tap (`ashley.api.chat.agree_to`)
    builds an `Inbound` with `ashley.channels.model.Inbound.agree`, carried out by `ashley.channels.agree.agree` with no
    model step, what became of each call kept on the person's turn rather than as a turn of hers
    (`ashley.conversations.inflight.InFlight.agreed`)
  - what the open screens are told of each turn is `ashley.channels.live_turn.Showing`
  - a turn on a channel that takes later replies is checkpointed as its loop goes (`ashley.channels.inflight.Saved`,
    through the loop's `ashley.channels.tool_loop.Steps`; its JSON `ashley.channels.checkpoint.Checkpoint`), and one whose
    runner stopped is finished by `ashley.channels.resume.sweep` in the `inflight` singleton under `Lease`
    (`ashley.channels.resume.run`, tunables `app/ashley/channels/inflight.json`, `ashley.channels.inflight_config`); an answer that goes out through the
    outbox is queued in the transaction that stores it (`ashley.channels.outbox.Outbox.answer`); on a thread whose
    messages steer, her answer is stored only once the turn was handed every message after its own
    (`ashley.channels.answering.stored`), and a turn dropped without an answer leaves work for the oldest message after
    it (`ashley.conversations.inflight.InFlight.drop_leaving`), answered from the start by whichever runner claims it
    (`ashley.channels.left.answer`)
  - the kiosk adapter `app/ashley/api/kiosk.py`, a shared screen paired as a device
    (`ashley.api.kiosk_device.kiosk_signed_in`, its device token kept in its own cookie), showing who is home
    and the household's locale and clock for its own clock (`ashley.channels.kiosk.glance.glance`), the screen's layout (`GET /api/kiosk/layout`, the Workshop's `screen`)
    and the buttons of its `controls` piece, each run through Tools by code (`ashley.channels.kiosk.controls.run`)
  - Home Assistant waking her, `app/ashley/channels/wake/`: the `wakes` singleton under `Lease`
    (`ashley.channels.wake.runner`, tunables `app/ashley/channels/wake/wakes.json`) takes each due wake, finds its
    event's one wake rule on the household's open benches (`ashley.channels.wake.rule.rule_for`, through
    `ashley.workshop.workshop.Workshop.of_kind`) and runs her own turn on it (`ashley.channels.wake.wake_turn.inbound`):
    unprompted, on the phone thread of the person it is about, with only the rule's tools (`ashley.tools.only.Only`),
    the wake's id its `source` so a wake handed in again is one turn; a due reminder runs as her turn on the phone
    thread of the person it is for, with only the tools that read (`ashley.tools.reading.Reading`) or the ones it names
    (`ashley.tools.only.Only`) and, for one a deposit fired, that deposit's fields, and goes out because they asked
    (`ashley.channels.wake.reminder_turn.inbound`, `ashley.channels.model.Inbound.promised`)
  - a watch's wake (`ashley.senses.wakes.WatchWake`), such as a Claude Code session she handed work to finishing or
    blocking, `ashley.channels.wake.watch_turn.fired`, taken up by the `wakes` singleton like any wake (Senses, below):
    her turn on the bench's talk that armed the watch, else the phone thread, the wake's id its `source`; whether its reply is said and whether it also goes to their phone are her fields, `Reply.worth_saying` and
    `Reply.to_phone`, the phone offered with whether a page is open (`ashley.channels.to_phone.reachable`,
    `ashley.channels.to_phone.looking`)
  - tap to talk on both, `app/ashley/api/spoken.py`, which turns one utterance's WAV into words
    (`ashley.channels.spoken.words_in`, its cap data, `app/ashley/channels/spoken.json`) that the page then sends as
    typed, tagged `said_aloud`; her answer aloud is `ashley.channels.aloud`, played from `app/ashley/api/voice_turns.py`
- **Who asks, how:**
  - Each channel adapter
  - the turn loop adds to the outbox
  - the Devices room's list, `app/ashley/api/devices.py`, through `ashley.channels.devices.Devices.of_household`, and its
    touch-control editor, `app/ashley/api/device_controls.py`

### Conversations

- **Owns (the question it answers):** What has been said in this exchange, by whom, and is it still going? Which
  conversation is this thread carrying?
- **Where:** `app/ashley/conversations/`
- **Pattern:**
  - Service behind the locator, Postgres implementation `ashley.conversations.postgres.PostgresConversations`, a Null
    Object that raises
  - state a pure function, `ashley.conversations.policy.Policy.state_of`
  - a turn's work in flight, claimed by one runner and holding the turn loop's checkpoint until her turn is stored, is
    `ashley.conversations.inflight.InFlight` (Postgres implementation
    `ashley.conversations.postgres_inflight.PostgresInFlight`, table `turn_work`; a Null Object that keeps nothing and
    stores her turn through Conversations); which turns of a conversation have work, for a page to show as pending, is
    `ashley.conversations.inflight.InFlight.working`
  - a turn's author is `ashley.conversations.model.Author`: a person, her, or the household speaking as itself (a wake)
  - a person's turn may carry what they pasted or forwarded, `ashley.conversations.model.Attachment`, stored on the turn
    and read with it; over `ashley.channels.pasted.threshold` its turn starts tainted `pasted` (`ashley.channels.pasted.taint_of`)
  - a person's conversations, newest activity first and paged by `ashley.conversations.model.Cursor`, are
    `ashley.conversations.conversations.Conversations.of_person`
  - the earlier turns a reply may carry across conversations, each recording who could hear it
    (`ashley.conversations.model.Heard`) and passing the hearing rule facts pass (`ashley.hearing.MAY_HEAR`) for the
    reply's `ashley.conversations.model.Hearer` in SQL, are `ashley.conversations.conversations.Conversations.carried`
- **Who asks, how:**
  - Channels, through `services.get` on `ashley.conversations.conversations.Conversations` (the turns a reply carries,
    `ashley.channels.history.carried`, budgets per kind in `app/ashley/channels/turns.json`)
  - a person's earlier conversations, read-only, `app/ashley/api/history.py`; a bench's whole talk is the same
    read on its thread (`Conversations.of_person` with `thread`, `app/ashley/api/bench_talk.py`)

### Inference

- **Owns (the question it answers):** Which model carries out this task now, and what did that call cost?
- **Where:**
  - `app/ashley/inference/`
  - routes and prices are data, `app/ashley/inference/routes.json` and `app/ashley/inference/prices.json`; a task may
    take another's route list (`{"like": "<task>"}`), as `escalated` takes `brainstorm`'s, or wait for its first route
    (`{"routes": [...], "fallback": false}`, `ashley.inference.routes.without_fallback`), as `memory_write` does
  - an operator overlays them from the file `ROUTES_FILE` names (`ashley.inference.routes.overlay`, applied by
    `ashley.inference.routes.load`): a task in the file replaces that task's whole entry
- **Pattern:**
  - Service behind the locator, Postgres-ledgered implementation `ashley.inference.router.RoutedInference` with a
    Strategy per provider (`ashley.inference.providers.AnthropicProvider`,
    `ashley.inference.providers.OpenAICompatibleProvider`, which also transcribes), and for speech
    `ashley.inference.wyoming_stt.WyomingTranscriber` and `ashley.inference.elevenlabs_tts.ElevenLabsSpeaker` behind
    `ashley.inference.speech_provider.Transcriber` and `ashley.inference.speech_provider.Speaker`, a Null Object that
    raises `ashley.inference.inference.InferenceUnavailable`
  - embeddings are `ashley.inference.inference.Inference.embed` (a `query` or `passage` vector per text), routed by
    `ashley.inference.embed_router.EmbedCalls` to an `ashley.inference.embed_provider.Embedder`, whose one
    implementation runs the model in-process, `ashley.inference.fastembed_embedder.FastEmbedder`
  - a voiceprint is `ashley.inference.inference.Inference.voiceprint` (how the voice in one utterance sounds, a unit
    vector), routed by `ashley.inference.voiceprint_router.VoiceprintCalls` to an
    `ashley.inference.voiceprint_provider.VoiceEmbedder`, whose one implementation runs the model in-process,
    `ashley.inference.sherpa_voiceprint.SherpaVoiceEmbedder`, wired only when the model file exists
  - a picture is `ashley.inference.inference.Inference.make_image`, routed by `ashley.inference.image_router.ImageCalls`
    to an `ashley.inference.image_provider.ImageMaker` (`ashley.inference.gemini_image.GeminiImageMaker`,
    `ashley.inference.openai_image.OpenAIImageMaker`), a household's count of them limited before any call by
    `ashley.inference.image_quota.ImageCap` (limit data in `app/ashley/inference/image.json`); her tool for it is
    `ashley.tools.bench_image.BenchImageTools`
  - the keyed providers (Anthropic, OpenAI with its images, Gemini with its images, ElevenLabs) are built from the keys
    in force, `ashley.inference.keyed_providers.KeyedProviders`, a per-pod cache read again at most every 30 seconds
    over `ashley.inference.provider_keys.ConnectionProviderKeys`: the first household's connections of the `inference`
    port (Connections, below), the env's keys where it has none. Each is a Type Object,
    `ashley.inference.keyed.KeyedProvider` (`ashley.inference.kinds.KEYED`); the env's keys seed the rows at start
    (`ashley.inference.key_seed.seed_from_env`). The keyless ones (a local server, Wyoming, the in-process models) are
    wired from settings by `ashley.wiring_providers.providers`
  - spend kept by `ashley.inference.postgres.PostgresSpendLedger`
  - the spend page (`app/ashley/api/spend.py`, the Usage room) reads it through `ashley.channels.spend_report.SpendReport`
    (`ashley.channels.spend_view.SpendView`): usage per provider and task over today, the last 7 days and the month in the
    household's zone (`ashley.inference.spend_tally.tally`), each provider's label and why it has no readable balance
    (`app/ashley/inference/providers.json`), and optional monthly budgets (`app/ashley/inference/budgets.json`, shipped
    empty) that give a labelled estimate of what is left. A provider that reports a remaining quota has a Strategy,
    `ashley.inference.balance.BalanceSource` (`ashley.inference.elevenlabs_quota.ElevenLabsQuota`), read through
    `ashley.inference.balance.ProviderBalances` and cached for a minute; the others are unknown by design
  - a singleton under the lease, `ashley.inference.watch.run`, reads the ledger (`ashley.inference.outcomes.shares`) and
    warns when one provider failed too large a share of recent chat calls, so a fall-through to the next route cannot
    hide it; thresholds are data, `app/ashley/inference/watch.json`
  - what each chat provider is sent is gated: `ashley.inference.openai_wire.reply_schema` and
    `ashley.inference.anthropic_wire.reply_schema` build the response format, and `app/tests/test_provider_schemas.py`
    checks it and every tool schema against the keywords a provider rejects (`app/tests/provider_schema_rejects.json`)
  - tool use is a step the caller loops, `ashley.inference.inference.Inference.step`
  - a system prompt is an `ashley.inference.model.SystemPrompt` (a stable part, then what changes per message);
    `ashley.inference.providers.AnthropicProvider` caches the tools, the stable part and the last turn, and sends the moment after the history, uncached
  - speech is `ashley.inference.inference.Inference.transcribe` (fed the utterance as it arrives) and
    `ashley.inference.inference.Inference.speak` (a stream), routed by `ashley.inference.speech_router.SpeechCalls` over
    the shared `ashley.inference.roster.Roster`
- **Who asks, how:** Channels and the memory writer, through `services.get` on `ashley.inference.inference.Inference`

### Memory

- **Owns (the question it answers):** What does she know about this household and its people, and who may hear it?
- **Where:**
  - `app/ashley/memory/`
  - the eval's cases are data, `app/ashley/memory/eval/recall_cases.json` and `app/ashley/memory/eval/write_cases.json`
- **Pattern:**
  - Service behind the locator, `ashley.memory.memory.Memory`, Postgres implementation
    `ashley.memory.postgres.PostgresMemory` (visibility filtered in SQL by `ashley.hearing.MAY_HEAR`, the rule carried
    turns pass too, before the full-text and embedding search, whose nearest facts are added to the text matches; policy
    data, `app/ashley/memory/recall.json`; an embedder that cannot answer leaves full-text alone; standing facts reach
    every reply through `ashley.memory.memory.Memory.profile` under the same filter, and recall leaves them out), a Null
    Object that raises `ashley.memory.memory.MemoryUnavailable`
  - what concerns one person, which they see, correct and forget, is `ashley.memory.memory.Memory.held` (household money, visibility `members`, is every member's), and a forget is
    `ashley.memory.memory.Memory.forget`
  - the write job, `ashley.memory.write_job.WriteJob`, is a singleton under `Lease` that writes idle conversations in
    ticks, its settings data (`app/ashley/memory/write_job.json`), each conversation's watermark set in `apply`'s
    transaction, and each tick embedding a batch of facts that lack one (`ashley.memory.memory.Memory.embed_missing`)
  - its decision is a Strategy behind the locator, `ashley.memory.memory.FactWriter` (a Null Object that raises
    `InferenceUnavailable`), whose model-backed one is `ashley.memory.inference_writer.InferenceFactWriter` (its prompt
    `app/ashley/memory/writer.md`, the `memory_write` task)
  - the write eval runs against the live model by `python -m ashley.evals memory-write` (`app/ashley/evals/`), judged by
    `ashley.memory.eval.judge.judge`
  - what she knew at a reply is `python -m ashley.memory report --conversation N` (`ashley.memory.report`), log lines on
    stdin joined to the fact rows
  - the recall eval by embedding is `python -m ashley.evals memory-recall-hybrid` over
    `app/ashley/memory/eval/hybrid_cases.json`, a measurement and not a gate
- **Time on a fact:** `ashley.persona.facts` shows each fact it renders with `(learned <stamp>)` from `valid_from`, by
  `ashley.stamp.stamp`, the one time format for everything she is shown (`docs/decisions.md`, "Every time she is shown is a
  household-local stamp").
- **Who asks, how:** Channels (profile and recall, `ashley.channels.recall.remembered`) the write job (similar, apply),
  a person's memory routes (`app/ashley/api/memory.py`: held, apply, forget), and remembering one line now
  (`ashley.memory.remember.remember`, the write job's `FactWriter` from the locator over the turns its watermark has not
  reached, applied with the watermark), which she asks for herself by setting `Reply.memory`
  (`ashley.channels.keep.now`, a `forget` deleted by code and a `keep` or `correct` through `remember`, after her turn
  is stored, its outcome logged and not shown on the line; the eval is `python -m ashley.evals reply-remember`,
  `ashley.evals.reply_remember`)

### People

- **Owns (the question it answers):** Who is in this household, and whose is this account?
- **Where:** `app/ashley/people/`
- **Pattern:**
  - Service behind the locator, Postgres implementation `ashley.people.postgres.PostgresPeople`, a Null Object that
    raises
  - written by the admin CLI, `app/ashley/people/__main__.py`, and by a signed-in person for their own accounts through
    a second, narrower service, `ashley.people.accounts.Accounts` (Postgres
    `ashley.people.postgres_accounts.PostgresAccounts`: their accounts, linking one, unlinking their Discord), kept
    apart so nothing that reads people can write them
  - a household's own fields (timezone, profile, locale, unit system, clock, home location; `ashley.people.model.Household`) are
    set by its people on the Devices room's household panel through a third service,
    `ashley.people.household_write.HouseholdWriter` (Postgres
    `ashley.people.postgres_household_write.PostgresHouseholdWriter`), which only that route and the wiring import
    (`app/tests/test_settings_boundary.py`); both it and the admin CLI check values with `app/ashley/people/fields.py`
- **Who asks, how:**
  - Channels and Presence, through `services.get` on `ashley.people.people.People`
  - the persona, which says the household's units (`ashley.persona.facts.UNITS`) before its profile
  - the accounts routes (`app/ashley/api/accounts.py`) on `ashley.people.accounts.Accounts`
  - the household routes (`app/ashley/api/household.py`) on `ashley.people.household_write.HouseholdWriter`; the web
    client writes every date, time and number in the household's locale and clock (`app/web/src/household/format.ts`)

### Connections

- **Owns (the question it answers):** How does she reach this household's services outside her, and with what secret?
- **Where:** `app/ashley/connections/`, table `connections`
- **Pattern:**
  - Service behind the locator, `ashley.connections.connections.Connections`, Postgres implementation
    `ashley.connections.postgres.PostgresConnections`, a row per connection addressed by its id, wired only with
    `CONNECTIONS_KEY`; a Null Object that cannot open and raises
  - the kinds are Type Objects, `ashley.connections.kinds.ConnectionKind` (name, who may hold it (`holders`), address rule,
    secret field, the one authenticated read, refusal texts, the panel's words), each declared by its adapter
    (`ashley.sure.kind.SURE`, `ashley.home_assistant.kind.HOME_ASSISTANT`, `ashley.codehost.kinds.GITLAB` and
    `ashley.codehost.kinds.GITHUB`) and registered in `ashley.wiring.CONNECTION_KINDS` behind the locator service
    `ashley.connections.kinds.ConnectionKinds` (a Null Object with none); a personal kind's rows carry `person_id`. A
    connection carries a `label` its owner gives it, and a kind's `most` is how many of it one owner may hold (one for
    every kind today), so `Connections` adds, replaces, renames, removes and opens by id and raises `LabelTaken` and
    `TooMany`; a connection is visible to a person when it is the household's or theirs.
    Nothing else lists kinds; a new service is its adapter's declaration and one line in the wiring
  - a kind declares the ports it implements, `ashley.connections.model.Port` (house, ledger, code_host, herdr, mail,
    inference), and
    a consumer opens a port, never a kind: `ashley.connections.ports.opened` and `ashley.connections.ports.opened_all`
    open the visible connections of the kinds of `ConnectionKinds.of_port`, in registration order, then label, then id. A second service
    for a port is its adapter and one line in the wiring; the code host tools alone keep a per-forge choice, since
    `ashley.codehost.routed.RoutedCodeHost` routes each call by forge
  - the herdr bridge, a person's own program on the machine where their herdr runs (`bridge/herdr/`, importing nothing
    from `ashley`), is reached as the personal kind `ashley.herdr.kind.HERDR`, whose address carries the bridge's
    certificate fingerprint; it serves one person and offers list, read, prompt, start and close, and file transfer through a session's `in/` and `out/`, over mutual TLS
  - the bridge is a port behind the locator, `ashley.herdr.bridge.Bridge` (`ashley.herdr.http_bridge.HttpBridge`, which
    presents the app's client certificate and pins the bridge's by fingerprint before sending the token, and a Null Object
    that fails), its bodies parsed by `ashley.herdr.wire`; limits are data, `app/ashley/herdr/herdr.json`
  - each secret sealed by `ashley.connections.sealing.Sealer` (AES-256-GCM, a key version byte, bound to its row)
  - a kind's `connect` is `ashley.connections.kinds.Pasted` or `ashley.connections.kinds.OAuth`; an OAuth kind's secret is
    a refresh token, and the row keeps the sealed access token, its expiry, the granted scopes, `secret_version` and
    `needs` (`ashley.connections.oauth_connections.OAuthConnections`). Providers are ports behind
    `ashley.connections.oauth.OAuthProviders` (`ashley.google.oauth.GoogleOAuth`, the kind `ashley.google.kind.GOOGLE`),
    connects in flight are `ashley.connections.pending.ConnectPending`, and
    `ashley.connections.renewal.Renewal` hands out an access token, refreshing it by compare-and-set on `secret_version`
  - what a connection reaches is `ashley.connections.resources.ConnectionResources` (Postgres, table
    `connection_resources`): a kind's `resources` lists them (`ashley.connections.resource_sync.sync`), each is shared with
    the household or kept by the connection's owner, and `usable(use, changing)` is the gate a tool source asks which
    resources a turn may use; `Connections.move` hands a connection to the household or takes it back, sealing its
    secret again (`ashley.connections.moves.move`)
  - an adapter calls `ashley.connections.answered.record` once a read of the service succeeded, which moves the row's `checked_at`
  - Sure itself is a port behind the locator, `ashley.sure.client.Sure` (`ashley.sure.client.HttpSure`, a Null Object
    that fails), its bodies parsed by `ashley.sure.wire` and read by the Ledger adapter (below)
- **Who asks, how:**
  - a person's connection routes (`app/ashley/api/connections.py`, `POST /api/connections` and `PUT`/`PATCH`/`DELETE /api/connections/{id}`), which
    check a new or replaced one with its kind's `check` before storing it; the settings routes (`app/ashley/api/connection_settings.py`),
    the only importer of `ashley.connections.settings_write.SettingsWriter`, which read and replace what a person sets on a
    connection (`ashley.connections.settings`, read by `SettingsReader`, held by a boundary test); the client's connections room
    (`app/web/src/rooms/connections/ConnectionsRoom.tsx`), which draws the kinds `GET /api/connections` serves
  - her money tools (`ashley.tools.money.MoneyTools`), which read the household's money through the Ledger (below)
  - her code host tools (`ashley.tools.code_host.CodeHostTools`), which open the speaking person's own GitLab and
    GitHub connections per turn and read through the neutral port `ashley.codehost.host.CodeHost` (adapters
    `ashley.codehost.gitlab.GitLabHost` and `ashley.codehost.github.GitHubHost`, routed by
    `ashley.codehost.routed.RoutedCodeHost`, a Null Object that fails; tunables `app/ashley/codehost/codehost.json`);
    reads only, and a file or snapshot goes onto a bench through `ashley.workshop.bench_file.add_file`
  - her mail tools (`ashley.tools.mail.MailTools`), which open the Google connections whose mailboxes the turn may use
    (Mail, below), offered on any turn by the resource gate, not the code host tools' gate
  - her Claude Code tools (`ashley.tools.claude_code.ClaudeCodeTools`), which open the speaking person's `herdr`
    connection per turn and list, read, prompt, start and close their sessions through the `Bridge` port; offered by
    the same gate as the code host tools, tunables `app/ashley/tools/claude_code.json`; a session they start or prompt is
    watched (Senses, below)
  - her devices read (`ashley.channels.devices_tool.DeviceTools`, `household_devices`), over
    `ashley.channels.devices.Devices.of_household`: the household's satellites, tablets, Discord servers and house, not
    Home Assistant's entities (`ashley.tools.house_roster.roster`)
  - Homes (below), which opens the household's Home Assistant connection, and `ashley.home_assistant.seed.seed_from_env`
    at start and again from Homes until household 1's row is seen
  - Inference (above), which opens the first household's `inference` connections for the model providers' keys; their
    kinds are `deployment` kinds (`ashley.connections.kinds.ConnectionKinds.offered`), offered to that household alone
  - a kind whose deployment-side setting is absent is not `configured` (`ashley.wiring._configured_kinds`: herdr's client
    certificate, `MAIL_BRIDGE_IMAGE` for Proton): it stays registered, so a stored row is still listed and removable, but
    it is not offered, cannot be added and opens through no port

### Ledger

- **Owns (the question it answers):** What does this household's money look like, whichever app it is kept in?
- **Where:** `app/ashley/ledger/`
- **Pattern:**
  - Service behind the locator, `ashley.ledger.ledger.Ledger`, reads only: accounts, categories, net worth and
    transactions as neutral records (`ashley.ledger.model`: `Account`, `Category`, `NetWorth`, `Entry`), a Null Object
    with no household connected
  - adapter pattern over those records: Sure is the first adapter, `ashley.sure.ledger.SureLedger`, which opens the
    household's Sure connection and is the only place Sure's field names (`ashley.sure.wire`) are read; another
    budgeting app is another adapter registered in `ashley.wiring`
- **Who asks, how:**
  - her money tools (`ashley.tools.money.MoneyTools`), which ask `connected` once per turn and render the records
  - the deposit sense (`ashley.senses.ledger_transactions`), which pages `Ledger.transactions` and derives the records
    criteria are judged over (`ashley.criteria.record.Transaction`) from each `Entry`
- **Known duplicates:** none. Writing (categorising) and events like "balance below" are not built.

### Mail

- **Owns (the question it answers):** What is in this person's mailbox, whichever provider keeps it?
- **Where:** `app/ashley/mail/`, tunables `app/ashley/mail/mail.json`
- **Pattern:**
  - Service behind the locator, `ashley.mail.mailbox.Mailbox`: a mailbox's address, folders and
    labels, a search and one message as neutral records (`ashley.mail.model`: `Header`, `Message`, `MailQuery`, `Page`),
    failing as `ashley.mail.model.MailFailed` (`refused`, `unreachable`, `syncing`, `needs_reconnect`, `not_found`); a
    Null Object that fails
  - adapter pattern over those records: Gmail is the first adapter, `ashley.mail.gmail.GmailMailbox`, the only code that
    reads Gmail's field names (`ashley.mail.gmail_shapes`); it takes the access token from
    `ashley.connections.renewal.Renewal` and turns a `MailQuery` into Gmail's search (`ashley.mail.gmail_query`) and
    a MIME tree into text (`ashley.mail.body`); Proton over IMAP and SMTP is the second adapter,
    `ashley.mail.imap.ImapMailbox`, the only code that knows Bridge's folders (`Labels/<name>`) and names a message by its
    `Message-ID`; `ashley.mail.routed.RoutedMailbox` is what the locator holds, sending each call to the adapter of the
    connection's kind, and `ashley.mail.calls` is the bookkeeping of a call both share (Bridge's keeping:
    `ashley.mail.proton_bridge.ProtonBridge` holds its sealed vault, the epoch that fences one pod at a time and each
    account's sync, and `ashley.mail.proton_bridge_job.run` is a singleton under the lease that keeps the pod)
- **Who asks, how:**
  - her mail tools (`ashley.tools.mail.MailTools`), which open the Google and Proton connections through the `mail` port
    and offer the four reads for the mailboxes `ashley.connections.resources.ConnectionResources.usable` returns for the
    turn (a shared one on any turn of its household, a kept one where the reply reaches its owner alone) whose
    connection may be read: granted a Gmail read scope, or a Proton connection (no scopes)
- **Known duplicates:** none.

### Sign-in

- **Owns (the question it answers):** Which person is this browser signed in as?
- **Where:**
  - `app/ashley/signin/`
  - lifetimes are data, `app/ashley/signin/signin.json`
- **Pattern:**
  - Service behind the locator, `ashley.signin.sessions.Sessions`, Postgres implementation
    `ashley.signin.postgres.PostgresSessions` (sign-ins in flight, sessions, refused accounts, and links of a Discord
    account in flight), a Null Object that raises
  - the provider is a port, `ashley.signin.oidc.Oidc`, whose one implementation `ashley.signin.provider.OidcProvider`
    is wired when its settings are (the only module importing joserfc), a Null Object that raises
    `ashley.signin.oidc.OidcUnavailable`
  - Discord's OAuth2, for linking, is a port too, `ashley.signin.discord.DiscordOAuth`, implemented by
    `ashley.signin.discord_http.HttpDiscordOAuth` when its settings are, a Null Object that raises
    `ashley.signin.discord.LinkUnavailable`
  - an account names a person only through People's accounts
  - refused accounts are listed by `app/ashley/signin/__main__.py`. Its own row rather than part of People: People is
    reference data, while sign-in owns credentials and flows that expire, as Devices does for devices
- **Who asks, how:** The web routes (`app/ashley/api/signin.py`) and every route for a person, through
  `ashley.api.person.person_signed_in`

### Tools

- **Owns (the question it answers):** What can she do beyond talking right now, and do it
- **Where:**
  - `app/ashley/tools/`
  - the tunables are data, `app/ashley/tools/search.json` and `app/ashley/tools/look_up.json`, and the house's
    actions she is never offered, `app/ashley/tools/home_assistant.json`, and the house state's cap and summaries,
    `app/ashley/tools/house_state.json`, and the caps on what her house tools return, `app/ashley/tools/house_look.json`, and the look-up's prompt `app/ashley/tools/look_up.md`, and her bench tools'
    `app/ashley/tools/bench_tools.json`
  - how she uses the house's tools is measured by `python -m ashley.evals house` (`ashley.evals.house`) over
    `app/ashley/evals/house_cases.json`, through her real turn loop with `ashley.evals.house_guard.GuardedTools`
    answering every tool off the read allow-list `app/ashley/evals/house_reads.json` as done without calling it, and `ashley.evals.house_readonly.ReadOnlyHomes` keeping every change of her per-turn `house_change` from the House, so nothing reaches the house and she has no error to retry on; an `action` case is scored on the round of its expected write (`steps_to_write`) and left out of the totals' steps and step-limit count
  - a measurement and not a gate
- **Pattern:**
  - Service behind the locator, wired as a Composite, `ashley.tools.composite.CompositeTools`, that merges its sources'
    catalogues, names the ones that did not answer in `ashley.tools.tools.Catalogue.unreachable`, and routes each call
    to the source that offered it; the locator's `Tools` is the look-up over the web alone, for a household with no
    house
  - each household's everyday tools come from `ashley.tools.everyday.Everyday` (`ashley.tools.everyday.HomesEveryday`,
    a Null Object answering the locator's `Tools`): over the household's own Home (Homes, below), the house's sources
    and the look-up with places near it, built once per Home and kept while it is the same, since the house tools'
    catalogue is cached per Home; a household with no Home gets the look-up with places near its own location,
    built once for it; a turn holds them as `ashley.tools.everyday.HouseholdTools`, a Proxy that asks once
  - her sources are the house, `ashley.tools.house_tools.HouseTools` over the Home's `House` (Homes, below): its
    instructions are her `app/ashley/tools/home_assistant.md` over `ashley.tools.house_roster.roster` of the devices the household
    lists and `ashley.tools.house_roster.devices` of the house's own, its live state, `ashley.tools.house_state.HouseStateTools`, one tool answered in code from `House.states`
    (`ashley.tools.house_targets.entity_of`), narrowed by `ashley.tools.house_query.select` and summarised under its cap by
    `ashley.tools.house_render.answer`, anything the house has and how it is set up (`ashley.tools.house_find`), how things
    changed (`ashley.tools.house_history`), and actions, `house_ask` for those that only read and `house_do` for the rest
    (`ashley.tools.house_act`), the things named resolved in code by `ashley.tools.house_targets.resolve`; and the look-up,
    `ashley.tools.look_up.LookUpTools`, a sub-agent offered as one tool that runs its own `Inference.step` loop over a
    second Composite, made afresh for each look-up, of the web through SearXNG,
    `ashley.tools.web_search.WebSearchTools`, wrapped in `ashley.tools.pages.Pages`, which numbers the results into the
    turn's `ashley.tools.results.Results` (bound by `ashley.channels.landing.Landing` while a call runs, so a bench tool of
    the turn names a result by its number, `ashley.tools.bench_reference.References`) and reads a result's page by its number through `ashley.tools.page_fetch.fetch` (the one module that
    opens an arbitrary URL, public https hosts only) and `ashley.tools.page_text.text_of` (a YouTube video's page through `ashley.tools.youtube.read_page` instead, and a paste or GitHub file view at its plain-text address, `ashley.tools.raw_source.raw_url`; the choice is `ashley.tools.page_reader.PageReader`, a service the bench tools also use to read a site or video piece's page, `ashley.tools.bench_page`; a page's schema.org recipe is kept beside its text, `ashley.tools.recipe_ld.recipe_in`, and a page whose site refuses the plain fetch is read in the page browser, `ashley.tools.page_reader.browsed_page`, Looks below), and places near the house
    through Photon, `ashley.tools.places.PlacesTools` (which reads the house's location from the household's own
    (`ashley.tools.home_location.own`) before Home Assistant's, `ashley.home_assistant.zone.home`), and Printables' 3D models, `ashley.tools.printables_search.PrintablesSearchTools`
    over the Printables service (below), whose results are numbered into the same `Results` as model pages, and returns
    `ashley.tools.look_up.LookedUp` cut to length in code
  - the Printables service, `ashley.printables.printables.Printables` (a Null Object that fails), over Printables' public
    GraphQL API as a visitor who is not logged in: `ashley.printables.graphql.GraphqlPrintables` searches, reads a model
    with its files, and asks for a file's address, which `ashley.tools.printables_fetch.fetcher` opens through
    `ashley.tools.page_fetch.fetch_file` (Printables' file hosts only, every hop checked); `read_page` reads a model's
    page through it (`ashley.tools.printables_page.page_of`); tunables `app/ashley/printables/printables.json`
  - a Null Object whose catalogue raises
  - each tool says whether it only reads, `ashley.inference.model.ToolSpec.reads`: her house reads are their own tools, and
    `house_ask` runs an action the house says only returns data or a script in the household's `reads` setting
    (`ashley.home_assistant.house_values`); her own where each is defined
  - each turn, `ashley.channels.turn_tools.for_turn` adds after it, in a Composite made for that turn, the sources the
    `Inbound`'s fields call for: with a known speaker, changes to the house's setup, `ashley.tools.house_change.HouseChangeTools`
    (`house_change`, and `house_confirm` from a later person turn of a proposal, `ashley.senses.proposals.Proposals`
    on its house topic; what needs the person's OK is data,
    `ashley.home_assistant.irreversible`); on a bench's talk her tools on that bench, `ashley.tools.bench_tools.BenchTools`,
    Commands by her through the Workshop, and on her web chat opening a bench, `ashley.tools.open_bench.OpenBenchTools`,
    and on either, a page of the speaker's own (`ashley.channels.model.Inbound.on_page`), moving that page,
    `ashley.tools.move_page.MovePageTools`, after which the turn is that bench's (`ashley.channels.landing.Landing`
    rebuilds this set, "Her reply follows the page" in decisions); and on any turn whose ids are known while a sandbox is wired, running
    code, `ashley.tools.run_code.RunCodeTools` (Code runs, below), except that a turn on a bench (its talk, or moved
    there) runs its code pieces instead, `ashley.tools.bench_run.BenchRunTools`, and never loose code; on a bench, the
    house's automations, `ashley.tools.bench_automations.BenchAutomationTools` (list, read one as a piece's body,
    propose installing a piece; an empty catalogue while the household has no house); and
    where the reply reaches the speaker alone (`ashley.channels.audience.owner_alone`) while Connections can open, the
    household's finances, `ashley.tools.money.MoneyTools` over the Ledger (tunables `app/ashley/tools/money.json`); and on
    any turn whose channel names the speaker, setting reminders, `ashley.tools.reminders.ReminderTools`, which lists,
    changes and cancels theirs only where the reply reaches them alone, and is given the turn's other tools to let a
    reminder name (`ashley.channels.turn_tools.for_turn`); and, with a known speaker or on a device's own thread, arranging the
    household's screens, `ashley.channels.screen_tools.ScreenTools` (Commands by her through `Workshop.apply_screen`)
- **Who asks, how:**
  - Channels, through `ashley.channels.turn_tools.for_turn` over the turn's household's
    `ashley.tools.everyday.HouseholdTools`
  - the kiosk's controls, through the device's household's `ashley.tools.everyday.HouseholdTools`

### Workshop

- **Owns (the question it answers):** What is on this bench, and who changed what?
- **Where:**
  - `app/ashley/workshop/`
  - piece kinds are data, `app/ashley/workshop/kinds.json`, and a bench's limits `app/ashley/workshop/workshop.json`
- **Pattern:**
  - Service behind the locator, `ashley.workshop.workshop.Workshop`, Postgres implementation
    `ashley.workshop.postgres.PostgresWorkshop`, a Null Object that raises
    `ashley.workshop.workshop.WorkshopUnavailable`
  - kinds a Type Object (`ashley.workshop.rules.Kind`)
  - every change a Command in one closed union (`ashley.workshop.commands.Command`) judged by one pure
    `ashley.workshop.decide.decide` into an accepted effect or a typed refusal, each logged, so replay from empty
    rebuilds the bench (`ashley.workshop.decide.replay`) and undo is a command; the command a press of Undo names
    is a walk over the last `undo_window` commands of the log (`ashley.workshop.undo_walk.next_undo`), never a stored pointer
  - a kind's body format is data (`format`, and `language` for code); a piece's last change and a bench's piece count
    and last change are read from the Commands, never stored
  - a piece's place is a value (`ashley.workshop.model.Place`) for Surfaces to take over
  - a device's screen is a bench of the device (`benches.device_id`, owner null; migration 0092), its pieces the `screen`
    family of kinds (`clock`, `home`, `conversation`, `controls`) under its own rules
    (`ashley.workshop.rules.load_screen`, `app/ashley/workshop/screen.json`: one of each, the conversation required) and
    seeded from `app/ashley/workshop/screen_seed.json` on its first command (`ashley.workshop.postgres_screen`); the same
    Commands, `decide`, log and undo, announced as `ashley.live.events.ScreenChanged` to the household's screens, and
    left out of every person-scoped bench query; she arranges it with `ashley.channels.screen_tools.ScreenTools`
  - a bench's shelf holds the pieces taken off its layout by `ashley.workshop.commands.Archive` and brought back by
    `ashley.workshop.commands.Restore`, ordinary undoable Commands; closing and reopening a bench
    (`ashley.workshop.workshop.Workshop.reopen`) are operations on the bench, outside the log
  - running a code piece is a Run command (`ashley.workshop.commands.Run`) whose effect changes no piece and is never
    undone; `ashley.workshop.run_piece.run_piece` logs it, then runs the body through Code runs' one runner
  - a `live` kind's body is a reference the client frames: `site` an https URL, `video` a JSON object of a url and a
    start, both checked by `ashley.workshop.embed` and served for a video as `BenchPiece.video`; a site's framing is
    measured once per address from the site's headers (`ashley.api.bench_frames`) and served as `BenchPiece.site`
  - an automation piece's body is Home Assistant's automation config as JSON (`ashley.workshop.automation_config`);
    her `ashley.workshop.commands.Propose` and the person's `ashley.workshop.commands.Install` are Commands, and an
    accepted Install, or its undo, is carried out on the house by `ashley.workshop.install_piece.carry_out` through
    `ashley.home_assistant.automations.Automations`, recorded before and after by a service behind the locator,
    `ashley.workshop.installs.Installs` (Postgres `ashley.workshop.installs_postgres.PostgresInstalls`, table
    `bench_installs`; a Null Object that raises, so nothing reaches the house unrecorded); a piece's waiting proposal
    is read from the log (`ashley.workshop.proposals.pending`)
  - a wake rule piece (kind `wake`) is the event it answers, her brief for that turn and the tools it may use, checked by
    `ashley.workshop.wake_rule.rule_of`; an automation piece may carry the action that wakes her,
    `ashley.workshop.wake_action.SERVICE` with structured data only (`ashley.workshop.wake_action.well_formed`)
  - an accepted command is announced on Live as `ashley.live.events.BenchChanged` to the owner alone
  - a cue (`ashley.workshop.commands.Cue`, hers through `bench_cue`) drives a video piece's player and changes no piece
    and is never undone; it is announced as `ashley.live.events.BenchCued` instead, which the client's player obeys
    (`app/web/src/rooms/workshop/pieces/player.ts`)
  - a reader piece (kind `reader`) is a page's text as she read it, with its url and title, as JSON checked by
    `ashley.workshop.reader.page_of` and served as `BenchPiece.reader`; she makes one by the number of a page `read_page`
    returned this turn (`ashley.tools.results.Results.page`, written into the body by `ashley.tools.bench_reference`)
  - a recipe piece (kind `recipe`) is the recipe a page published as schema.org data and the headcount it is for, as
    JSON checked by `ashley.workshop.recipe.recipe_of`, made like a reader piece by the number of a page read this turn
    (`ashley.tools.bench_recipe_ref`); its amounts are scaled on read in code (`ashley.workshop.recipe.scaled` over
    `ashley.workshop.quantity.amount_of`, units and limits in `app/ashley/workshop/recipe.json`), the same numbers in her
    read (`ashley.tools.bench_view`) and in `BenchPiece.recipe`, drawn by `app/web/src/rooms/workshop/pieces/RecipeView.tsx`
  - a measurements piece (kind `measurements`) is rows each with a source: numbers with a unit (measured, datasheet,
    accepted, bound or guessed) and choices in plain words (stated, seen, datasheet, accepted or guessed, citing the
    person's turn or the bench piece), as JSON checked by `ashley.workshop.measurements.items_of`, confirmed by
    `ashley.workshop.measurements.confirmed`, a cited turn checked by `ashley.tools.bench_citations.Citations`, and shown
    as a table by `app/web/src/rooms/workshop/pieces/MeasurementsView.tsx`
  - a model piece (kind `model`, a code kind whose language is `build123d`) is shown as its latest run: the GLB drawn
    by `app/web/src/rooms/workshop/pieces/ModelView.tsx` through `app/web/src/rooms/workshop/solid/stage.ts`, the only
    file that imports three.js and reached by `import()`, then downloads and the checks of the run's report; in a look
    the same component draws a four-view sheet (`app/web/src/rooms/workshop/solid/sheet.ts`)
  - a point (`ashley.workshop.commands.Point`, hers through `bench_point`) highlights a passage of a reader piece
    (`ashley.workshop.reader.Passage`, located from an exact quote by `ashley.workshop.reader.locate`); it changes no
    piece and is never undone, is announced as an ordinary `ashley.live.events.BenchChanged`, and the latest one of each
    piece is read back from the log (the `pointers` of `ashley.workshop.workshop.BenchView`, served as `BenchPiece.pointer`
    while the piece is at the version it was made against); the client draws it in
    `app/web/src/rooms/workshop/pieces/ReaderView.tsx`
  - what a person did since she last looked is `ashley.workshop.workshop.Workshop.unseen` over the log and table
    `bench_reactions` (`ashley.workshop.reactions.Unseen`, ids and kinds only); the newest record's `to_seq` is the
    last command she has seen, written by `ashley.workshop.workshop.Workshop.reacted`, never stored on the bench
  - a large piece (family `large`, kinds `image`, `clip` (a video file), `audio` and `file`) is the descriptor of bytes
    the Object store keeps (`ashley.workshop.stored_file`, served as `BenchPiece.file` with a short-lived link); its kind
    is chosen by the bytes' media type (`ashley.files.config.FilesConfig.piece_kind`), it is made only by
    `ashley.workshop.bench_file.add_file`, and `decide` refuses an Edit that changes its body
  - a cue drives a `clip` or `audio` piece's player as it does an embedded video's (`ashley.workshop.decide.PLAYED`); a
    transcript is a reader piece with no address (an empty url, `ashley.workshop.reader.page_of`), put beside the recording by
    her `bench_transcribe` (`ashley.tools.bench_media.BenchMediaTools`), whose body names the recording and each line's
    start (`ashley.workshop.reader.Recording`, served as `BenchPiece.reader.recording`); a click on a line is a cue from
    the page itself (`cueBenchPlayer` in `app/web/src/session/live.ts`), the same path her cue takes to the player
- **Who asks, how:**
  - a person's upload (`app/ashley/api/bench_files.py`), her `bench_add_file` (`ashley.tools.bench_files.BenchFileTools`)
    and her `bench_add_printables_file` (`ashley.tools.bench_printables.BenchPrintablesTools`, a model's STL, 3MF or STEP
    named by a search result's number and a file id)
  - the `wakes` singleton, each sweep, so that she reacts to a bench whose person has paused
    (`ashley.channels.wake.bench_reacts.BenchReacts`, tunables in `app/ashley/channels/wake/bench_react.json`)
  - A person's bench routes (`app/ashley/api/benches.py`)
  - the wake adapter reads the household's wake rules (`ashley.workshop.workshop.Workshop.of_kind`)
  - a person's Run button (`app/ashley/api/bench_runs.py`) and her `bench_run` (`ashley.tools.bench_run.BenchRunTools`)
  - a person's Install and Undo of an install (`app/ashley/api/benches.py`), and her automation tools
    (`ashley.tools.bench_automations.BenchAutomationTools`)
  - her `bench_frames` and `bench_transcribe` (`ashley.tools.bench_media.BenchMediaTools`), offered per bench turn by
    `ashley.channels.turn_tools.sources` while a store and a media worker are wired
  - her bench tools (`ashley.tools.bench_tools.BenchTools`) and opening a bench from web chat
    (`ashley.tools.open_bench.OpenBenchTools`)
  - a person opening a bench from the list with an ask: the ask is the first message of the bench's talk and her turn
    on it leads (`ashley.api.bench_opening.start`)
  - a bench's title is changed by a `ashley.workshop.commands.Rename`, hers through `bench_rename`
  - a bench's kind of work (`ashley.workshop.model.Bench.work`) is set by `ashley.workshop.workshop.Workshop.set_work`,
    an operation outside the log, hers through `bench_work` and the person's through `PUT /api/benches/{id}/work`
  - her `bench_replace` of a stretch of a long piece, which is an `Edit` built from the body as it now is
  - a bench's talk is a conversation on the bench's thread through the turn loop (`app/ashley/api/bench_talk.py`)
  - the client's workshop room (`app/web/src/rooms/workshop/`) shows them, reading a bench back when
    `app/web/src/session/live.ts` hears its `LiveBench`

### Object store

- **Owns (the question it answers):** Where are the bytes of this file, on either site?
- **Where:**
  - `app/ashley/files/`; the limits, the media types a file may be (as signatures) and the link lifetime are data,
    `app/ashley/files/files.json`
- **Pattern:**
  - Service behind the locator, `ashley.files.store.ObjectStore` over a neutral key and bytes, a Null Object that raises
    `ashley.files.store.StoreUnavailable`; adapters `ashley.files.s3.S3Store` (one S3-compatible endpoint, signed by
    `ashley.files.sigv4.sign`), `ashley.files.mirror.MirroredStore` (every site's endpoint as one: write all, read the
    nearest; wired only when `FILES_ENDPOINTS` lists two or more, one endpoint is its `S3Store` alone) and `ashley.files.memory.MemoryStore` (tests)
  - the copies are kept whole by a singleton under the lease, `ashley.files.repair.run`, for a mirrored store alone; bytes no piece names are
    deleted from every site (or the one store) by another, `ashley.files.sweep.run`, which reads what pieces name through
    `ashley.workshop.file_references.named_keys` (large pieces and the artifacts of the runs that remain) and keeps its last pass's findings in `ashley.files.orphans`
  - a file is judged before it is kept (`ashley.files.sniff.sniff` by its bytes, `ashley.files.intake.take`), and
    reached by signed, expiring links (`ashley.files.links`) that answer one byte range (`ashley.files.ranges.parse`),
    so a player seeks
  - Fit: not Postgres (files are too large for rows and for WAL), not Memory, not a bench piece's body; WAL-G's NAS
    endpoints are the same storage, written here by the app itself
- **Who asks, how:**
  - the Workshop's image and file pieces (`ashley.workshop.bench_file.add_file`), the bench routes
    (`app/ashley/api/bench_files.py`, `app/ashley/api/files.py`) and her tools (`ashley.tools.bench_files.BenchFileTools`,
    `ashley.tools.bench_file_text.text_of`)
  - Looks keeps the pictures she was given under their own prefix (`ashley.looks.keys`), which the files' repair keeps whole
    on every site (`ashley.wiring_singletons.REPAIRED_PREFIXES`) and the sweep does not list
  - a media pod (Code runs) fetches the file it works on by a link of `ashley.files.links`
  - Code runs keeps a bench run's meshes (`ashley.runs.artifacts.keep`), judged by `ashley.files.sniff.sniff`; the sweep
    reads them through `named_keys` from `code_runs.artifacts`

### Skills

- **Owns (the question it answers):** What method does she follow for this kind of work in this household, and how
  did it change? And, in the same changelog, what has this household put in place of her persona's taste?
- **Where:**
  - `app/ashley/skills/`; the limits and the shape of a kind's name are data, `app/ashley/skills/skills.json` (the kinds themselves are
    the household's rows, table `skill_kinds`, started by `ashley.skills.skills.Skills.add_kind`), and the seeds
    that ship are documents in `app/ashley/skills/seeds/` (`app/ashley/skills/seeds/3d.md` is her build123d method: measurements with sources,
    the model, its checks, the honest reading of the report)
  - the persona overrides: `app/ashley/skills/persona.py` (read), `app/ashley/skills/persona_write.py` (write), the
    family `persona` of `skill_versions`; which sections may be overridden is each marker's field in
    `app/ashley/persona/ashley.md`, read by `ashley.persona.sections.catalogue`
- **Pattern:**
  - Service behind the locator, `ashley.skills.skills.Skills`, Postgres implementation
    `ashley.skills.postgres.PostgresSkills`, a Null Object that raises `ashley.skills.skills.SkillsUnavailable`
  - a kind's skill is a Type Object: a document per kind, never code; seeds are read by `ashley.skills.seeds.load`
    and carry the owner's skill they were `seeded_from`
  - kinds of work are rows, never a list: she starts one by setting a bench's work to a new name with a label
  - versions are append-only per household and kind (table `skill_versions`); a rollback is a new version, a pin
    (table `skill_pins`) makes her edits `proposed` until `ashley.skills.skills.Skills.decide`
  - persona overrides are a second family in the same changelog: `ashley.skills.persona.PersonaOverrides` reads,
    `ashley.skills.persona_write.PersonaWriter` writes (a person only; the boundary test keeps it to its route and
    the wiring), both registered by `ashley.wiring_skills.wire_skills`; a null body is "the shipped text"
  - Fit: a versioned document, but not Memory (atomic facts retrieved by similarity, per person, superseded by
    correction; a skill is one whole document loaded by key) and not bench pieces (bench-scoped and a person's)
- **Who asks, how:**
  - her tools on a bench (`ashley.tools.bench_skills.BenchSkillTools`), whose instructions carry the bench's skill
    into the stable part of her prompt
  - a person's routes (`app/ashley/api/skills.py`): read, pin, roll back, approve or decline her edit
  - the client's bench bar (`app/web/src/rooms/workshop/bench/Method.tsx`)
  - every reply and errand reads the persona overrides into its prompt (`ashley.channels.taste.overrides`), which
    `ashley.persona.sections.render` applies to the `allowed` sections only
  - a person's persona routes (`app/ashley/api/persona.py`) and the Devices room's panel
    (`app/web/src/rooms/devices/PersonaPanel.tsx`)

### Code runs

- **Owns (the question it answers):** Run this script once, isolated, and keep what happened.
- **Where:**
  - `app/ashley/runs/`
  - the sandbox's tunables are data, `app/ashley/runs/runs.json`: what every run shares at the top level (chars
    limits, poll), and each language, Python and build123d alike (its image given as `CAD_IMAGE`), as
    one `ashley.runs.config.Profile` under `languages`
  - the cluster side (namespace `ashley-sandbox`, RuntimeClass `gvisor`, the app's ServiceAccount) is in the cluster repo;
    the app takes the namespace and class as `SANDBOX_NAMESPACE` and `SANDBOX_RUNTIME_CLASS` (those values by default)
- **Pattern:**
  - the record: Service behind the locator, `ashley.runs.runs.Runs`, Postgres implementation
    `ashley.runs.postgres.PostgresRuns` (table `code_runs`, one row per run tied to the person turn that asked, the
    bench command that made it, or both), a Null Object that raises, so nothing runs unrecorded; it also answers a
    bench piece's latest run and the files its next run starts with, the latest runs asked for by a set of
    turns (`ashley.runs.runs.Runs.of_turns`), and prunes a piece's older runs when a new result is recorded
  - one runner, `ashley.runs.once.run_once`: record the start, run it, keep a bench run's binary artifacts in the
    object store (`ashley.runs.artifacts.keep`; the runner carries them back when the language's profile has an
    `artifact_bytes`), record the end with the artifacts; a model run is started with the STL, 3MF and STEP
    file pieces its `inputs` name (all of the bench's when it names none) as binary inputs (`ashley.workshop.model_inputs`, within the profile's `input_bytes`)
  - where it runs: a Strategy behind the locator, `ashley.runs.sandbox.Sandbox`, whose Null Object runs no language,
    so `run_code` is not offered; `ashley.runs.podman.PodmanSandbox` runs the same pod's container with podman on a
    workstation, for an eval run off the cluster (no gVisor); the app's implementation, `ashley.runs.kubernetes.KubernetesSandbox`, runs the languages
    its config has an image for (`ashley.runs.config.RunsConfig.offered`) and makes one pod per
    run (`ashley.runs.pod_spec.manifest`, from the job's language profile) through `ashley.runs.kube_api.KubeApi`, runs `app/ashley/runs/runner.py` in
    it, reads its one marked line from the log (`ashley.runs.envelope.parse`) and deletes the pod however the run ends
  - media jobs, the same pod machinery for a recording: a Strategy behind the locator, `ashley.runs.media.Media`, whose
    Null Object does nothing (so her frame and transcript tools are not offered); the one implementation,
    `ashley.runs.media_kubernetes.KubernetesMedia`, makes one pod per job (`ashley.runs.media_pod.manifest`) of its own
    image (ffmpeg, the Wyoming client and yt-dlp, `deploy/media/Containerfile`) through `ashley.runs.pod_log.PodLog`, which runs
    `ashley.runs.media_runner` in it. The pod fetches the stored file from the app, then makes a sheet of frames or a
    transcript: the file's embedded captions, else its sound sent window by window to the speech service
    (`ashley.inference.wyoming_stt`'s server, `WYOMING_STT_URL`). A third job fetches no file: given a YouTube video's id it
    runs yt-dlp for the English captions in a pod labelled `ashley.runs.media_pod.FETCH_LABEL`, the only media pod with public
    egress. Captions parse in `ashley.runs.captions`; the limits are data, `app/ashley/runs/media.json`
  - a run is a change in the tool loop's sense (`ashley.inference.model.ToolSpec.reads` false), so the turn's
    checkpoint records it started before it runs and it is never run again on resume
- **Who asks, how:**
  - her `run_code` tool (`ashley.tools.run_code.RunCodeTools`), offered per turn by `ashley.channels.turn_tools.for_turn`
  - the conversation routes, which serve a conversation's runs under her final answer
    (`ashley.runs.runs.Runs.in_conversation`, placed by `ashley.api.chat_runs.under_answers`, which uses the same `answer_of`); the page shows them with
    `app/web/src/rooms/her/RunDetails.tsx`
  - the turn loop, which follows each carried answer of hers with its runs in a compact form
    (`ashley.channels.history_runs.carried`, placed by `ashley.conversations.answers.answer_of`, budgets in
    `app/ashley/channels/turns.json`)
  - a bench's code pieces (`ashley.workshop.run_piece.run_piece`), and the bench routes reading each piece's latest run;
    a build123d run starts with the bench's measurements (`ashley.workshop.measurements_file.file_of`) and the print
    settings (`ashley.workshop.print_file.file_text`), and its report is read, with a verdict per check, the parts'
    roles (a reference part's form) and the print check's findings, by `ashley.workshop.model_report.report_of`

### Looks

- **Owns (the question it answers):** What did she see when she looked at a bench, and what does the bench look like?
  And what does a public page give a browser?
- **Where:**
  - `app/ashley/looks/`; the limits are data, `app/ashley/looks/looks.json`; the browser image is built from `deploy/look/Containerfile`
- **Pattern:**
  - the drawing: a Strategy behind the locator, `ashley.looks.looker.Looker`, whose Null Object draws nothing (so only an
    image piece can be looked at); the one implementation, `ashley.looks.kubernetes.KubernetesLooker`, makes one pod per
    look (`ashley.looks.pod_spec.manifest`) through `ashley.runs.pod_log.PodLog` (shared with media jobs), runs
    `ashley.looks.shooter` in it, reads its one marked line from the log and deletes the pod however the look ends
  - an Object Pool of size one in front of it, `ashley.looks.warm_looker.WarmLooker`: a look goes to the pod kept up by
    `ashley.looks.warm_pod.WarmPod` (one per cluster, a singleton under `Lease.run_on_site`) and takes a pod of its own
    when that one is busy or gone
  - the page it photographs is the client's (`app/web/src/rooms/workshop/look/`; it is ready once every model on it has
    drawn its frame, `app/web/src/rooms/workshop/solid/drawing.ts`), reached by a signed token
    (`ashley.looks.links`) and served by `app/ashley/api/look.py`
  - the record: Service behind the locator, `ashley.looks.looks.Looks`, Postgres implementation
    `ashley.looks.postgres.PostgresLooks` (table `bench_looks`, one row per tool call, tied to the person turn), a Null
    Object that raises; the bytes are in the Object store under `ashley.looks.keys.PREFIX`
  - the page browser: a second Strategy behind the locator, `ashley.looks.browser.PageBrowser`, whose Null Object reads
    nothing (so a page its site refuses stays unread); the one implementation,
    `ashley.looks.kubernetes_browser.KubernetesBrowser`, runs the same program in its `read` mode in a cold look pod that
    also carries the fetch label for public HTTPS (`ashley.looks.pod_spec.read_manifest`), through the same `PodLog`
  - Fit: the warm pod is the same runner kept running, not a second system; the page browser is the same browser and pod
    given a public page, not a second system; a second use of Code runs' pod machinery, not its `Sandbox` (text script, no network); not a bench piece (what
    she saw is history of a turn, not work product); not the files' prefix, which a sweep owns
- **Who asks, how:**
  - her `bench_look` tool (`ashley.tools.bench_look.BenchLookTools`), offered per bench turn by
    `ashley.channels.turn_tools.sources`
  - the conversation routes, which serve a conversation's looks under her final answer (`app/ashley/api/chat_looks.py`);
    the page shows them with `app/web/src/rooms/her/LookDetails.tsx`
  - her `bench_frames` keeps its sheet of a video's frames the same way (`ashley.tools.bench_picture`), counted with the
    looks against `max_looks_per_turn`
  - the page reader, for a page whose site refused the plain fetch (`ashley.tools.page_reader.FetchedPageReader`)

### Tidy

- **Owns (the question it answers):** Which passages of a bench's text pieces has editing left stale, contradicted, duplicated or
  as debris, for her to verify?
- **Where:**
  - `app/ashley/tidy/`; the bounds are data, `app/ashley/tidy/tidy.json`; the task `bench_tidy` has its own routes in `app/ashley/inference/routes.json`
- **Pattern:**
  - the record: Service behind the locator, `ashley.tidy.tidy.Tidy`, Postgres implementation `ashley.tidy.postgres.PostgresTidy`
    (tables `bench_tidy`, the piece versions the last finished pass saw and the time a running pass took the bench, and `bench_findings`),
    a Null Object that raises `ashley.tidy.tidy.TidyUnavailable`
  - the pass: `ashley.tidy.run.after_turn`, a structured reply from a cheap model (`ashley.tidy.pointer`) that code checks quote by quote
    before keeping it
  - Fit: the shape of Workshop's reactions (a trigger derived from state, the last-seen recorded), not a second Workshop log:
    a finding is a pointer about pieces, never a Command, and no piece changes by it; not Memory (a finding ends when its
    quote does); no singleton, since the turn that changed a text piece already marks the moment and a missed pass is made up by the next
- **Who asks, how:**
  - the end of a turn on a bench, which sets the pass going apart from her reply (`ashley.channels.bench_after.tidy`, called by `ashley.channels.respond`)
  - her `bench_read`, which lists the standing findings as `to_check` (`ashley.tidy.offer.to_check`, called by `ashley.tools.bench_tools.BenchTools`)
  - her `bench_dismiss` (`ashley.tools.bench_tidy.BenchTidyTools`), offered per bench turn by `ashley.channels.turn_tools.sources`

### Senses

- **Owns (the question it answers):** What is happening right now?
- **Where:** `app/ashley/senses/`
- **Pattern:**
  - Service behind the locator per sense
  - the first is `ashley.senses.presence.Presence`, from the `person` entities of each household's own Home Assistant
    (`ashley.senses.homes_presence.HomesPresence` over `ashley.senses.home_assistant_presence.HomeAssistantPresence`),
    unknown for a household with no house, with a Null Object answering unknown
  - what the house says just happened is `ashley.senses.wakes.Wakes` (Postgres `ashley.senses.postgres_wakes.PostgresWakes`,
    table `wakes`; a Null Object that raises): an event queue between Home Assistant's `POST /api/wakes`
    (`app/ashley/api/wakes.py`) and the `wakes` singleton, one wake per household and event id; the same queue holds
    the reminders she sets for herself (`ashley.senses.wakes.Reminder`, kind `reminder`), each due at its time, a
    repeating one's next occurrence stored as the last is settled, by a structured rule in the household's wall
    clock (`ashley.senses.repeat.next_after`: every N days to years, weekly on `weekdays`, monthly on the `nth`
    weekday, until a day), a reminder carrying where its words go (`Reminder.route`) and the tools its turn may use
    (`Reminder.tools`), and edited in place (`ashley.senses.wakes.Wakes.edit`)
  - the reads she repeats until something changes are `ashley.watches.watches.Watches` (Postgres
    `ashley.watches.postgres.PostgresWatches`, table `watches`; a Null Object that raises), a Type Object of kinds
    (`ashley.watches.kinds.Kind`, the registry `ashley.watches.registry.KINDS`, tunables and each kind's defaults in
    `app/ashley/watches/watches.json`): the `watches` singleton (`ashley.watches.job.run`) reads once per kind and
    person, judges against each baseline (`ashley.watches.judge.judge`), and stores a changed check as a `watch` wake
    together with the new baseline. Its one kind is `claude_session` (`ashley.watches.claude_session.ClaudeSession`),
    armed by `ashley.tools.claude_watching.watching` when `claude_start` or `claude_prompt` succeeds, which asks each
    person's `Bridge` for their sessions and tracks `status` and `seq` in Postgres; `bench_job` (`ashley.watches.bench_job.BenchJob`), which reads
    a group of bench jobs and wakes once when it settles; and `mail_inbox`
    (`ashley.watches.mail_inbox.MailInbox`), which reads a mailbox through the `Mailbox` port and answers
    `ashley.watches.model.Later` while it is still syncing, and which she arms as a sort: a watch carries a `brief`,
    is `standing` (each successful read moves its expiry on).
  - what she proposed and a person has not yet agreed to is `ashley.senses.proposals.Proposals` (Postgres
    `ashley.senses.postgres_proposals.PostgresProposals`, table `proposals`; a Null Object that raises): a Command awaiting
    confirmation, taken only from a later person turn of the conversation, within a time limit
    (`ashley.senses.proposals.refusal` over `ashley.senses.proposal_gate.gate`), or by its id for a tap
    (`ashley.senses.proposals.Proposals.take_by_id`). Its payload kinds are a Type Object
    (`ashley.senses.proposal_payloads`: a money rule, a reminder or a change to one, a watch that acts, a change to the house), stored as
    tagged JSON and grouped in topics, one pending proposal per person, conversation and topic; its callers are
    `ashley.tools.reminders.ReminderTools` and `ashley.tools.house_change.HouseChangeTools`
  - what a turn that had read outside words did without asking, and the lists it wrote, is
    `ashley.senses.outside_record.OutsideRecord` (Postgres `ashley.senses.postgres_outside_record.PostgresOutsideRecord`,
    tables `outside_actions` and `outside_writes`, both pruned by the write that adds the next; a Null Object that raises),
    written by `ashley.tools.outside.Outside` and read back for the receipts beside her reply (`Outside.receipts`, kept with her turn as `Turn.receipts`) and by `house_ask`
  - whether a consequential change follows from what the person asked is `ashley.tools.action_judge.ActionJudge`, asked by
    `ashley.tools.outside.Outside` for a `judged` tier (`ashley.tools.tiers`) through `ashley.tools.outside_judging`;
    `ashley.tools.action_judge_model.ModelActionJudge` answers under the task `action_judge`, and the Null Object, which asks,
    is what an unwired process sees; the person's words are read by `ashley.channels.judge_words.reader` (for a woken turn, from the turn that made the reminder or watch), and a source
    shapes a call's view and checks its recipients in `Tools.vetted` (`ashley.tools.house_vet`, `ashley.tools.mail_vet`)
  - what lands in, or leaves, the household's ledger is `ashley.senses.deposits.Deposits` (Postgres
    `ashley.senses.postgres_deposits.PostgresDeposits`, rows of `wakes` with trigger `event` and the table
    `deposit_reads`; a Null Object that raises), read by the deposit singleton (`ashley.senses.deposit_sense`, tunables
    in `app/ashley/senses/deposits.json`) through the Ledger (below), whose transactions
    `ashley.senses.ledger_transactions` turns into the records criteria are judged over (`ashley.criteria.record.Transaction`); a deposit
    or withdrawal (the rule's `direction`) matching an armed reminder's rule (`ashley.senses.deposit_rule.DepositRule`:
    payee, minimum and the conditions she composes, `ashley.criteria.predicates`, some measured against the payer's
    history in code) stores an ordinary once reminder in the same queue; with the rule's `judge` her own turn decides
    whether it is sent. `ashley.criteria` is a plain import, not yet a system: other senses (Home Assistant wakes,
    presence arrivals, a calendar) could judge by the same predicates over their own records
- **Who asks, how:**
  - Channels (who is talking on a shared device), through `services.get`
  - the `wakes` singleton's sweep also lets her react to a bench whose person has paused
    (`ashley.channels.wake.bench_reacts.BenchReacts`), a turn on the bench's thread (Workshop, Conversations) that
    Initiative lets out only when her reply says it is worth saying
  - the wake intake stores, and the wake adapter (`ashley.channels.wake.runner`) takes up and settles; a due reminder
    becomes her turn on the person's phone (`ashley.channels.wake.reminder.fired`), whose push the push singleton
    sends and records on the reminder (`ashley.channels.push.reminders.deliver`), unless its route is `quiet`
  - her reminder tools schedule, list, change and cancel (`ashley.tools.reminders.ReminderTools`, shaping in
    `ashley.tools.reminder_shape`), and `remind_on_money` proposes one that waits on a deposit or a withdrawal, as
    `remind` and `change_reminder` do for one whose turn acts, and `arm_reminder` agrees the latest proposal from a
    later person turn (`ashley.senses.proposals.Proposals.propose`, `take` on its reminder topic, which also holds
    proposed reminders and edits), taking her conditions as `conditions`
    (`ashley.tools.reminder_conditions`, defaults and limits from `app/ashley/senses/deposits.json`); a person's reminder routes list and cancel (`app/ashley/api/reminders.py`)

### Initiative

- **Owns (the question it answers):** Does what she would say on her own go out?
- **Where:** `app/ashley/initiative/`
- **Pattern:** a Strategy behind the locator, `ashley.initiative.initiative.Initiative`, deciding from structured fields
  of her reply, never its words; the first policy, `ashley.initiative.initiative.WorthSaying`, is
  `worth_saying` on `ashley.inference.reply.Reply` alone, and the arrival greeting's scored policy replaces it. A Null
  Object that never speaks
- **Who asks, how:** the turn loop, for every reply on a turn nobody asked for (`ashley.channels.model.Inbound.unprompted`),
  at the turn's end however it ends (`ashley.channels.unprompted.decided`, through `ashley.channels.storing.pushed` and
  `ashley.channels.storing.stored`, so the first runner and the resumer decide alike); a bench's reaction to its
  person pausing is such a turn, and a quiet one is left out of what a page shows (`ashley.conversations.quiet.shown`, also the count the conversations list uses)

### Errands

- **Owns (the question it answers):** What did she owe a person that she could not do for want of a tool source, and
  how did it go?
- **Where:** `app/ashley/errands/`
- **Pattern:** a service behind the locator, `ashley.errands.errands.Errands` (Postgres
  `ashley.errands.postgres.PostgresErrands`, table `errands`; a Null Object that raises), a work queue claimed with
  `FOR UPDATE SKIP LOCKED` whose rows move `due`, `running`, then `done` or `given_up`; tunables in
  `app/ashley/errands/errands.json`; the job is `ashley.channels.errand.job.ErrandJob`, a singleton under `Lease` that
  runs due errands through the tool loop under the `errand` task. Distinct from the outbox (things to say, deleted as taken) and Memory (what is
  true)
- **Who asks, how:** nothing calls it yet; the turn loop stores and tells errands and the `errands` singleton runs
  them (`docs/decisions.md`, "What she could not do for want of a source, she does once it answers, and says so next time")
- **A second job type, bench jobs:** work she hands to a worker from a bench (`docs/decisions.md`, "She hands a bench job to
  workers and stays with the person"). `ashley.errands.bench_jobs.BenchJobs` (Postgres
  `ashley.errands.bench_jobs_postgres.PostgresBenchJobs`, table `bench_jobs`; a Null Object that raises), tunables in
  `app/ashley/errands/jobs.json`. Its own table, since a job has no source and a turn starts several. Run by
  `ashley.channels.bench_job.BenchJobRunner`, a singleton under `Lease`: an `agent` job is a sub-agent loop
  (`ashley.tools.bench_agent`, `look_up`'s pattern, task `bench_job`) over the bench's tools narrowed by
  `ashley.tools.job_scope.JobScope`; a `claude_code` job is a session on the person's herdr bridge
  (`ashley.tools.bench_session`). Started by her tool `ashley.tools.bench_jobs.BenchJobTools`, shown as a `job` piece
  (`app/ashley/workshop/job_body.py`), told by a `bench_job` Watches kind (`ashley.watches.bench_job.BenchJob`), one
  watch per group of jobs

### Homes

- **Owns (the question it answers):** Which Home Assistant does this household reach, what is in its house and what can she
  change there (states, history, registries, configs, actions)?
- **Where:** `app/ashley/home_assistant/`; tunables are data, `app/ashley/home_assistant/automations.json` and
  `app/ashley/home_assistant/house.json`, and which changes need a person's OK, `app/ashley/home_assistant/irreversible.json`
- **Pattern:**
  - Service behind the locator, `ashley.home_assistant.homes.Homes`, implemented over the household's `home_assistant`
    connection (Connections, above) by `ashley.home_assistant.connected_homes.ConnectedHomes`: a keyed pool of one
    `ashley.home_assistant.homes.Home` per household, kept while its address and token are unchanged; a Null Object
    that reaches no house. It checks a new address and token with one `GET /api/`
  - each Home's house is a port, `ashley.home_assistant.house.House`, over neutral records, implemented over HA's REST and
    WebSocket APIs by `ashley.home_assistant.ha_house.HaHouse` (registries `ha_registry`, configuration changes
    `ha_changes`, one WebSocket command per connection `ha_socket`), with a Null Object that offers nothing and raises;
    a change is data, `ashley.home_assistant.change.Change`, whose operation key `irreversible` judges
  - each Home's automations are a second, narrower port, `ashley.home_assistant.automations.Automations`, over HA's REST API
    (`ashley.home_assistant.rest_automations.RestAutomations`), a Null Object that offers nothing and raises for a
    household with none (`ashley.home_assistant.homes.automations_of`). Not a tool: code decides when it writes (a
    person's Install), so no model sits between the decision and the house. Known duplicate: it is the House's
    automation configs; the Workshop's install moves onto the House port and this one goes (open work)
- **Who asks, how:** with the household each already holds: the everyday tools (`ashley.tools.everyday.HomesEveryday`),
  her changes to the house's setup (`ashley.tools.house_change.HouseChangeTools`),
  presence, room speakers (`ashley.home_assistant.media_player.play_for`), her automation tools on a bench (reads),
  the Workshop's install (`ashley.workshop.install_piece.carry_out`), and the connection routes' check
