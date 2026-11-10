# Decisions

**North star: one assistant for the household that is always there.** She keeps working when a site, an ISP or
a cluster goes down, and never becomes two assistants with two memories.

## Words used here

- **Site:** a physical location with its own ISP. A deployment runs on two sites (site A, site B) plus a third site
  that only witnesses.
- **Active site:** the one holding the writable database. Only it runs singletons.
- **Singleton:** anything Ashley does on her own initiative rather than in answer to a request: the HA event
  listener, schedulers, reminders, proactive behaviour. Run twice, she says everything twice.

## What she's for

Useful like a real assistant, fun and cool like Jarvis, but named Ashley (the name began as AHSLI, Automated Home
System with Lifelike Intelligence).
HA-based Ashley answers a wake word and forgets; the two gaps that matter most are **initiative** (she never
speaks first) and **conversation** (no flowing back-and-forth that starts at the right moment, on whichever medium
suits it). Next come long-term memory, knowing who is talking, and replying on more than one channel. Reach beyond
the house is wanted but comes later.

## Per person by default

What she can reach, what she knows and how she behaves is set per person, never written for one named owner:
memory, settings, connected accounts and tools (each person's own Claude Code, calendars, Discord), how often
she speaks up and their quiet hours. A person-owned thing keys on the person a login, account or voice maps to.
Household-wide settings exist only for what is genuinely shared: a room's satellite, a shared channel, the
house itself through HA. A design that needs "only the owner" is asked again as "only the person who connected it".

## Whether she speaks unprompted is decided in code

A model call is stateless, so a prompt told to speak "when it makes sense" either always speaks or never does.
Code computes a score from measured facts (time away, hour, who else is home, when she last spoke, whether
anything is worth saying) and the model's structured `worth_saying` and importance fields; she speaks when it
clears a threshold. Weights and thresholds are data, tuned from real use.

- **She never repeats herself:** what she recently said unprompted goes into the prompt as already said, so
  greetings and asides don't go same-y the way the old hardcoded greeting did.
- **Asides (unprompted wit) are the lowest importance**, capped per person per day in code, and never interrupt
  that person's focus: not while they are on a call, have just been prompting a Claude Code session themselves, or
  it is late by their own quiet hours. A session merely running is not focus: a person can have sessions working almost
  all the time, overnight and while away.
- **Rejected: leaving the judgement to the prompt.** No history, so no rate.

## A conversation is one thing; channels carry it, several at once

A conversation has participants, history and a state (open, idle, closed), and belongs to no channel: it
records the one it started on, and any can carry it later. Voice satellites, text, push and the tablet are channel
adapters, and any number can carry one conversation at once in either direction: speak to the kitchen and send a
photo from the phone, and both land in the same exchange.

- **A reply is rendered per channel.** The model returns one structured field per medium (`spoken`, `text`, ...);
  code picks which to deliver and where, so a long answer can arrive as text while the room hears "it's on your
  phone".
- **Each channel declares its audience** (who can hear or read it), which private-answer routing checks: a
  Discord DM is its owner's alone, a shared Discord channel is the household's, a kitchen satellite is whoever is
  home.
- **Channels planned:** voice satellites, Discord (where a household may already talk), the web app with web push,
  and an MCP server so Claude Code sessions can ask her things or tell her to remember them, authenticated as
  their user.
- **Spoken words differ from written ones.** Memory, text and prompts use real spellings (the pet's name as written); the
  voice channel applies the household's pronunciation words on the way out, so TTS quirks never reach memory or
  text.
- **She can open a conversation herself**, through the same path: initiative picks a person, a moment and the
  channels.
- **Conversation kind (command, chat, brainstorm) is set in code** and decides length, model and channels. Today's
  "two sentences, absolute" holds for commands only.
- **Open, idle and closed are derived, never stored**: a function of the kind, the last turn's time and the
  database's clock, with the thresholds per kind as data (`app/ashley/conversations/policy.json`). Idle still takes
  a turn and reopens; closed refuses it, and the channel starts a new conversation. Nothing has to run for a
  conversation to close, so there is no singleton to miss a tick across a failover.
- **Closing is not forgetting.** A conversation is the unit turns are stored in, the memory write job's idle trigger
  and a divider in her history; what a reply sees does not stop at its edge. A reply carries the speaker's latest
  turns with her across conversations (for an unknown speaker, only this conversation's), each marked with when it
  was said (`(Sun 1 Nov 2026 10:22)`, see "Every time she is shown is a household-local stamp") and, when its
  conversation's thread is not the reply's own, where (`(Sun 1 Nov 2026 10:22, bench <id> "<title>")`; `web chat`,
  `a device`, `the phone` or `Discord` for the other threads, read from the thread and the bench's title, never from
  turn text). Those said elsewhere come first in her prompt, then those said here, each in time order, so the last exchange before the message is this thread's; the prompt says a marked turn was said elsewhere and the last message here, so a short "yeah" answers what
  was last asked on this thread, not the newest turn in view. It also carries older turns matching the message, found by their words, beside the facts recall finds. A
  conversation she does not remember (an eval harness's) is carried only within itself. Both
  budgets are turn counts per kind, data in `app/ashley/channels/turns.json`; the recent one also caps a
  conversation that never goes quiet. `respond.done` logs how many of each were carried and how many the filter held
  back.
- **Every time she is shown is a household-local stamp.** Wherever she is shown when something happened, it is
  `ashley.stamp.stamp`: `Sun 1 Nov 2026 10:22`, weekday, date and 24-hour time in the household's zone. The clock now
  is in her system prompt (`persona.facts.when`) for her to do the arithmetic against. The places: carried and
  relevant chat turns (`(<stamp>)` prefix), remembered and standing facts (`(learned <stamp>)` from
  `Fact.valid_from`, the only time a fact holds: a correction is a new fact with a new `valid_from`, so it is also
  when it was last confirmed), `bench_read` (each recent command's `at`, each piece's `changed_at`),
  `bench_read_piece` (`changed_at`), `bench_last_run` (`ran_at`), `house_automations` (`last_triggered`), and the bench reaction turn's list of changes. The
  bench tools take the zone from the household (`ashley.people.zone.zone_of`) and leave a time out rather than show
  it in a guessed zone when People cannot answer. A stamp is a function of the stored time and the zone alone, so a
  line shown again is the same bytes. That keeps history a cached prefix (the tail breakpoint, see the cache layers
  decision), and standing facts, which sit in `stable`, stay stable.
  - Rejected: relative ages (`3 days ago`). They change with every message, would have broken a cached `stable`
    for standing facts, and she can subtract.
  - Not stamped, because they already carry an absolute local time or none that matters: reminders (`at`, the due
    time, local), Sure transactions (`date`), a bench's `bench_shelf` pieces. Not stamped, queued in `open-work.md`:
    a Home Assistant entity's state carries no `last_changed`.
- **Every carried turn passes the rule facts pass** (`ashley.hearing.MAY_HEAR`, in the same SQL shape). Each turn
  records who could hear it where it was said: private to the speaker on an owner-only channel, or when her reply went
  to their phone; shared on anything the household could hear. So a turn said where only its owner heard reaches
  only that owner's owner-only replies, and a shared room hears only turns the household could have. Turns from
  before this was recorded are private to no one, so no reply carries them.
- **Rejected: a dynamic timeout** (still a wall, just moved); **the model deciding when a conversation ends** (a
  stateless call cannot judge it consistently, and code can); **never closing** (leaks across audiences, and loses
  the write trigger). Compacting old turns waits until measurement says the budget hurts, and so does embedding
  turns for the relevant search, which is full text only.
- **People, participants and speakers carry `household_id` in every reference**, so the schema itself refuses a
  person in another household's conversation.
- **Rejected: a reply bound to the channel it came in on.** Long answers would have nowhere to go.
- **Rejected: a stored state column moved by a sweeper.** A singleton that misses its tick leaves a conversation
  open forever, and two clocks (the sweeper's and the reader's) can disagree about the same row.

## Every channel shares one turn loop; adapters live at the edge

An adapter turns what arrived into an `Inbound` (household, thread, text, kind, medium, audience, speaker if the
channel names one, whether it is shared, place) and delivers the `Outbound` that `channels.respond` returns. The loop
finds the speaker and the conversation, stores both turns, builds the prompt, and runs tool calls until she answers.

- **A thread is the channel's key for where a message came from** (`device:7`, a Discord channel id). Conversations
  maps threads to conversations, many to one, because the closed check and the switch to a new conversation must be
  one transaction.
- **The first adapter is `POST /api/messages` for signed-in devices:** a device sends text and gets her reply in the
  response, rendered for its medium. The eval battery, the hallway tablet's page and any satellite bridge can all
  use it. A device token is issued once and only its SHA-256 is stored.
- **On a shared device the speaker is the one person home**, when exactly one is (`Presence`); otherwise unknown. A
  personal account names its person through an explicit account mapping, never a guess.
- **No text holds a NUL (U+0000), which no Postgres text column stores.** A wire model declares every free-text field
  `ashley.text.NoNul`, so a person's or device's NUL is a 422; Discord's route drops such a message (`nul`, logged
  `discord.ignored`); and a NUL in what her model writes (`Reply.spoken` and `text`, the memory writer's fact text) is
  removed as it is read, since her words must still reach the person.
- **A call carries only what this reply needs.** Owning the pipeline means the prompt is assembled per message, not
  fixed: household facts are retrieved for the message rather than sent whole, tools are offered by what the moment
  can use, a sense is read through a tool when the reply needs it rather than pushed into every prompt, and work that
  needs a large tool set or a long loop goes to a sub-agent (another caller of `Inference.step`, with its own task and
  routes) so the main call stays small. Stable sections come first and the moment last, so the cached prefix holds:
  `persona.system` returns a `SystemPrompt` (`stable`, then `moment`: what she remembers, what was said before, the
  clock and who is speaking), and `AnthropicProvider` puts one cache breakpoint on the last tool, one on the end of
  `stable`, and one on the last block of the last turn. `moment` is sent after the history, not in the system prompt,
  so the history is a prefix that survives from one message to the next (the clock in the system block put it
  before every message and no history prefix could be read): on Anthropic the last block of the last user turn,
  after the tail breakpoint (a new user turn when the last turn is not a user's), labelled `MOMENT_LABEL` ("not words
  anyone said"); on Chat Completions (Gemini, ChatGPT, local) a user message after the last entry. Measured on one
  conversation's two consecutive messages (~12K-token prefix): Anthropic read 8,173 of 11,995 tokens before and 11,944
  after, on both Sonnet and Opus; Gemini's implicit cache read 0 before and 8,706 of 10,553 after. The mid-conversation
  system role (prompt-caching.md) is not used: it is not available on every model she routes to. The tail breakpoint
  is what lets the next tool round of a reply read the history this round wrote; without it each round re-paid the whole history (a measured 4-round turn: reads stayed at
  the system prompt's size while uncached input grew by a round's content each time). Each Anthropic call logs
  `inference.cache_layers`: a hash of the tools, the stable text and the turns, with the cache tokens read and written,
  so a miss inside the TTL is attributed to the layer whose hash moved. Rejected: the moment in the system prompt,
  the mid-conversation system role, top-level automatic caching (the
  explicit marker keeps all three breakpoint positions in one place and works on any SDK version); the one-hour TTL
  (a reply's rounds are seconds apart); the beta cache-diagnostics header (the layer hashes answer the same question
  without a beta).
  The prompt is a record, not a `str` subclass: a `str` that carried the layers lost them to any concatenation,
  silently, and the cache stopped with no error. Rejected: a `str` subclass carrying `stable` and `moment`.
  Anything code can decide (who is talking, whether to speak, a format rule) is decided in code and costs no tokens.
- **Tool calls and results live only for one reply.** The conversation stores what was said; the house is read
  again next time rather than trusting a stale result.
- **Tools that belong to one context are added for the turn, by the `Inbound`'s fields.** Every turn is offered the
  locator's `Tools`, the catalogue every turn shares; `ashley.channels.turn_tools.for_turn` adds the sources this
  turn's fields call for (`Inbound.bench_id`: that bench's tools; `Inbound.opens_benches`: opening a bench), each built
  for the one turn, after the shared catalogue in one Composite whose shared part is keyed `everyday`. A turn that
  calls for none gets the locator's `Tools` itself, so the voice, Discord, the kiosk and its controls see no change. The
  loop runs every call through that one source. A field is set by the adapter that knows the context, never read from
  what was said, and the next per-context tools (her moving the page, herdr for the person who connected it) are a
  field and a line in `for_turn`. Rejected: a method on `Tools` taking the turn, which every source would have to
  implement and ignore; and a per-context catalogue in the locator, since a per-turn source holds the turn's owner.
- **Every tool is offered from the first step, and a call to one runs as asked.** Each tool says whether it only
  reads (`ToolSpec.reads`), and a tool not known to only read, or a name the loop was not offered, is a change; the
  repeat rule uses it (a change that ran lets a read made before it run again). Her house reads are their own tools
  (`house_state`, `house_find`, `house_history`, `house_ask`); an action that only returns data, or a script in the household's `reads`
  setting (its Home Assistant connection's settings), is asked through `house_ask`. She had reached for writes on read asks ("is the porch light on", `HassLightSet`); what
  watches that is the house eval's attempted writes on its `read_only` cases (main before any gate: 1 of 22 runs in one
  eval, 0 in another), and item 8's prompt cuts are measured by it. The eval keeps its own read allow-list
  (`house_reads.json`) rather than reading `reads`: a guard that trusts what it checks cannot fail.
  - Rejected: a `declare_change` tool she must call before a change. A self-declaration by the model that errs
    protects nothing and costs steps: she called it on 8 of 12 information asks with `what` "none" or "nothing", and
    on action asks declared "none needed" and then made the change.
  - Rejected: a required `change` argument on change tools. It was filled on every call including spurious ones, so
    it refuses nothing.
  - Rejected: offering change tools only after a step whose `Reply.changes` says the turn wants one. In the house eval
    on chat, action asks never sent it: after a read round she looks for a tool to act with, not a reply, and read
    until the step limit (2 of 6 action runs reached their tool, main 6 of 6).
  - Rejected: a classification call before every turn, which costs every turn a model call to save a step on action
    turns only.
  - Rejected: words in the person's message, or a pattern over tool names; HA's annotations already say.
- **What she always knows about a household is its profile** (who lives there, pronouns, pets, how calendars and
  lists are named), a column set by the admin CLI, until standing facts in memory replace it. None of it is in the
  repo.
- **A reply that only says she will check goes out at once, and the answer follows as a later reply.** The model says
  so in a field (`Reply.answers` false); on a channel that delivers later replies (`Inbound.later`: voice, Discord and web chat)
  the turn returns it and finishes in the background, storing the answer as her turn. About a second and a
  half to her first words rather than four or five. `POST /api/messages` answers in its HTTP response, so there the
  step is asked again with tools required instead.
- **The held line is her turn, stored before it goes out and marked `follows`** (`NewTurn.follows`, the `turns.follows`
  column, `ChatTurn.follows` on the wire), on every channel. It was said, so the conversation, history carrying, memory
  and reading back all hold it, and a page keeps it with the answer under it. The mark is how anything reading the
  conversation knows the answer is still to come: a page shows her thinking after it, and a person's line followed only
  by held lines is still owed an answer (`app/web/src/rooms/her/owed.ts`). On a turn kept in `InFlight` it is stored by
  `InFlight.said`, under the turn's claim and renewing it, so a runner that lost the turn never adds it after another
  runner's answer; a resumed turn never holds, so it is stored once, by the runner that held. A conversation refusing
  it is logged `respond.turn_unrecorded` and the line still goes out. Every wired model takes her two lines in a row in
  the carried history (probed through the app's providers on each chat model in `routes.json`).
  - Rejected: keeping it unstored. The web page drops a line the conversation lacks once the answer is stored, so
    "let me check" vanished under the person's eyes; Discord kept the message while the conversation, and so her
    history, lacked it.
  - Rejected: telling a held line by its text or by position (her line before her line). Behaviour keys on a field.
- **A long turn holds by the clock, in her words.** A turn that only calls tools never writes a reply, so `answers`
  false cannot fire on it (a six-round look-up took 76 s with nothing said). On a turn that can hold, every tool she is
  offered takes one more required argument, `aside`: one short line about what she is doing, which the loop strips
  before the call reaches its tool and leaves out when it matches a repeated read (`ashley.channels.aside`). Before each step, once the turn has run past its kind's
  `hold_after_s` (`turns.json`) with no answer, her latest aside goes out as the held reply (`respond.held
  by=aside_budget`) and the turn resumes under `auto`, as a held turn does. No aside, no extra line; one held line per
  turn whichever way it held. A round's calls run under the same clock: when the budget passes while they run, her
  latest aside is held then, and the calls run on, one at a time, inside the `Held` (`running`) for `resume` to await,
  so a 20 s `look_up` holds at the budget rather than when it ends. A model step runs under the same clock: when the
  budget passes while it is in flight, the latest earlier aside is held then, and the step runs on, never cancelled
  or asked again, inside the `Held` (`stepping`) for `resume` to take as that round's step (a bench step ran 92 s and
  the person saw nothing).
  - The aside is the held line, so it is written as one: a whole sentence that stands alone, not a label for the call
    (live, a held line read "And the choices note.", a fragment of the call it rode on). The aside and a fast cascade
    step's own `holding` field (open-work item 6) are different fields; what they share is the builder of the held
    `Reply`, `aside.holding`.
  - Rejected: a `holding` field on `Reply` as the source of a held line on a long turn. A step that calls tools has no
    `Reply`; the required argument is the field that exists on that step.
  - Rejected: a `hold` tool carrying the line. It is optional, so she can skip it, and skipping a holding line is the
    defect; a required argument on the calls she makes anyway cannot be skipped.
  - Rejected: text beside the tool calls (Anthropic's text block, Chat Completions' `content`). It is prose, not a
    field, and OpenAI-compatible servers often send none beside tool calls.
  - Rejected: a field on `Reply`. A step that calls tools returns no `Reply`.
  - Rejected: canned "one moment" text when there is no aside. Her line is in her voice or there is none.
  - Rejected: a timer that delivers mid-round through its own path. The held return already delivers; the loop
    returns it with the round still running instead.
  - Rejected: running a round's reads concurrently to close the gap. It shortens a round of several reads but never
    bounds the hold: every late hold measured came in a round of one call (`look_up`, up to 20 s), and concurrent
    reads beside a change would need their own ordering rules.
- **One aside per round is the held line: the first.** Calls made together carry asides written as a sequence, and
  the last read as a fragment ("And what the last probe found."). A text page shows her thinking without one, so
  brainstorm holds at 60 s, and its line is about the work, never what she is reading.
- **A turn answers by its kind's `deadline_s`, under the route's timeout.** The web app's HTTPRoute cuts a request at
  60 s (`kustomization/ashley-app/patch-httproute.yaml` in the cluster repo), and a cut POST loses the reply on the
  page. Before each step, once the turn has run `deadline_s`, the step is the closing one, under tool choice `none`,
  logged `respond.deadline`. The clock is read between steps, so a round that began before the deadline still
  finishes: `deadline_s` plus one round plus the closing step must stay under 60 s. Chat and brainstorm take 40 s: the
  76 s turn's rounds averaged about 12 s and its closing step about 4, so 40 + 12 + 4 = 56. Command, the kiosk's and
  satellites' kind, takes 20 s for its four rounds. A held turn has already answered its POST, and the deadline still
  bounds its total work. One step slower than its route's `timeout_s` (30 s on chat, 120 s on brainstorm) can still
  overrun; that is the route's timeout to tune, not the loop's.
- **A bench turn gets windows, not a cut.** At deadline_s, a turn still calling tools takes a fresh window, up to its
  kind's `windows` (brainstorm 2), counted in `Checkpoint.windows`. A closing reply whose `answers` is false (a promise)
  is never stored: it takes a window, or is asked once to say where things stand (a person once waited over an hour on a promise).
- **A turn escalates once, from its fast route to the stronger one.** On a kind whose limits say `escalates`
  (`turns.json`: chat) and a channel that takes replies said after the response, two things send the turn on to the
  route `brainstorm` uses, both decided in code (`ashley.channels.escalation`). **A:** it reaches `max_tool_rounds` or
  `deadline_s` with no answer, in place of the forced close on the fast model. **B:** the fast model's `Reply.escalate`
  is set, a nullable field whose value is the line she says meanwhile (a reply with the field set carries nothing else
  that is used). The turn goes on from the entries it has, so the stronger route sees what the fast one found, under
  `brainstorm`'s limits with the kind's own reply length (`ashley.channels.escalation.of`), its rounds counted on from
  where the fast route stopped. Its answer reaches the person as the held one's does: stored as her turn, or queued
  in the outbox, as her "getting back to you". A person who has not had a held line gets one first, `aside.holding` of
  the reply's `escalate` (B) or her latest aside (A), returned as a `Held` by `escalate`; one who has, goes straight on.
  The stronger route ends a turn as any other does: a wrap-up at its own limits, so a turn still never ends silent.
  - **One escalation, never a chain.** The trigger is saved in the turn's checkpoint (`Checkpoint.escalated`, set
    before the line goes out) and the loop reads it back (`Steps.escalated`), so a pod lost mid-escalation is resumed by
    any pod on either site on the stronger route, once, and a stronger route's own `escalate` or limit is not a trigger.
  - **Its calls are the ledger task `escalated`**, whose routes are `brainstorm`'s by reference
    (`"escalated": {"like": "brainstorm"}` in `routes.json`): the spend ledger shows the rate, cost and outcome of
    escalated calls apart from chat's and brainstorm's, and re-tuning the stronger model is one list. Logged
    `respond.escalated` with the conversation, trigger (`a`, `b`), rounds, `from_route`, `to_route` and duration_ms.
  - **Only chat escalates.** Command and voice answer a person standing there and an Opus-length answer minutes later is
    worse than the wrap-up; it is a flag per kind in `turns.json` should measurement say otherwise. A turn at its limit
    with a held line to give and no aside closes on the fast route as before, since a bare escalation would leave the
    POST waiting. A turn whose page has moved to a bench is that bench's and does not escalate.
  - Rejected: a learned router in front of every call (RouteLLM, Not Diamond): trained on general chat preferences
    rather than her tasks, and a hosted one adds a round trip on every voice turn. A cascade pays a second call only on
    the turns that need it.
  - Rejected: a separate `holding` field beside `escalate`. The field being set is the decision and its value the
    line; two fields could disagree.
  - Rejected: deciding to escalate from her text or the question's wording. A limit is a count and a clock; B is a field.
  - Rejected: forcing the close on the fast model at the limit, which is what produced a turn with nothing to say; the
    wrap-up stays as the stronger route's last step.
  - Rejected: a model name in the loop, or a second copy of `brainstorm`'s route list under another task.
- **A channel that pushes is an outbox** (`ashley.channels.outbox.Outbox`, table `outbox`): any pod adds a reply for a
  thread, and the singleton holding that thread's channel takes it every `poll_s` and delivers it. The satellites
  singleton plays it on the satellite's room speaker, else as an announcement on its own media player (queued behind
  one already playing); the Discord singleton posts it in the channel. A take deletes what it returns, so a reply is
  said at most once, since a late duplicate is worse than a gap; one older than `stale_s` is dropped. Initiative, the
  arrival greeting and an errand's result reach people through it too.
  - Discord goes through the outbox like voice, rather than a REST call from the pod that made the reply: one path for
    every channel, and only the Gateway singleton holds a client.
  - **Long work is three layers, and this is only the last.** The outbox says something on a thread now. Which person,
    which channel and whether now is a good moment is Initiative's; a result nobody has heard yet is held on its
    errand until it is told (open-work, "Errands"). An answer that outlives `stale_s` is stored on the thread and its push dropped; once errands land
    it is told at the next chance.
  - Rejected: a hook that delivers the early reply while the turn runs, with the answer as `respond`'s return value.
    Each adapter would need that hook and, for Initiative, a second way to push: two delivery paths per channel. A new
    wake on the same satellite also cancels the run, and the answer with it.
- **Web chat is a person's own thread, `person:<id>:web`** (audience `owner`, the person the speaker), and no
  singleton holds it. A held reply carries `follows` and is stored as her turn, marked so; the answer is stored after it
  and never queued in the outbox
  (`Inbound.later_by`), and every page open on the thread reads the conversation back when Live says the thread got a
  turn, so two tabs of one person both show it. While a page has no live feed it reads the conversation back slowly
  instead.
- **A run shows under her final answer to the message that asked for it.** The conversation routes (web chat, a bench's
  talk and the kiosk share them) read the conversation's runs in one query (`Runs.in_conversation`) and put each on
  her last turn that is not a held line and records answering that person turn (`Turn.answers`,
  `ashley.api.chat_runs`), so a held line carries none; a run waits for its answer while the person turn has none. A
  person who types while she is still working gets each message's runs under the answer to that message. Her turn
  records the person turn it answers (`NewTurn.answers`, the `turns.answers` column; the held line and the answer both
  carry it, a resumed answer too; null for a turn answering none; a person turn with it is refused), set where
  `respond` stores her turns. It is not on the wire: the page is given the runs already placed. Migration 0037
  backfilled older turns by position only where unambiguous (held lines and at most one answer between two person
  turns); the rest stay null and show no runs. The page shows each as a collapsed disclosure
  ("Ran Python · exit 0", or timed out, out of memory, failed, outcome unknown, no result recorded), opening to the
  script, input, output and files (`app/web/src/rooms/her/RunDetails.tsx`), the same component on all three surfaces.
  A run made by a bench's Run command (`NewRun.bench`) is its piece's: it shows on the code piece only, never under her
  line in the bench's talk, even when her `bench_run` call made it; a `run_code` call from the talk still shows there.
  Output is already cut to the sandbox's limits when stored. Runs unreadable is `unavailable`, like the turns.
  Rejected: a route per run, one request per turn on a page that reads the whole conversation back.
  Rejected: placing by position (the last of hers before the person's next turn). With a second message typed
  meanwhile it puts the first message's runs under its held line and reads the answer to it as the second's.
- **Her lines on the web render as Markdown, a person's stay literal.** The page parses her `text` into a tree
  (`app/web/src/rooms/her/markdown.ts`) and builds elements from it, never HTML: paragraphs, lists, bold, italic, inline
  code, and links only to http, https and mailto. A heading is a bold paragraph, a table its source text, a fenced block
  a scrolling monospace block, coloured as below; raw HTML is text. The same component serves the kiosk.
- **Code is coloured by highlight.js, loaded on first use** (`app/web/src/highlight/`). A fenced block in her lines and
  the body of a code piece both go through `CodeBlock`, which shows the text plain at once and colours it when the
  highlighter's chunk arrives, so the first paint carries none of it. Ten grammars, each its own chunk: Python,
  TypeScript, JavaScript, YAML, JSON, bash, SQL, C, C++ (also the Arduino tag) and Markdown. A fence's first tag names
  the language, and a tag we do not colour (`rust`) stays plain. With no tag, and for a code piece, every grammar is
  tried over the text and the best fit is used when its relevance is at least 4, else the block stays plain: real code
  scored 4 to 16, prose, directory listings and logs 3 or less. Code-run output and the piece editor stay plain. The
  colours are the house tokens (`app/web/src/highlight/highlight.css`), not a stock theme. Measured on those ten
  languages, in isolated esbuild bundles: highlight.js 27 KB gzip against Shiki's fine-grained build (JavaScript regex
  engine, one CSS-variable theme) 183 KB, and a cold first highlight, import included, of 12 ms against 71 ms for
  Python, 12 against 43 for YAML and 17 against 1,000 for C++ (node, median of five). Rejected: Shiki, for the size and
  the C++ grammar's cost; a per-piece `language`, which needs a field on every piece ("A piece is work product"), so
  detection stands in; an overlay editor, since a plain textarea keeps selection, copy and the edit flow.
- **Tap to talk in a page is a transcript, then a typed message.** The page records 16 kHz mono PCM with Web Audio
  (no codec on either side, and the format the voice pipeline already hears), posts it as one WAV, and sends the words
  it gets back through its own typed route with `said_aloud`, so the thread, the `Inbound` (its `medium` still the
  channel's, text) and her text reply are the typed path's.
  The audio lives in memory for the one transcription and is never stored; an utterance is capped at `max_ms`
  (`app/ashley/channels/spoken.json`), served to the page so it stops recording there, and the body at that many
  samples plus a WAV header. The page also stops by itself when the person stops talking: energy per 20 ms window
  against `quiet_rms` (`spoken.json`), with the Echo's `speech_ms` and `silence_ms` read from `voice.json` and served
  in the same limits, since the browser has no VAD model. Rejected: one route that transcribes and answers, which needs
  its own reply envelope and loses the person's words when the reply fails.
- **Spoken to, she decides whether to answer aloud**, as she decides when and where to speak elsewhere. A tagged message offers `Reply.aloud` in one line of `# Now` (`ashley.channels.aloud.offered`), as a spoken
  turn offers `to_phone`; set, her `spoken` is stored on her turn beside `text` (`Turn.spoken`), in the same insert,
  and the page that sent the message plays it from `GET /api/chat/turns/{id}/voice` (the kiosk's
  `/api/kiosk/turns/{id}/voice`), synthesised on the fetch with the household's words, fetchable for `voice_s` and
  only on the caller's own thread. Only the tab that sent it plays it; it primes its audio inside the record tap,
  since phone browsers refuse audio a page starts later, and shows a play control when playback is still refused.
  Rejected: speaking whenever tagged (the choice is hers, and a list or a link does not work heard); setting
  `Inbound.medium` to spoken (the thread stores and shows `text`, and every medium-keyed path, `to_phone` and the
  stored field included, would treat the page as a satellite); a Clips row with a URL token (a page can send its own
  cookie, and a second table would escape the turn's transaction and its forgetting).
- **Her behaviour is measured by what she did**: `respond.done` carries `changes`, `closed` and `answers`, and
  `tools/bench_outcomes.py` computes the outcome measures from them. A wording fix is not a fix until they move.
  A real bench conversation is measured again through the bench replay (`python -m ashley.evals bench-replay`): it is
  captured from production into a directory outside the repository, asked again ask by ask through her turn loop on a
  bench rebuilt from its command log in a throwaway database, and scored per ask from records (time to a clean run,
  runs, changes outside the ask's pieces, measurement rows rewritten with no new source, the last run's overlaps and
  failed checks, looks at a photo); what only her words carry (asking to look, asking what the real thing looks like,
  claiming a fix, asking for a row again) comes from a grader call's structured fields (task `eval_judge`), reported
  apart. The production conversation is scored the same way, its runs executed again since a bench keeps only its
  latest runs. Rejected: a model-piece screenshot in the replay, since the look pod draws the app's page and no app
  serves the throwaway database; she is told only image pieces can be looked at, and a captured photo over the look
  limit is re-encoded to fit.

## Open screens learn what changed through Live

Every open screen holds one Server-Sent Events stream, `GET /api/live`, fed by the Live service: Postgres LISTEN/NOTIFY,
since every pod on both sites already reaches the one writable primary, so a NOTIFY from any pod reaches every pod's
listener, and a failover is the listener reconnecting to the new primary. Each process holds one listening connection
and fans out to its own streams; nothing about a screen is kept beyond its open connection.

- **It carries ids and states, never text:** her state in a turn (`listening`, `thinking`, `speaking`, `idle`, named by a random
  turn token; a satellite's wake publishes `listening` until the transcript and `speaking` from handing over the reply
  to the room until an estimate of its playing, `voice.json`'s `playback`, since neither a satellite nor a room speaker
  reports its end), "this thread of yours got a turn", "a turn on this thread of yours ended with no reply", "this bench of yours changed" and "she moved your page to this
  room or bench". A page refetches what it shows; the feed is a nudge, not the data.
- **Who sees it is the channel's audience.** A turn on an `owner` channel (a DM, the person's web chat) is shown to that
  person only; one on a shared channel (satellites, a shared Discord channel, devices) to everyone signed in to the
  household. Neither says which room or who is talking. A shared channel's stored turns are announced only to the
  screen of a device that has one (the kiosk, `GET /api/kiosk/live`), never to a person's.
- **A device is a viewer of its own kind.** A person's screen is shown the household's shared events and their own,
  never a device's; a device's screen is shown the shared events and its own thread's turns, never an event of any
  person's channel. Both cookies stay strictly apart, so the feed has one route for each.
- **Losing an event costs a refetch, never a turn.** Publishing never waits; a stream that falls behind drops what is
  waiting for one `resync`, as does every stream when its pod's listener reconnects. A state carries `at_most_s`, since
  the `idle` can die with the pod that ran the turn. A stream ends after `stream_s` and the page reconnects, which
  checks its session again. Heartbeats every `heartbeat_s` (20 s) keep Cloudflare from closing it: its proxy read
  timeout is 125 s.
- **`speaking` is on the wire but nothing sends it yet.** A satellite plays the clip URL it is handed, and when it
  starts and stops is not reported back; the clip route streams faster than real time, so its end is not the end of
  playback.
- **Rejected: polling per room.** Every open screen would ask every few seconds whether anything happened, mostly to
  hear no, and a screen would learn of a kitchen question only at its next poll.
- **Rejected: Redis pub/sub or an etcd watch.** Redis is a new stateful service on both sites with its own failover to
  get right, for what the database we already fail over does. The etcd is the referee's, sized and tuned for three
  members' votes across a high-latency link, and every pod would hold a watch on it; a user-facing feed has no business on
  the quorum that decides failover.
- **Rejected: the outbox.** It is a queue whose items are claimed once; a screen's events go to every screen.

## Web push

Web push is a channel like any other: its thread is `push:<person id>`, and one singleton under the lease `push` takes
that prefix from the outbox and sends each reply to every browser the person subscribed in the devices room. Nothing
is pushed from a request pod. Her VAPID identity is `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` and `VAPID_SUBJECT` from
the deployment's secret store (`ashley-push`); unset or not one key pair, the push routes answer 503, the singleton does not run,
and the rest runs.

- **"It's on your phone" keys on a field.** `Reply.to_phone` means the written reply holds what doesn't work aloud (a
  link, a list, something long to keep). Code offers it per call, in one line of the prompt, only on a spoken channel
  to a known speaker with a subscribed browser, and honours it only then: `text` goes to their push thread, `spoken`
  plays as usual and says so, and `text` is stored as her turn, since it is what they will refer back to. Otherwise
  the field is ignored.
- **A notification may carry her words** (title "Ashley", the reply as plain text, cut to `push.json`'s `body_chars`, a click opening
  `/`; a link shows as its label): Web Push encrypts the payload to the browser's own keys, so the push service relays it without reading it.
- **A browser belongs to one person.** Subscribing an endpoint someone else had moves it; the devices room shows "on"
  only when the server says this browser is the signed-in person's.
- **Only the browsers' own push services are accepted as endpoints** (`push.json`), since the server POSTs to whatever
  a browser hands over, and no redirect is followed. A service answering 404 or 410 forgets that browser; any other
  failure keeps it.
- On iPhone, web push works only for the app added to the Home Screen; the devices room says so.
- **A woken turn routes itself: a sense is an input.** She works out where a thing goes by its type and urgency, and
  may decide to route it nowhere. So a turn she was woken
  for (`Inbound.unprompted`) on a thread other than the person's phone thread is offered the same `Reply.to_phone`,
  and code never pushes on its own. She is given facts, per call, in `# Now`: whether the person has a page open on any
  device (`ashley.channels.to_phone.looking`), told only when that can be read, and that a push reaches their phone.
  Both are offered only to a known speaker with a subscribed browser; with no browser the field is ignored, as on a
  spoken turn. Her choices are three, by fields: `worth_saying` false posts and pushes nothing (the turn is stored as
  her staying quiet, and what she did with her tools stands); true, the reply is on the thread; `to_phone` also true,
  its `text` is queued for `push:<person id>` in the transaction that stores her turn, as for a spoken turn. A reply
  kept quiet never pushes (`unprompted.as_said`). The outcome is logged `wake.outcome` (`silent`, `thread` or `phone`)
  with the conversation id.
  Initiative today decides only whether a woken reply goes out (`speaks`, from `worth_saying`); the channel and the
  moment are this field, which is the seam a scored Initiative takes over. Urgency is not a field yet. Presence is
  Live's per-pod fan-out and cannot say who is looking across both sites, so an open stream (`GET /api/live`) holds
  a row of `live_screens` (`ashley.live.screens.Screens`), refreshed at the stream's heartbeat and removed when it
  ends; one not refreshed within `live.json`'s `present_s` is a pod that died and counts as closed. Rejected: code
  pushing when no page is open, which decides routing for her and buzzes by rule; asking the pod's own fan-out, which is
  blind to the other site.

## Her house is general: Home Assistant's REST and WebSocket APIs behind a port

She has the household's Home Assistant admin token and may see and change anything in it. What she
sees and does is a `House` (`ashley.home_assistant.house`): neutral records (things with a state, devices, entities,
areas, floors, labels, integrations, configs, actions) and the operations over them, implemented for Home Assistant by
`ha_house.HaHouse` over its REST API (states, history, logbook, actions, automation and script configs, diagnostics) and its
WebSocket API (the registries, helpers, config entries), one command per connection. Swapping the house changes the adapter
alone. What each API offers in HA 2026.10.4 (read from a live house's `/api/config`; each row checked on it read-only or
on a scratch container):

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
home-assistant.io/integrations/mcp_server and /integrations/esphome. Aliases are written `[None, ...]` since 2026.10: the null is
the entity's own name, and plain strings drop it from Assist.

- **Her tools are general primitives, not HA's tools.** `house_state` (the live map of the devices the household lists
  for her by name, `all` for everything), `house_find` (devices, entities, areas, floors, labels, integrations,
  automations, scripts, helpers, actions and their fields, and what an integration reports about itself, by kind),
  `house_history` (a thing's changes, or the logbook), `house_ask` (an action that only returns data) and `house_do` (any
  other action). An action's fields are a JSON object as text (`data`): Gemini, her chat model, fills an object whose fields the
  schema does not name with `{}`, and the shopping-list ask failed on it until the schema said text. Things are named by exact id, or by `name`, `area` and `domain` resolved in code against the house's own
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
  registry's devices that have a maker or model, as many as `devices_chars` holds and a count of the rest). The exposure stays
  the household's curation of what she is told up front and the tie-break between equal names; it no longer limits what she
  can reach. The devices line is what makes a question about one ("can the Atom Echos also be Bluetooth proxies?") a lookup:
  without it she answered from what she knows of the product and called no tool, with it she reads the device's record and
  its integration's diagnostics.
- **Some of the house's actions she is never offered, as data** (`home_assistant.json`, actions as `domain.name`):
  `assist_satellite.announce` is excluded since her route to the rooms is the outbox. The scripts that only look something up
  are the household's `reads` setting ("A connection has settings its person sets"); an action the house says only returns data is a read too. The kiosk's controls run `house_do`
  by code and name none of the excluded.
- **She reads the house's state through `house_state`, answered in code** (`house_query` narrows like a map, `house_render` caps it): one
  `GET /api/states` plus the registries per call, nothing cached on a pod. Every list holds every child; an answer over
  `house_state.json`'s cap shows names or counts instead, with `complete` false and `narrow_by`. `name` matches the entities'
  own fields, every word; `matched` 0 is final.
- **Structured reads that code acts on go through HA's REST API**, not a tool: presence decides who is talking, so no
  model sits between the state and the decision. The event stream will use HA's websocket. The Workshop's installed
  automations still go through `ashley.home_assistant.automations.Automations` (a subset of the House's automation configs;
  folding it into the port is open work).
- **Rejected: HA's MCP server as a second adapter, and as the first.** Measured on a scratch HA 2026.10.4 with aliases and
  areas, twelve asks (ten everyday, two names the house lacks): MCP's intents resolved 10, the registry-backed resolver 12; the two MCP misses were area
  aliases ("the lounge lights", "the main bath light"). Reads are the same matcher either way. MCP also reaches only what is
  exposed to Assist, and gives no registries, history, logbook, config or device details, so keeping it would be a second
  implementation of the same questions that drifts. `HomeAssistantTools`, `McpClient` and the `GetLiveContext` parser are gone.
  House eval, two runs a case on a scratch house carrying the eval's names: main (MCP) 22/22, step-limit hits 0; this 22/22 and,
  on a rerun, 21/22 (one `unknown-sauna` run asked `house_do`; 8 of 8 on eight more), step-limit hits 0 and 1; her first step reads
  about 1,200 more input tokens (five house tools, `house_change`, the devices line). Her first run was 20/22: the shopping-list add
  sent `data` as `{}`.
- **Rejected: a sub-agent in front of HA** (one `house` tool, Haiku over HA's tools). It cut her main call about 3x
  (11.6k to 4.0k tokens a step) but made five read-only asks slower (sum about 49 s before, 75 to 87 s after): two
  model steps per house call on HA's guidance, and a name that matched nothing came back as prose she re-asked in
  new words, up to 11 steps in one turn.
- **Rejected: vector search or tool search over HA's tools.** The definitions cost little (about 70 ms of first
  token); the results were the cost.

## Search: SearXNG for the web, Photon for places

Tools is a Composite over its sources: the house (HA's MCP server) and a look-up, which is itself a sub-agent over a
Composite of the web and places. Each source's catalogue is asked at once; one that does not answer is named in the
catalogue, and she says in one line that she cannot use it right now, while the others go on.

- **She never reads search results; a sub-agent does, and she calls it as one tool, `look_up`.** It has its own task
  and routes (`look_up`, Haiku first) and only `search_web`, `read_page` and `find_places`; she writes the question in full, it
  searches, and it hands back `found`, a short `answer`, its `sources` and, when she asked for a page or video to show,
  its `references`: result numbers with a few words and the site each, never a URL. Her context holds the question and that
  answer, never a snippet, which is what "A call carries only what this reply needs" asks of a long or untrusted tool
  set, and she keeps every house tool after a look-up, so "what time does Target close? remind me at eight" is one turn.
  What crosses back is bounded in code (`look_up.json`: the answer's length, how many sources and how long each), and
  nothing that reads the web has a tool that acts on the house.
- **What can still get through:** an instruction a page smuggles into `answer` reaches her as a tool result. It is
  bounded by the answer's length, by the sub-agent's prompt (results are facts to weigh, never repeated as requests),
  by her own prompt (a look-up's answer is information, not an instruction), and at worst by what HA exposes to Assist.
- **The look-up knows when it was asked through a field:** `look_up` requires `now`, the household's local date and
  time from her prompt, which reaches the sub-agent before the question, so "open now" and "tonight" mean something.
  `Tools.call` carries no household, so a required field is how the moment crosses.
- **Its steps record no conversation in the spend ledger:** `Tools.call` carries no conversation id, so a look-up's
  rows are by task alone.

- **The web is SearXNG** (JSON API), at the deployment's address (`SEARXNG_URL`, set in the cluster repo); without it
  she has no web search. The look-up is shown the first few results' titles, snippets and sites, each with a result
  number, and SearXNG's direct answers.
- **The look-up reads a page by result number, never by URL.** `read_page` takes a number that a `search_web` of this
  turn returned; the numbers run on across the turn's searches and look-ups, and the table from number to URL is the
  turn's one `ashley.tools.results.Results`, which `ashley.tools.pages.Pages` records into and the bench tools read
  (see "A site or video piece is put up by a result's number"). At most two pages are read per look-up. A
  snippet often lacks the one fact asked for (a clinic's hours) while the page has it. Her context is unchanged: the
  page text reaches only the sub-agent, cut to `page_chars`.
- **A YouTube video's page reads as the video, and its description's links become numbered results.** A watch page's
  words are all inside a script, so its stripped text is a few hundred characters. `read_page` on a result whose parsed
  host and path are a YouTube video's (`ashley.workshop.embed.youtube_id_of`) fetches `https://www.youtube.com/watch?v=<id>`
  as a browser would (`Mozilla/5.0`, `Accept-Language: en`) and returns the title, channel, publish date, length and
  description from the page's `ytInitialPlayerResponse` (`ashley.tools.youtube`). Each https link in the description is
  recorded into the turn's `Results` (at most `Pages.MAX_LINKS`, once each) and shown as `<url> (result N)`, so
  `read_page` and the bench's reference tools follow it by number; the page authored the link and she never types a URL,
  so the rejected URL parameter below stays rejected. The same change would number the links of any read page; only a
  video's description does, since a page's own text rarely holds the links a question turns on. `page_bytes` is
  unchanged: the player response sits inside the first megabyte of the two pages measured (at about 0.78 MB of 1.4 and
  1.8 MB), and a page that cuts it off reads as any page.
- **A bench site or video piece reads as its page.** `bench_read_piece` on a site piece, or a video piece that is not a
  direct file, also returns `page_text` (the page as `read_page` reads it, cut to the bench's `piece_chars`; for a YouTube
  video its details and description) or `page_unavailable`, through `ashley.tools.page_reader.PageReader`, the one reader
  `read_page` and the bench share, under the same `page_fetch` boundary. A video's description links are numbered into the
  turn's `Results`, so look_up reads such a result's page (she names its number) and `bench_add` of a code or document piece
  by that number follows. Before this a video already on the bench could not be read: `read_page` takes only a result number
  and the piece's own address is not one. The address is the piece's stored body, written by the server from a result or
  given by a person, never model-typed text, so the rule that she never reads by a URL she wrote holds. Rejected: a `url`
  parameter on `read_page` or a separate bench tool (the piece id already names the stored address).
- **A YouTube video's captions are fetched by yt-dlp in a media pod of their own.** A plain GET of a caption track's
  address answers 200 with an empty body (YouTube wants a proof-of-origin token the page does not hand a plain client);
  yt-dlp, pinned in the media image, does what it asks. `bench_transcribe` on a YouTube `video` piece takes the captions
  file piece she names (`captions_piece`) first, else runs `Media.youtube_captions`, a third media job beside `frames` and
  `transcribe`: the app parses the video id from the piece's URL (`ashley.workshop.embed.youtube_id_of`) and hands the pod
  only that id; the runner builds the canonical watch address itself and passes yt-dlp an argv list, so no other address
  reaches it. yt-dlp is asked for the manual English track and falls back to the automatic one (json3), and the runner
  turns it into `[start, text]` cues stored and shown like a recording's transcript (source `youtube`). A video with no
  English track answers its own outcome, `no_english_captions`. This is the only media pod with public egress: it carries
  `ashley.yggdrasil.pub/fetch` besides the media label, and the namespace's network policy (the cluster repo) opens TCP
  443 to public addresses and DNS to that label alone. The pod fetches no file and has no link. Logs carry the video id,
  cue count, seconds and outcome, never a caption. Rejected: the app pod fetching the track (it would open an address no
  check has seen), and calling YouTube's player APIs by hand.
- **A page fetch from inside the pod is a request forgery waiting for an injected snippet**, so
  `ashley.tools.page_fetch` is the one module that opens an arbitrary URL, and it fetches only https, only from a host
  whose every address is global (`ipaddress.is_global`, so loopback, private, link-local, CGNAT and unique-local are
  all refused, as is a mix of one public and one private address), checked before each request and again after each
  redirect, which it follows by hand up to `max_redirects`. It reads only `text/html` and `text/plain`, at most
  `page_bytes` of the body, within `page_timeout_s` for the whole fetch. **A DNS answer that changes between the check
  and the connect is not covered;** a homelab threat model accepts that. Pinning the checked address is possible
  (connect to the address, with the host in `Host` and in httpx's `sni_hostname` extension), but the client's pool keys
  connections by address, so a TLS connection checked against one host's certificate would be reused for another
  host on the same address; closing that properly needs a network backend that checks at connect time.
- **A page whose site refuses the plain fetch is read in a browser pod, as a browser that says what it is.** When the
  fetch is answered 401, 403, 429 or 503 (`ashley.tools.page_reader.REFUSING`, a bot wall's challenge among them) and a
  page browser is wired, `FetchedPageReader` reads the page through `ashley.looks.browser.PageBrowser`: a cold look pod
  (`ashley.looks.pod_spec.read_manifest`) running the look program in its `read` mode, which prints the main response's
  status and type and the loaded document, cut to `read_bytes`. The pod carries the fetch label as well as the look
  label, so the namespace's existing policy gives it public HTTPS and nothing private (the house LAN, both sites' pods
  and Services are excepted), and the address was checked public by the fetch it follows. What it brings back goes
  through `page_fetch.page_of`, so text and recipe are read alike; a non-2xx answer is still no page. Chromium runs as
  it comes, headless and saying so: measured on five recipe sites, the plain
  fetch read one and the browser another, the other three refusing both. Rejected: disguising the browser or
  answering challenges, which is getting past a site's refusal rather than reading what it serves; the warm look pod,
  which reaches only the app and draws benches, so strangers' pages stay out of it.
- **Printables is a look-up source beside SearXNG and Photon: a model is a result number, and its file reaches a bench by
  that number and a file id.** Its public GraphQL API (`api.printables.com/graphql/`) answers plain requests, while the
  site's pages and the other two sites that host designs answer them with a challenge (printables.com/model pages,
  Thingiverse and MakerWorld; nothing here tries to get past one).
  - **Find:** the look-up has `search_printables` (`ashley.tools.printables_search`): name, summary, likes, downloads,
    makes, rating and file names, each result numbered into the turn's `Results` as the model's page address. It is a
    look-up source, not a bench tool, because it is another search whose results the look-up weighs and she never
    reads; a model's page then goes on a bench as a site piece by its number through the path that already exists.
    Every value a caller supplies goes to the API as a GraphQL variable.
  - **Look:** `read_page` on a Printables model's page reads the model through the API (`ashley.tools.printables_page`):
    author, category, license, date, counts, files by name and size, and the description as text. The site's own page is
    not fetched.
  - **Fetch:** `printables_files(result)` lists the model's files with the ids Printables gave, and
    `bench_add_printables_file(result, file)` puts one on the bench as a file piece. The server finds the model from the
    number (`ashley.printables.printables.model_id_of`, by parsed host and path), requires the file id to be one of that
    model's files and its name to end `.stl`, `.3mf`, `.step` or `.stp`, asks the `getDownloadLink` mutation for the
    file's address, and opens it with `ashley.tools.page_fetch.fetch_file`: https, global addresses only and
    only `files.printables.com` (`printables.json`), each by parsed hostname and again after every redirect, at most the
    bench's file limit (`files.json` `max_bytes`) and `download_timeout_s`. The bytes must be what the name says (a binary
    or ASCII STL, a 3MF with its model part, a STEP with its ISO-10303-21 header) and are then kept as an upload is
    (`ashley.workshop.bench_file.add_file`). No URL is an argument of any of it.
  - **Outcomes** are distinct: `unknown_result`, `not_a_model_page`, `no_such_file`, `not_a_model`, `too_large`,
    `needs_login`, `unavailable`. `getDownloadLink` handed over STL, 3MF and STEP files to a visitor with no login; its
    refusal (`ok` false) is `needs_login`, an outcome no model tried has produced.
  - **Rejected: Thingiverse and MakerWorld.** Both answer automated requests with a Cloudflare challenge. Thingiverse has an
    API key in the secret store (`ashley-thingiverse`) that a source over its API could use; none is built.
  - **Rejected: a URL argument for the file,** for the reason `read_page` takes none: the address comes from the API for a
    file the model lists.
- **Places are Photon** (`photon.komoot.io`, OpenStreetMap), biased toward the house and ranked by distance in code,
  nearest first, with the miles. The house's coordinates come from HA's `zone.home`; they are rounded to
  `bias_decimals` (about a kilometre) before they leave, and the precise point is used only for the ranking, here.
  With that bias "Target", "pharmacy", "urgent care" and "Chipotle" each came back nearest-first at about 3 km.
- **Tunables are data**, `search.json`: Photon's host, timeout, how many results and how much of each snippet.
- **Rejected: SearXNG's map category for places.** It drops any location bias: a bare "Target" returned ten
  results, the closest 990 km from the house, so "nearest" cannot be had from it.
- **Rejected: appending a locality to the query** ("Target in <town>"). It sends where the household lives as text
  in every query, and a town name is a coarse bias that still does not rank by distance.
- **Rejected: narrowing her tools after a search** (only search tools for the rest of the reply, once results were
  read). It kept web text away from house actions but broke searching and then acting in one turn.
- **Rejected: a URL parameter on `read_page`.** Any URL a snippet planted could then be fetched from inside the pod.
- **Rejected, for now: trafilatura or readability for a page's text.** A dependency and an image rebuild for a
  tag-stripper's job; `ashley.tools.page_text.text_of` does it with `html.parser`.
- **Rejected: offering her the search tools directly.** Raw snippets, text anyone can write, would sit in her context
  beside every house tool.

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
  group only. There is no admin group: what belongs to one person (their memory, their Claude Code sessions) keys on
  the person an account maps to. An `ashley_admins` group is for the day something needs a role several people
  can hold.
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
- **The `connections` table does not list kinds.** The check on `kind` and the one tying `person_id` to the code
  hosts are dropped (migration 0063): the registry is the one list, and a copy in the table would be a second a new
  service must migrate. The service writes only registered kinds, refuses to read a row whose kind is gone
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
  needs more yet: each one looked at is another kind (Gmail beside Proton, GitHub beside a local GitLab), a
  resource inside one connection (a person's mailboxes or calendars), or a personal kind's one per person (a herdr
  per person's machine). A connection is addressed by its id and carries its owner's label (at most 40 characters,
  unique per owner and kind), the owner being the household or, for a personal kind, the person. Adding past `most`
  is 409 `too_many` and a taken label 409 `label_taken`. A second account of one kind later is that kind's `most`
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
  serialized result, so the loop never cuts it. `claude_read` fits the end of the screen the same way. Rejected: a fixed `read_chars` setting (both tools had one), which had to be kept under
  the cap by hand and was 40000 against caps of 8000 and 16000; wrapping a cut result in JSON, which escapes the head
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
- **The tools' answers did not change** in the move: the same Sure bodies give the same bytes.
- Rejected: an adapter per tool. The records are the contract, and four tools plus the sense share one reader.

## Most channels are shared devices, so who is talking is its own answer

Only a personal login names a person by itself: a web session, a Discord DM, a person's Claude Code. Room satellites,
the hallway tablet and a shared Discord channel are used by whoever is there. So every request carries two answers:
the channel's audience (who will hear the reply, declared by the channel) and the speaker (who is talking), which on
a shared device starts out unknown.

- **A shared device signs in as a device**, with its own account mapped to a place and an audience, never to a
  person. The hallway tablet is everyone's kiosk.
- **The speaker on a shared device comes from signals in code**: HA presence (one person home is that person),
  voice identification later. Until one names someone, the speaker is unknown and gets shared facts only.

## The hallway tablet is her page, paired as a device

`/kiosk` is a page of her web app outside the person shell, for a screen anyone may use. It shows only what anyone in
the hallway may see, and does what anyone there may do.

- **The screen pairs once with a device token** from `python -m ashley.channels.devices add` (audience `present`, its
  place). `POST /api/kiosk/session` checks it with `Devices.by_token` and keeps it in a `__Host-ashley_kiosk` cookie
  (Secure, HttpOnly, SameSite=Strict), checked again on every request, so revoking the device unpairs the screen.
  Rejected: a table of kiosk sessions, a second credential to expire and revoke for one screen; and signing the
  tablet in through OIDC, which would make it a person.
- **The device rules hold as on `POST /api/messages`:** a request carrying `Cf-Connecting-IP` is refused with 401, so
  the screen loads her page at `PUBLIC_URL` on the home network, where the gateway serves it. A write must come from
  that origin, as JSON. The kiosk cookie is never a person's session nor a session cookie a kiosk.
- **Only what makes her act is counted against the device's rate:** messages and controls. The page's reads poll at
  fixed rates and cost no tokens, so counting them would let the page's own polling spend the budget for talking.
- **It shows its own conversation**, on the device's thread `device:<id>` (channel `web`, the device's audience and
  place, shared, so presence names the speaker). A held line and its answer are each stored as her turn and announced
  to the screen through Live (`later_by="turn"`), as on web chat, so "let me check" appears at once and stays, and the
  answer lands under it;
  it is not queued in the outbox, since the satellites singleton takes every outbox reply on a `device:` thread. The
  page holds `GET /api/kiosk/live` open, reopened with backoff: her mark follows the shared turns' state and the
  conversation is read back on a stored turn or a resync, with its slow timer only while the feed is down. **The glance**
  is the screen's own clock, written in the household's locale and clock, and the first names of the household's people who are home (the house's own knowledge, which whoever stands in the hallway can see), and calendar and
  reminders shown as not connected until a source exists; it is read on its timer whether or not the feed is up, since
  nothing announces a person coming or going.
- **The tablet's screen is a bench of the device's, laid out by her.** A device of form `other` has at most one screen
  bench (`benches.device_id`, owner null), created on its first change and seeded from `screen_seed.json`; until
  then the page shows its fixed layout, which is also what it shows whenever the layout cannot be read or is not
  well formed. Its pieces are the `screen` kinds (clock, who is home, the conversation, the controls), one of each,
  and the conversation is never removed, so the hall can always ask her to put things back. She places, moves,
  resizes and removes them through the Workshop's Commands from any channel of the household (`ScreenTools`), and
  every change is logged and undoable as on a bench. The screen announces `ScreenChanged` to the household's screens.
  Rejected: a Surfaces table and log of its own, a second decide/undo for the same arrangement; a jsonb layout on
  `devices`, which has no log or undo.
- **The touch controls are the screen's `controls` piece**, its body the button list. A person edits it in the
  Devices room and she edits it when asked, both as an Edit naming the version read, so one of two concurrent edits
  is refused `stale_base` and redone on the other. Each light or scene must be in the house's catalogue, checked by
  the caller before the Command. A press still runs `house_do` by code. `device_controls` holds a device's list only
  until its screen bench exists.
- **An open page follows the server's build, the person shell and the kiosk alike** (`web/src/session/update.ts`,
  `watch.ts`). It remembers the `version` `GET /api/health` gave when it booted, asks again on each live resync and every
  few minutes, and when the served build differs reloads at a quiet moment: no pointer, touch or key for a while (a page
  never touched reloads at once), and on the kiosk not while she is listening, thinking or speaking nor while a message
  is going. A build reloaded for that is still served old (a pod on the old image mid-roll) is retried after a backoff,
  then given up on. `dev` never reloads. There is no asset hash, so the version is the whole key.
- **An HA dashboard is not framed inside her page.** HA answers with `X-Frame-Options: SAMEORIGIN` (both
  through its proxy and on `:8123` directly), so a browser refuses to show it framed by her origin. Framing would mean
  turning off HA's `http: use_x_frame_options` for the whole instance, and the frame would still need its own HA
  login in partitioned storage. What she has no view of yet gets her own view.

## Discord is a bot, its Gateway a singleton

She is one Discord bot. A DM is its account's own channel; a household's Discord server is a device, as a satellite
is, mapped by the admin CLI (`python -m ashley.channels.devices discord`) with a home channel, `#ashley`, where she
will post on her own initiative. She moves between the server's channels, and each channel is its own thread, so its
own conversation. One unrevoked device holds a server, so revoking it frees the server for another. The adapter is
`app/ashley/channels/discord/`.

- **The Gateway session is a singleton under the lease `discord`.** Discord allows several sessions on one shard and
  does not say whether each gets every event, so two sessions are assumed to both answer; the lease allows one.
- **Each message is claimed in Postgres before she answers it** (`discord_seen`, `INSERT … ON CONFLICT DO NOTHING`),
  so a double reply is impossible even in a failover's overlap. During a demotion the claim fails on the read-only
  database and she does not answer, which is the lease rule's tolerated failed write. Claims are pruned after
  `seen_retention_days` each time she takes the lease.
- **On taking the lease she catches up**: for each server's home channel, and each channel with a claim in the last
  `catch_up_s`, the messages after the last claimed one and younger than `catch_up_s`, each handled as if just
  arrived; the claim makes repeating it safe. It also hands in again each claim in that window never settled (a
  session that died between claiming a message and the turn loop taking it), from that message on, without claiming
  it twice. That is safe because the message's person turn is stored once by its source (`discord:<message id>`) and
  a turn whose work is saved or whose answer is stored gets no second answer ("Work in flight survives its pod"). A first DM sent while no session is connected is missed, since its
  channel is not yet known; accepted.
- **A DM from an account mapped to a person is that person's**: audience `owner`, speaker the person. **A DM from an
  unmapped account gets nothing**, no reply and no model call, logged with the Discord user id for the admin to map.
  Answering it as an unknown speaker would give household facts to any member of the server, guests included, and
  spend on their messages. A person whose Discord privacy blocks DMs from the server's members cannot DM her either:
  Discord refuses the message before the Gateway sees it, so nothing is logged; they allow DMs in the server's privacy
  settings.
- **In any channel of a household's server she answers only a message that mentions her or replies to one of hers**,
  read from Discord's structured fields, never the text. The audience is the device's; the speaker is the author's
  person when they are in that household, else unknown, and presence never guesses, since Discord names the author.
- **The household servers are read for each server message**, so a server registered with the CLI is answered at
  once, with no restart; a message that arrives while they cannot be read is dropped unclaimed.
- **When the session ends on its own, the replies in flight finish first**: their messages are claimed, so no other
  session would answer them. Cancelling the body (a lost lease) cancels them.
- **A reply is split for Discord's 2000-character limit in code**, at paragraph, then line, then word breaks, into at
  most `max_messages` messages, the last ending `…` when cut. Every send parses no mentions, so her text can never
  ping `@everyone` or a role. In a channel the first message replies to the one she answers.
- **While she thinks she shows typing.** A turn that cannot be made posts a line from data (`unavailable_text`,
  `refused_text`); a failed send is logged and dropped, since a late duplicate is worse than a gap.
- **The library is hikari** (asyncio, typed, every cache off, runs in the caller's loop with no signal handlers),
  fenced in `client.py` behind the adapter's own interface; `test_boundaries.py` holds the fence. Every session start
  spends one of the token's 1000 daily IDENTIFYs, which the lease's pause after a failed body bounds.
  - Rejected: discord.py (caches guilds and channels by default, releases slower, pulls `audioop-lts`).
  - Rejected: disnake, nextcord, py-cord (cache-heavy discord.py forks with smaller teams).
  - Rejected: a hand-rolled Gateway client (heartbeat, resume, compression and rate limits to own for nothing).

## Every fact has an owner, a household and one of four visibilities

People in a household share most things; some are private (therapy), some are known but rarely asked about
(texts, plans with friends). Each fact carries `household_id`, an owner and a visibility:

| Visibility | Rule |
|---|---|
| shared | She may mention it to anyone in the household, unprompted. |
| discreet | She answers if someone else asks directly, never volunteers it. |
| members | Household money: any known person of the household may ask, only where they alone hear the reply; never volunteered, never to an unknown speaker, a satellite, the hallway tablet or a household channel. Its owner is null. |
| private | Filtered out in SQL before any prompt about anyone else. |

- **Enforced by the query, not the prompt.** A fact told "don't mention this" leaks by inference; a fact absent
  from the context cannot.
- **An unknown speaker gets least privilege**: shared facts only. Knowing who is talking widens what she knows.
- **Private answers go only to channels the owner alone hears**; with others in the room, the answer goes to the
  owner's phone.
- **The model sets visibility as a structured field, erring private**; code pins some kinds (health, therapy) to
  private, and an explicit "keep that between us" or "you can tell my partner" overrides.
- **Source data has visibility too**, as data. Calendars are often the least private source: a household may
  share every HA calendar, a personal one included. Where someone is goes on the calendar; what happens there, as
  told to her, is private.
- **`household_id` is on every row of household data from the first migration.** Other households (relatives at
  another site) may join later; nothing crosses households unless explicitly shared. Tables that
  hold nothing said or known about anyone, such as the spend ledger, carry none.
- **Rejected: two levels (private/household).** Texts and plans aren't secret, but shouldn't be volunteered.
- **Rejected: a kind-based clause (`kind = 'finance'`) in the hearing rule.** The one rule would then read a fact's
  kind as well as its visibility, and a money fact moved to the household would need the kind check at every reader;
  `members` keeps the rule on `visibility` and `owner_id` alone.

## What she knows lives where the thing that would make it wrong lives

Before anything she knows is written down, ask what would make it stale; that decides its home, and the home is
where she meets it on the way to using it, so nothing has to be carried in every prompt "in case".

| Goes stale when... | Home | She meets it |
|---|---|---|
| we revise how she behaves | the persona files, per kind | every reply of that kind |
| a tool or device changes | the tool's own description, or the entity's name and aliases in HA | when that tool is offered |
| the world moves (a birthday, a pet, who prefers what) | a memory fact with validity (below) | retrieved when the message is about it |
| a moment passes (who is home, a light, the time) | nowhere: read live from a sense or tool | when the reply needs it |
| a person changes their mind about her | their settings | when that person is talking |

- **Live state is never stored as knowledge.** A remembered "the porch light is on" is wrong by the next reply.
- **A rule about one tool lives in that tool**, so it arrives only with the tool and leaves with it. The household
  profile's tool hints (the thermostat setpoints sensor, how to phrase Locate Person) move into those scripts and
  sensors in HA.
- **The household profile is the interim home of world facts** until standing facts and recall carry them (open-work, "Retire the `households.profile` column").

## Memory is atomic facts in Postgres that are superseded, never edited

One row per fact (who it is about, owner, household, visibility, kind, source conversation and turn), current while
`valid_to` is null. A correction closes the old row and points it at the new one, so she stays accurate and can
still answer "what did I say before?". Facts are never blurred or aged out: a butler who misremembers an allergy
is broken.

- **Written in the background** when a conversation goes idle: a model sees the ten most similar current
  facts and returns a typed `ADD`/`UPDATE`/`INVALIDATE`/`FORGET`/`NOOP` per fact. Replies never wait on it.
  `INVALIDATE` keeps the old row as history; `FORGET` is the owner asking, and deletes it with everything it
  superseded, so it never resurfaces, not even as "what did I say before?". The writer is `InferenceFactWriter`
  on Sonnet, prompted by `writer.md`; any change to that file or the cases reruns the write eval (`python -m
  ashley.evals memory-write --runs 5 --writer anthropic --judge anthropic`) beside a run of main the same day, since
  a case varies by a run or two at five runs. A case the writer is known to fail carries `known_failing`: it stays
  in every rate and is marked in the report, so the gap shows. What a fact must leave out (a one-off ask said beside
  it) is an expectation's `omits`, judged as a statement the fact must not make; a "states" that says what is
  absent cannot pass, since the judge reads it as a particular. Rejected: Haiku for `memory_write`. On a long task
  conversation with facts said in passing it missed them (a twelve-turn workbench brainstorm, 0 of 3 runs wrote all four
  facts, at `effort` low; a production brainstorm of the same shape, 0 of 3 at low and 0 of 3 at high), where Sonnet
  at `effort` low wrote them 3 of 3. The short write cases cannot show it, so
  `standing-facts-in-passing-in-a-long-brainstorm` does.
- **A fact links to the turn it came from.** `facts.source_turn_id` is a turn of the source conversation (the
  foreign key names both, so a turn of another conversation is refused), null for facts written before it existed.
  The writer sees each turn marked `[turn N]` and names the one a fact came from in `source_turn`, a structured field
  of its output on `add` and `update`. Code keeps it only when it is one of the turns the writer was shown; otherwise
  the fact takes the last person turn of those turns (none, when there is none) and `memory.write` counts
  `turn_fallback`. The write job and "Remember" both go through that writer, so both name it; a correction made on
  the page names its own typed turn. The Memory room shows each fact's source; nothing reads facts back onto a chat
  line, and the conversation reads carry none. Rejected: showing memory under chat lines (a receipt of the facts a
  line taught, an outcome of acting on memory, a marker that a fact was replaced). Facts are learned from every
  channel, merged, superseded and forgotten, and a chat line is the wrong thing to hang them on: it couples Memory to
  the interface, which is visually cool and will cause problems later.
- **Looked at, not built: the whole conversation for the writer.** It sees only the turns after the watermark, so
  a reopened conversation loses its earlier exchange as context. Give it the whole conversation with the written
  turns marked if real cases show a fact misread for want of it.
- **Each conversation is written once per new turn**, by a singleton under the lease: the turn it was written
  through is recorded in the same transaction as the facts, so a failover mid-write leaves both or neither and the
  next holder redoes it. When Sonnet is unavailable the job waits for it rather than take `memory_write`'s Gemini
  Flash-Lite fallback, which scored 76% on the write cases when Haiku scored 100%; the fallback stays in `routes.json`
  only so the eval can pin it.
- **A device says whether its conversations are remembered.** The eval harness and test devices are registered
  not-remembered (`devices add --not-remembered`), so their traffic never costs a write nor plants a fact in the
  household. The field is authored on the device and copied to the conversation when it starts; a conversation
  continued from a thread keeps the value it started with, and the write job never selects one that is not remembered.
- **Most facts are never asked to be remembered.** 96% of ChatGPT's memories were written without being asked, and
  real use is music, timers, weather and the house, so facts arrive inside task turns. The write job's harder
  half is what *not* to keep: jokes, hypotheticals, one-off context.
- **Whether the owner said who may know is its own field** (`visibility_stated`), so code's private pin on health
  yields to "you can tell my partner" without reading the words.
- **A household fact the writer adds has no owner unless its teller said who may know it.** Code decides it from the
  writer's fields (`about` null and `visibility_stated` false clear `owner`, counted as `owner_cleared` in
  `memory.write`), because the model's owner on such a fact flips with unrelated prompt edits: a one-sentence change
  to `writer.md` turned "remember the spare key is in the green watering can" into the teller's fact 4 times in 5. An
  `update` keeps the owner written, since a person may have made a household fact theirs. Rejected: a prose rule in
  `writer.md` alone, which is what held the owner before and did not.
- **Read in two tiers:** the household's standing facts always in the prompt; everything else by search filtered on
  visibility first. A retriever finds what a message names, and "order sushi for dinner" never names the shellfish
  allergy, so the facts that change a good reply without being mentioned have to be there already.
- **A fact is standing when the writer says so** (`standing`, a field of the writer's output): true of someone for
  good, and changes what a good reply looks like without being mentioned, such as what they can't eat, their pronouns,
  an access need, or a pet's name and kind. Code pins `diet` facts to standing, as it pins `health` to private.
  Standing facts come to every reply through the same visibility filter as recall, so another person's discreet one is
  marked "only if asked" and a private one reaches only its owner on an owner-only channel; recall leaves them out,
  since they are already there. There is no cap: a household has a handful each, and `memory.profile` logs the count.
- **What someone can't, won't or shouldn't eat or drink is its own kind, `diet`**, and is not `health`: allergies,
  intolerances and diets are what a household cooks and orders around, so they are shared unless the owner says
  otherwise, where `health` is pinned private. A shellfish allergy that only a DM could hear would not stop the
  kitchen speaker ordering sushi.
- **Money is its own kind, `finance`, and is the household's** (a household's Sure holds accounts every member
  shares): unless its owner said who may know, code stores it with no owner and visibility `members`, so any member may
  ask about it and what one says of money is the others' to ask about too, yet it is recalled only where the speaker is
  a known person who alone hears the reply, never on a satellite, the hallway tablet or a household channel. "Keep this
  between us" still makes it private to the person who said it. Any member who holds a household money fact may
  correct or forget it, as with any household fact (`held` decides); moving a private money fact to the household
  makes it `members`, never `shared`.
- **Recall is hybrid: full-text unioned with the three nearest facts by embedding.** Full-text alone found a relevant
  fact for 64% of 90 blind-written household remarks and for 9 of 30 paraphrases ("is it bin night" against "The
  recycling goes out on Tuesday nights"); with the nearest three by embedding it was 93% and 29 of 30. The
  vectors are `pgvector` columns on `facts`, made by `thenlper/gte-base` (768 dimensions, MIT) run in-process on
  the CPU. It tied the larger models on those cases and costs about 17 ms a question; it is baked into the image,
  so nothing is fetched at runtime. Facts are embedded when the write job writes them, and a tick embeds a
  bounded batch of any without one or with another model's, so changing the model re-embeds in the background. A
  fact is never lost to an embedder outage: it is written without a vector. Recall embeds the question, and with no
  answer from the embedder falls back to full-text alone, so a reply never fails because of it. The same union feeds
  the write job's candidates, so a paraphrase of a known fact is an `UPDATE` or `NOOP` and not a twin. The
  visibility filter runs before either search. There is no ANN index: a household has hundreds of facts, the
  filter leaves fewer, and an exact scan is faster and exact; add one when a household's facts reach the tens of
  thousands. The cost is more facts per reply, since the nearest three come back whether or not they answer
  (`python -m ashley.evals memory-recall-hybrid` measures it).
- **Recall searches each message's own text**, read alongside the tool catalogue, and reaches the prompt as `[id]`
  lines; the reply names the ids it relied on in `used_facts`, which code keeps only where they were recalled.
  Unreachable memory is said in the prompt, as unreachable tools are, so she never answers as if she knew nothing.
- **Every fact links to its source conversation**, and people can see, correct and forget their own (below).
- **Tested on our own knowledge-update and contradiction cases**, not public benchmarks: LoCoMo and its rivals are
  vendor-run, and full context beat every memory system on it. The cases are in `app/ashley/memory/eval/`; each
  says whether it is `authored` or `real`, and results are reported per source, so authored cases cannot pass for
  real ones. Real cases come from her own turns as people use her, and keep the words as said: a real case that fails
  for want of what she had at the time gets that context (the stored facts, the tools), never new wording.
- **Rejected:** OpenClaw-style markdown files (no per-person visibility, validity or typed operations); A-MEM
  (rewrites old notes); Letta or Zep as the runtime (no per-person isolation; Graphiti needs a graph database);
  a game companion's villager haze and 12-fact cap (charming in a game, wrong for a butler).
- **Looked at, not built: a `topic` key per fact** (a game companion's memory keys each by what it is of, so nothing is
  remembered twice). The writer passes every update and contradiction case without one, and model-made keys for
  open-ended subjects would drift where the game's come from a fixed menu. Revisit if real cases show duplicates.

## People see, correct and forget what she knows of them

A signed-in person reaches the facts that concern them through `/api/memory/facts` (`app/ashley/api/memory.py`).

- **What concerns a person:** the current facts about them, the ones they own, and household facts (about and owned
  by nobody), filtered exactly as recall filters for that person on an owner-only channel. So another person's
  private fact never shows, even one about them (a surprise party), and the fact a correction replaced shows only
  when they may see it too. This one set is what they may see, correct and forget; any fact outside it is 404 to
  every route, the same answer as a fact that does not exist, so nobody learns one is there.
- **Any signed-in person of the household may correct or forget a household fact.** It is always shared, and any
  of them can already change it by telling her, since the write job updates it from whoever's conversation said so.
  The web gives them no power they lacked.
- **A correction is a web conversation of its own.** `Memory.apply` takes the conversation a fact was learned in, and
  a correction made on the page was learned from the person typing it, so it opens a `command` conversation with them
  as its participant and one person turn, the text they typed, and supersedes the old fact with an `Update` from
  it. The conversation is not remembered, so the write job never reads it and plants the same fact twice. Kind, who
  it is about and whose it is carry over; the visibility carries over as stated, so a discreet `health` fact stays
  discreet, and only the fact's owner may change it (403 otherwise). Rejected: a source of none, since every fact
  links to a conversation and a fact with none would be the one place that rule breaks; and reusing the conversation
  the old fact came from, which would say the correction was learned where the mistake was.
- **A fact moves between a person and the household through the correction path** (`POST .../moves`, `to` =
  `household` or `mine`): the same supersession as a correction, the text and kind carried over, a `command`
  conversation of its own as the source. Only a fact's owner may make it the household's, and only when it is about no
  one: the owner becomes none and it becomes shared, because a household fact is always shared. A fact about its owner
  stays theirs, since handing it over would share it with everyone and lose who it is about; who hears it is its
  visibility's job. Any household member may make a household fact theirs: the owner becomes them, about stays none and the
  visibility carries over. A fact about someone else, or owned by someone else, or already where it was asked to go, is
  403.
- **Forgetting is a hard delete of the fact and every version it replaced**, in one transaction, as the write job's
  `FORGET` is: `Memory.forget`, which needs no conversation. Embeddings are columns of `facts`, and nothing else keys
  on a fact id, so the rows are all there is. One `memory.forgotten` line carries the person and the count.
- **Where a fact was learned is its conversation's kind and start, the channel and place it started on, and whether
  the reader took part**, and no turn text. `Inbound.channel` (`voice`, `discord`, `device`, `web`) and `place` are
  written to the conversation when it is created and never updated: a thread points at the conversation it carries
  now and moves on, and later messages on other channels do not change where it began. Conversations from before
  have neither, and the room shows that as an unknown. A correction made on the web is a `web` conversation with
  no place.
- **Remembering a line now is the write job's decision, run early.** A person points at a turn of a conversation they
  took part in (dragged to Memory, or "Remember"), the answer shown only as a short fading acknowledgement where the
  gesture happened and never kept on the line, and `ashley.memory.remember` runs the same `FactWriter` over it
  against the most similar current facts and applies the ops through `Memory.apply`, so dedupe and supersession are
  the job's. Nothing is written verbatim from the line, and there is no second prompt. A conversation they were not
  in is 404, as one that does not exist. The writer sees what the job would have: a turn after the watermark comes
  with every unwritten turn before it, and the watermark moves to it in the same transaction, so the job carries on
  from the next turn and no line is decided twice; a turn already written is decided again with the turn before it
  as context, and the watermark stays. Rejected: deciding only the one line and moving the watermark to it, which
  would skip the unwritten lines before it for good; and leaving the watermark alone, which has the job decide the
  line a second time against the fact it just wrote.
  The two never write the same turns twice: `Memory.apply` moves the watermark only from where the decision began,
  under the watermark row's lock, so whichever lands second is stale. The job skips that conversation for the tick;
  the route decides once more from the new watermark.
- **She acts on memory now when her reply says so: keep, correct or forget.** `Reply.memory` is null, or an act:
  `keep` when the person asks her to remember, note or keep something or says it is worth keeping, `correct` or
  `forget` when they ask her to change or remove something she holds, with `facts`, the ids from `What you remember`
  of what they mean. Behaviour keys on the field, never on the words. The persona says she acts only on what is listed
  there and, when what they name is not, says she can't find it in what she remembers; never that memory changed,
  since the Memory room shows what came of it. Code drops an id she was not shown this turn (standing or recalled) and logs it
  (`respond.memory_act_unknown_fact`, ids only), so an invented id changes nothing.
  In a remembered conversation, once her turn is stored, `ashley.channels.keep.now` carries the act out apart from the
  reply. It records nothing on her turn and tells no screen: input to Memory, shown in the Memory room.
  `keep` and `correct` run `remember` over the person's turn and hers (the writer sees what she said she would do), and a
  `correct` also gives the writer the facts it names among those it decides against; the earlier unwritten lines are
  decided with it. `forget` is done by code, not the writer: each named fact the speaker may see (`Memory.held`, the
  Memory room's rule) is deleted with `Memory.forget`, one they may not is refused and logged, and only a known
  speaker forgets. `respond.memory_acted` logs how it ended, with ids and the action: `changed` when facts she held
  were corrected, ended or forgotten, else `kept` when facts were added, `known` when memory already held it, `missing`
  when a `correct` or `forget` named nothing she held or nothing the speaker may forget (nothing in memory changes),
  `failed` when it could not be done, which is also logged with ids and the kind and leaves the watermark where it
  was, so the write job writes those turns when the conversation goes quiet. The eval is
  `python -m ashley.evals reply-remember`, which grades the action and the exact set of ids.
  Rejected: a tool for it, since the decision is the write job's and a tool call would make the reply wait on it.

## A person reads back their earlier conversations

A conversation that has closed is not gone: `Conversations.of_person` lists the ones a person took part in and
`GET /api/chat/conversations/{id}` reads one (`app/ashley/api/history.py`), on any channel they spoke on.

- **Taking part is the only key.** A conversation is the person's when they are a participant (started with, or spoke in
  it), in their household. Any other id, and one that does not exist, is the same 404, so nobody learns a conversation
  is there. This reads what a shared kiosk or satellite conversation held, including others' turns, because they were
  in the room for it.
- **Newest activity first, paged by a keyset cursor** of the last activity and id of a page's last entry, handed to the
  client as an opaque `next` and taken back as `before`. A conversation with no turn is not listed. The service reports
  each one's kind, state, when it started and was last active, the channel and place it started on (unknown for old
  rows) and its turn count; turns come from reading one by id.
- **Read only.** Nothing posts into a closed conversation; the composer always talks to the open one. A reply to an
  earlier conversation would start a new one, as it always has.
- **Her room is one stream.** The open conversation stays as it was; scrolling up past it loads earlier conversations
  inline, newest first, each under a quiet divider giving when and where it happened. With no open conversation the
  earlier ones still show, so a page opened after thirty quiet minutes is not blank. Rejected: a separate list of
  past conversations, a second place to look for what she said.
- **Logs** carry the person, conversation ids and counts (`chat.history`, `chat.past`, `conversation.listed`), never
  turn text.

## The workshop: benches of pieces, changed only by Commands

A bench is where she and a person make something together (open-work, "The workshop"). It belongs to its household and
the person who opened it (audience `owner`). Closing it puts the project away: it is kept as it was, takes no command,
and is listed among the person's closed benches (`GET /api/benches/closed`, most recently closed first), from where it
is reopened (`POST /api/benches/{id}/reopen`) as it was. Close and reopen are bench-level operations beside the
Commands, not Commands: they change no piece and are not undone. Rejected: a Close command in the log, which would
make Undo reach a closed bench's opening and closing.
The Workshop service (`app/ashley/workshop/`) answers one question: what is on this bench, and who changed what. Every
call names the owner asking, and anyone else's bench is the same 404 as one that does not exist.

A bench is a project, and may be months or years of work. What runs on it is for prototyping, testing and debugging,
never for running things for real (a few days or a week at most, typically only while working on it).
What a bench makes that is meant to last (an automation, a script she runs on a schedule) leaves the bench for the
system that owns that kind of thing, and the bench stays for the work that goes on. While on the bench it may run in
shadow or for a short trial; nothing on a bench is relied on. Closing a bench puts the project away, not ends it.

An automation finished on a bench goes to one of three homes, which she proposes and the person approves: **Home
Assistant**, when it is simple enough to be reliable there (she reads and writes HA automations); **her own rule
runner**, when it needs more than HA can express, with HA for its triggers and its actions; or **an app of its own
in the cluster**, built through her herdr VM, when it is bigger than a rule. All three stay open to her, and she
chooses after planning it with the person on the bench. Home Assistant is the first built, end to end (below); the
rule runner and the app path are open-work item 23.

- **A piece is work product with a kind**, and kinds are data (Type Object, `app/ashley/workshop/kinds.json`): a label,
  the longest body, a family, and a body format. `stored`: the body is the content, in Postgres (`document`, `note`).
  `live`: the body is a reference to a source the client renders (`site` and `video`, below). The format is `markdown`, `plain`
  (shown as typed) or `code` (source, with a `language`; only a code kind has one), and the client renders a body by
  it: a document is Markdown, a note is plain because it is a jotting, so a stray `*` or `#` stays as typed. The kinds and the bench's limits
  (`app/ashley/workshop/workshop.json`) are served at `GET /api/workshop/kinds`, so the client hard-codes neither.
  Rejected: a class per kind, which turns each new kind into code and a migration.
- **A bench's list entry and a piece carry what the Commands say, derived on read.** A bench summary has `piece_count`
  and `last_changed_at` (its last accepted command), and each piece of a read has `changed_at`, `changed_author` and
  `changed_person_id` from the command in its `changed_by`, however old, so who changed a piece never depends on
  `recent`. None of it is stored twice. Rejected: a counter or timestamp column on the bench, which a command could
  forget to keep.
- **Every change is a Command** (`ashley.workshop.commands`): add, remove, move, edit, run, propose, install, archive,
  restore, undo, rename, cue and point,
  frozen records in one
  closed union, each naming who made it, the person or her. One pure function, `ashley.workshop.decide.decide`, judges a
  command against the bench into an accepted change and its effect, or a typed refusal. Every command gets the bench's
  next `seq` and one row in the log, refusals included, so the log replayed from empty through `decide` reproduces the
  bench and every outcome; a piece's id is the `seq` of the add that made it. Her edits go through the same
  `decide` as a person's, so hers are as visible and as undoable.
- **An edit replaces the piece's title and body and names the version it was based on**; a stale base is refused
  `stale_base` and nothing is merged. The client reads the bench again and redoes the edit. Rejected for now: CRDT or
  OT merging. One writer at a time per piece is enough until two people (or a person and her) editing one piece at
  once is real, and a merge is then a new `decide` rule rather than a new store.
- **Undo is a command too, and walks back through the bench's commands.** An Undo names an earlier command and applies
  the inverse of its effect while the piece it changed is as that command left it: every later command on the piece
  was itself taken back by a later Undo (or is such an Undo), else it is refused `changed_since`. That also refuses a
  command already undone. The next press names the newest accepted command that is not an Undo and not yet undone
  (`ashley.workshop.undo_walk.next_undo` over the bench's last `undo_window` commands, served as `BenchDetail.undo_next` and in her
  `bench_read`), so pressing Undo again undoes the next-older command, and stops at one that cannot be undone, with
  its refusal (`changed_since`, or `full` when a removed piece has no room on the bench to come back), rather than
  reaching past it. Anyone's command can be undone by anyone: the person's Undo reaches
  her commands and hers reaches theirs. There is no redo: an Undo cannot be undone (`nothing_to_undo`), and the
  client's button never offers one. Rejected: a stored undo pointer or per-screen stack, which drifts when her changes
  or another tab's arrive; a redo stack, which nothing here needs yet; skipping past a command that cannot be undone
  to an older one, which would undo work the person has not seen unwound.
  - **Undo reaches back over a window, not the whole log**, so its cost and reach stop growing with a bench's age
    (months or years of work). The window is the last `undo_window` commands by `seq` (`workshop.json`, 200), refusals,
    Runs and Undos counted, because a press of Undo is itself a command and spends a slot: a long walk back reaches
    about half the window in changes. `decide` refuses an Undo naming a command with `seq < next_seq - undo_window`
    `nothing_to_undo`, and the read walks only those commands, fetched with a bounded query (`LIMIT`), so both agree on
    where the window starts. Older changes stay in the log and the replay; they can no longer be undone. It has its own
    number, not `recent_commands` (50, what a read shows): that is a display budget, and sharing it would cap a walk
    back at about 25 changes. Rejected: a window counted in accepted changes only, which needs the whole log read to
    find its start. Rejected: a new refusal reason; to her tools and the person an Undo too far back is the same as one
    naming a command that is not an undoable change (`nothing_to_undo` and its hint).
- **What is not on the layout now but may be wanted again goes on the bench's shelf** (a bench lasts as long as its
  project, so what it holds outgrows `max_pieces`). `Archive` takes a piece off the layout onto the shelf, the pieces
  after it moving up; it no longer counts toward `max_pieces`, keeps its text, version and runs, and takes no edit,
  move, run or remove (`no_such_piece`). `Restore` brings it back last on the layout at the size it had, refused `full`
  when there is no room. Each is undone by the other through the ordinary undo rules: undoing an archive puts the piece
  back at its old order (or last), refused `full` with no room; undoing a restore archives it again; a change before
  either is `changed_since` until the archive or restore is itself undone. The shelf is served most recently archived
  first (`BenchDetail.shelf`, the bench-tools' `bench_shelf`), and a shelved piece is a `bench_pieces` row marked
  `shelved`. Remove stays for what is not wanted at all. Rejected: a Restore naming its order and size, which a Move
  after it already does, as its own undoable step; removing straight off the shelf, which would need a Remove whose
  undo returns to the shelf; nothing asks for it yet, so a shelved piece is restored, then removed.
- **Layout is an order plus a size class** (`ashley.workshop.model.Place`): the pieces hold orders 0 to n-1, and each
  has `small`, `medium`, `large` or `full`, a share of the row the client maps to its grid. A move names the new order
  and size and the others shift, so every screen computes the same arrangement and animates from the old one by piece
  id. Rejected: grid cells, which make every move a collision problem across screen widths that order-plus-size
  leaves to the client. The place is its own small value so that Surfaces (open-work item 20) can own layout later. A
  device's screen is laid out with the same Place.
- **One transaction per command.** It locks the bench's row, decides against the stored pieces (and, for an undo, the
  stored effect it names), writes the log row and the changed pieces, so commands racing on one bench from any pod of
  either site are decided one after the other. Tables `benches`, `bench_pieces` (the bench as it stands) and
  `bench_commands` (the log, the command and its effect as JSON); every row carries `household_id`.
- **Live says a bench changed, by ids only.** After an accepted command commits, a `BenchChanged` (bench id and `seq`)
  goes to the owner's screens alone; a page showing the bench reads it back. A refusal changes nothing and says nothing.
- **A bench's talk is a conversation whose thread is the bench**, `bench:<id>`: a `brainstorm` conversation through the
  shared turn loop, as web chat is, owner the speaker and its only audience, held answers stored as her turn and
  announced as a `LiveTurn` for that thread. Any channel that can name the thread can carry it later.
- **A bench shows its whole talk, not only the open conversation.** A conversation records the thread it started on
  (`conversations.thread`, written by `for_thread`; before that column existed only the thread's current conversation
  was placed), so `GET /api/benches/{id}/conversations` pages every conversation on `bench:<id>` through the same
  `history_page` her room's history uses, and the page shows them above the open one under the same dividers
  (`Earlier`). Only the bench's owner reads it, anyone else's id is 404, and a conversation reads by its id under the
  taking-part key. A closed talk is not an empty one: a bench lives for days, longer than a brainstorm stays open.
  What she carries on the bench's next turn is unchanged: the owner's latest turns across conversations, this bench's
  closed talk included, since each was private to the owner. Rejected: a second history route for benches, and
  never closing a bench's conversation.
- **Large pieces live in S3 on both sites' NAS** (family `large`, kinds `image` and `file`; `ashley.files`; each
  site's NAS S3 endpoint, the ones WAL-G writes to). The piece's body is a JSON
  descriptor of its bytes (`ashley.workshop.stored_file`: `sha256`, `size`, `media_type`, `name`), capped by the kind's
  `max_chars`; the bytes are one object, `bench/<household id>/<sha256>`, in one bucket. A write goes to every endpoint
  of `FILES_ENDPOINTS` at once (this site's first) and counts when one took it; a read takes the first endpoint that has
  it; a singleton under the lease (`ashley.files.repair`, every `repair_interval_s`) copies what one site holds and the
  other lacks under the bench and look prefixes, and does nothing while a site cannot be listed. So both sites reach the bytes with no shared mount, and
  an upload made while a site is down is whole on both within an hour of its return. The Postgres row is the index and
  the log; there is no table of copies. Keys carry the household, so the same file in two households is two objects and a
  link to one reaches only its own. The store is a service behind the locator (`ashley.files.store.ObjectStore`, a Null
  Object that raises `StoreUnavailable`, `ashley.files.s3.S3Store` over one endpoint, `ashley.files.mirror.MirroredStore`
  over several, `ashley.files.memory.MemoryStore` for tests), so swapping the store changes only the adapter.
  - **Bytes no piece names are swept** (`ashley.files.sweep`, a singleton under the lease of its own, every
    `sweep_interval_s`): the repair's listing, extended to carry when each key was last written, is compared with what
    benches name (`ashley.workshop.file_references`: large pieces on any bench, shelved included, and those in the last
    `undo_window` commands of a bench's log, since undoing a Remove needs the bytes). A key is deleted from every site
    only when it is unreferenced, younger than `sweep_grace_s` on no site (an upload in flight has bytes before its
    piece), and found so by the pass before too; those findings are the rows of `file_orphans`, not pod memory, so the
    next pass may run anywhere. A refused or failed upload and a removed piece's bytes both end there. A site that
    cannot be listed or deleted from is skipped for the pass; the others go on, and a copy left on a down site is
    deleted once it is back (repair may copy it across first, which only costs one more pass). The references are read
    after the listing, so a piece committed during a pass is seen; what remains is the seconds between that read and
    the delete, which the grace and the second pass make a retry of old bytes' problem alone. Rejected: a second lister
    (the sweep goes through `ObjectStore.listing`, which `keys` is now defined by); candidates held in memory, which a
    failover or rollout loses; deleting on first sight, which a put racing the pass would lose.
  - Rejected: an NFS PVC per site. It is two unreplicated filesystems, and mounting both sites' exports from each means
    `hard` mounts that hang a surviving site's pods in D state when the other site goes, or `soft` mounts that trade the
    hang for corruption. Rejected: MinIO bucket replication as the mechanism, whose lag shows only when a site is read
    (as WAL-G's record says). Rejected: refusing an upload unless both sites took it, which stops uploads exactly when
    a site is down; the repair closes the gap. Rejected: Postgres `bytea` or large objects, which put files through
    WAL and both sites' replication. Rejected: a table of which site holds which object, which the listings answer.
- **Her tools on a bench are the person's Commands, made by her** (`ashley.tools.bench_tools.BenchTools`, offered only
  on the bench's talk): `bench_read` (every piece with its id, kind, title, version and place, its body cut to
  `read_body_chars` with `body_cut` saying so, and the latest commands by seq), `bench_read_piece` (one piece, a
  window of at most `piece_chars` from an `offset`), `bench_add`, `bench_edit` (with the version she read),
  `bench_replace`, `bench_move`, `bench_remove`, `bench_archive`, `bench_shelf` (the shelf's ids, kinds, titles and
  versions; `bench_read` says how many it holds as `shelved`), `bench_restore` and `bench_undo`.
  She arranges what she adds in the turn she adds it (order by how a reader takes the pieces, size by what each is),
  tidies a bench that has grown untidy once, and leaves a tidy one alone. `bench_read` gives each piece
  `last_changed_by` (`you` or `person`, from the command it last changed by), and her guidance has her fit her pieces
  around a person's and never move or resize one. The guidance is instruction data (`bench_specs.INSTRUCTIONS`). Rejected:
  a refusal in `decide` for her moving a person's piece, which would make the Workshop judge whose layout it is.
  Each builds the Command a person's route builds, `by` her, through `Workshop.apply`; a refusal comes back as a tool
  error naming the reason (`stale_base`: read again and redo). An edit replaces the whole body, so she may edit only a
  version she read or wrote whole in the same turn; anything else is refused `unread` before the Workshop sees it, and
  a piece longer than `piece_chars` she changes with `bench_replace`: an exact `old` snippet that must occur once in
  the whole body, and a `new` in its place, on a version she has read any window of. It builds an ordinary `Edit`
  from the current body, so the version check, log, undo and replay are the Edit's and there is no new Command. A
  snippet found nowhere or more than once is `bad_arguments` and changes nothing. Rejected: a line or offset range,
  which names a place and silently edits the wrong text when the body shifted or she miscounted, while a snippet
  names the text itself. Rejected: scanning her prose for fenced code to make pieces, since behaviour keys on fields;
  code she writes for the bench goes in through `bench_add` with kind `code` (`kinds.json`, format `code`), her
  choice, and the instructions tell her so. A code kind carries one `language` (`text`); a language per piece would
  need a field on every piece and is not built. Tunables: `app/ashley/tools/bench_tools.json`.
- **A code piece is run by a Run command** (`ashley.workshop.commands.Run`): the piece, the version the runner saw and
  a language the sandbox runs. The person's Run button (`POST /api/benches/{id}/runs`) and her `bench_run`
  (`ashley.tools.bench_run.BenchRunTools`, on a bench's talk while a sandbox is wired) both go through
  `ashley.workshop.run_piece.run_piece`: `decide` judges the Run (`no_such_piece`, `unknown_kind`, `not_runnable` for
  a kind whose format is not `code`, `stale_base`) and it is logged, then the body runs once through the one runner,
  `ashley.runs.once.run_once`, recorded in `code_runs` against that command (and her turn, for hers), and the owner's
  screens are told again when it has ended. A run the sandbox cannot take (a language it does not run, a blank piece,
  a body over `max_script_chars`) is refused before anything is logged, since `decide` does not know the sandbox.
  - **What it gave is shown on the code piece**: each piece of a read carries its latest run (`BenchPiece.last_run`),
    read from `code_runs`, never stored twice; `bench_last_run` gives her the same. Rejected: an output piece added
    by the run, which takes a slot on the bench, is editable text posing as a result, needs an undo of its own, and
    on the next run must either pile up or overwrite a piece someone may have changed.
  - **The files go back in, and no pod keeps them.** A run starts with the files left by the piece's latest run that
    ran to its end (outcome `ran`, any exit code); one stopped, killed or lost part way may have left them half
    written, so it passes nothing on and the one before it still does. They are already within the runs' file limits.
  - **A run is never undone.** Its effect, `Ran`, changes no piece (not its version, place or `changed_by`); Undo never
    names it (the walk passes over it as over a refusal), an Undo naming one is `nothing_to_undo`, and it never makes
    the change before it `changed_since`. Undoing an edit leaves the last run, and the files it left, as they are.
    Rejected: refusing the Undo of a run, which would stop the walk there and strand every change before it.
  - **A piece keeps two runs, and a run goes when a newer one replaces it.** Recording a bench run's result deletes,
    in the same transaction, that piece's finished runs but for its latest run, its latest that ran to its end (the
    one its next run's files come from) and the one just recorded, and logs `runs.pruned` with the bench, piece and count. So a bench's runs stay
    at about two a piece however long it lives, and a removed piece's last two stay with the bench. A run with no result yet is work in flight and is never
    pruned, so two runs pressed close together both keep their results; the one just recorded waits for the next
    finish to go. A run lost with its pod never gets a result and stays, as the "No result recorded" row it is.
    A run asked for by a chat turn is never pruned: it is shown in its conversation and carried in history, and goes
    with its turn (`ON DELETE CASCADE`); nothing deletes a conversation or a bench today. Rejected: a retention job on
    a timer, a second thing to keep running; an age limit, which would drop the files a long-idle piece's next run needs.
  - **It survives its pod as any change does**: the command is logged before anything runs and the run recorded
    before it starts, so a pod that stops part way leaves an accepted Run with no run (it never started) or a run with
    no result (shown as "No result recorded"); neither is run again, and her `bench_run` is a change to the tool loop.
- **A site or video piece is a reference the page frames, its body checked by the server** (kinds `site` and `video`,
  family `live`, `ashley.workshop.embed`). A site's body is one https URL that is not a YouTube or Vimeo page, which is a
  video piece, hers or the person's (no credentials, at most 2000 characters; whitespace
  inside it refuses it, whitespace around it is trimmed and the body is stored trimmed, a whitespace-only body being the
  empty one; a video's `url` field is trimmed the same way, in the stored JSON); a video's is a JSON object `{"url", "start"}`, `start` whole seconds, the field a pointer into the video
  will name; a `start` in the URL (YouTube `t=` or `start=`, Vimeo `#t=`, as seconds or `1h2m3s`) is the start when the
  body gives none, and the body's `start` wins. An Add or Edit of anything else is refused `bad_site` or `bad_video`; an empty body is a draft. The video's
  URL is a YouTube or Vimeo page, shown through the provider's privacy embed (`youtube-nocookie.com`,
  `player.vimeo.com`, an unlisted video keeping its hash) derived from the parsed host and path, or a direct media file by its path suffix; the server
  serves the result as `BenchPiece.video` (`provider`, `url`, `embed_url`, `start`) so the client derives nothing, and
  nothing autoplays. A site is an iframe with `referrerpolicy="no-referrer"` and a sandbox of `allow-scripts
  allow-forms allow-popups`, never `allow-same-origin` and never `allow-popups-to-escape-sandbox`, so a framed
  site cannot reach the page's cookies or storage and a window it opens stays sandboxed too; the cost is that a site reading its own cookies loses them. A provider's player gets
  `allow-same-origin` too (its own origin, a fixed host) and `strict-origin-when-cross-origin`, which YouTube requires.
  Many sites refuse framing and the page cannot detect it, so "Open in a new tab" is always shown. The app sets no
  CSP, so no `frame-src` changed.
  **The server decides whether a site frames, from its headers, and the page shows a card when it does not.** A site
  piece is served as `BenchPiece.site` (`frameable`, `title`); `frameable` is a measured true or false, or null for
  unknown. The first read of an open bench that finds a site address with no measure asks the site once in the
  background through the `FrameProbe` service (`ashley.workshop.frame_probe`, implemented by `ashley.tools.site_probe` over
  the page reader's request, the same request-forgery checks, so the workshop and the API make no request themselves), decides
  from the final answer's status and headers alone (`ashley.tools.frame_policy`: a non-2xx status, `X-Frame-Options` `DENY` or
  `SAMEORIGIN`, or a `frame-ancestors` that names neither our origin (`public_url`), `*` nor `https:`; a
  `frame-ancestors` overrides `X-Frame-Options`, as in a browser), records it in `bench_site_frames` by bench and address,
  and tells the person's screens the bench changed (`BenchChanged` with `seq` 0). An address that gets no answer is
  recorded unknown and not asked again until it leaves the bench and returns; the record is dropped once no piece holds
  the address. Only `false` makes the client show a card (host, the page's title, "Open in a new tab") in place of the
  frame; unknown renders as ever, the frame and the link. Logged as `bench.frame` with bench, piece and outcome. Rejected: reading the
  page's text to guess, or a client probe (a refused frame cannot be told from a slow one); a column on the piece (the
  fact belongs to the address, and the piece's versions would churn); measuring on every read. She makes them with the ordinary piece tools; a person adds one from the Add card with an
  address (and, for a video, a start as seconds or `m:ss`), which the page shapes into the body and the server judges. Rejected: regex over a pasted URL in prose to pick a provider; a `provider` field she
  would have to get right, which the host already says.
- **An automation piece is Home Assistant's own automation config, as JSON the code checks** (kind `automation`,
  format `automation`, `ashley.workshop.automation_config`): one object of HA's field names (`alias`, `description`,
  `triggers`, `conditions`, `actions`, `mode`, and `max`, `max_exceeded`, `variables`, `trigger_variables`), each of
  its type, every trigger, condition and action an object, with no `id` (the install owns it). An Add or Edit of
  anything else is refused `bad_automation`; an empty body is a draft. What a trigger or action means is HA's to judge
  when it is written. The room reads it as When, Only if and Then, one line per item, with the JSON folded under it,
  and edits the JSON in the ordinary editor. Rejected: YAML text, which code cannot check without HA's schema and
  which turns every edit into a parse; a form, which nothing needs yet.
- **Installing is her Propose and the person's Install, both Commands** (`ashley.workshop.commands.Propose`,
  `Install`). She proposes a piece at the version she read (`bench_propose_install`), with whether it is enabled and
  an old automation to turn off; `decide` refuses `not_installable`, `stale_base` or `incomplete` (no alias, trigger or
  action), and a Propose changes no piece and is never undone, as a Run. The room shows her proposal on the piece
  (`BenchView.proposals`, read from the log) with an Install button; the person's `install` command names it, and is
  refused `no_proposal` (not this piece's, or installed already) or `stale_base` (the piece changed since). Only a
  person installs and only a person undoes an install: hers are refused `needs_person`, so every write to the house,
  either way, is the person's. Her tools write nothing outside the bench.
- **An accepted Install is carried out on the house after it is logged** (`ashley.workshop.install_piece.carry_out`,
  called by the commands route, which answers once it has ended), recorded in `bench_installs` before its first
  write and again when it ends (`ashley.workshop.installs.Installs`): it reads what HA holds under the piece's id and
  whether the old automation is on, records that, writes the config, turns it on or off as proposed, then turns the
  old one off. A pod that stops part way leaves an accepted Install with no record (nothing was written) or a record
  with no ending (shown as such: check the house); neither is carried out again, and a second carry-out of one command
  writes nothing. HA refusing the config ends it `refused` with HA's own message; HA out of reach before anything was
  written ends it `failed`, touching nothing. A new automation is on for the moment between its write and its turning
  off; rejected: HA's `initial_state`, which forces its state at every HA restart.
- **A piece is installed under one id, `ashley_bench_<bench>_piece_<piece>`**, so its first install is fresh and every
  later one an update of the same automation. An install never writes over an automation under that id that no
  earlier install of the piece wrote (`failed`, nothing written), since a test database's bench shares the id with
  production's. Rejected: a random id kept on the piece, which a later install would have to look up and a race could
  fork.
- **Undoing an install takes it back from that record**, as an `Uninstalled` effect carried out the same way: a fresh
  install is deleted (nothing of it is left behind); an update has the config and on/off state HA had before written
  back; the old automation is turned on again only if the install found it on. An install that wrote nothing has
  nothing to take back. Rejected: disabling instead of deleting a fresh install, which leaves dead automations in
  HA's list for every trial.
- **She opens a bench from the person's own web chat** (`ashley.tools.open_bench.OpenBenchTools`, offered only there,
  the speaker known): `open_bench` with a title of hers, returning the bench's id and the room's path,
  `/workshop/<id>`, which her reply links to; the link opens the bench in place, and she can take the page there
  herself ("She moves the person's page herself").
- **A person opens a bench from the list by asking** (a field that asks "What are we making?" implies she will
  answer what is asked). `POST /api/benches` takes an `ask` (the talk's 1 to 4000
  characters), a `title`, or both. An ask is the person's first message in the bench's talk, whole, and she answers it
  in a bench turn that leads, as on a bench she opened herself: the route builds the talk's `Inbound` with `lead`
  (`ashley.api.bench_opening`), which `channels.turn_tools` reads as it reads a fresh `Arrival`, so there is one lead
  and one turn path. The turn runs on its own after the route answers, and the bench's id is its `source`, so a bench
  is one turn. A title alone opens a bench and starts no turn.
- **A bench is named by a Command.** `Rename` (`ashley.workshop.commands.Rename`, her `bench_rename`) sets the bench's
  title, refused `bad_title` when empty or past `title_max_chars`; its effect `Renamed` changes no piece, and Undo
  names the title back (`changed_since` once a later rename stands). A bench opened with only an ask is titled from it
  (`ashley.workshop.provisional.provisional_title`, cut at a word with an ellipsis) until the lead has her rename it
  in her first turn. The person's own rename is not on the wire yet. Rejected: asking the model for the title in the
  open request, which would make opening wait on a model call; a title column she writes outside the log, which
  would be neither undoable nor on Live.
- **Logs** carry bench, command and piece ids, the command's type, the kind, the author (`person` or `ashley`) and the
  outcome (`workshop.opened`, `workshop.closed`, `workshop.reopened`, `workshop.command`, an install's
  `workshop.install_started`, `workshop.install_finished` and `workshop.install` with its automation id, and her
  tools' `tools.call`); never a title, a body or an automation's config.
- **The bench is in her prompt.** Each turn's moment carries the bench as it stood (`Catalogue.now`). An
  outside-kind piece shows only id, kind and version, so the view never taints. Rejected: bench_read every turn
  (a model step of about 4 s, and a taint whenever a file is on the bench); the view in `stable` (cache churn).

## She reacts to a person's bench change

When a person's commands on a bench stop for a pause, she gets one turn on that bench and may say something or stay
silent (as tldraw's agent is handed the user's changes since its last request). Fits into: Initiative (whether it
goes out), the `wakes` singleton's lease and the shared turn loop (the turn, its inflight row and resume), and the
Workshop's log (what changed); it adds no singleton and no turn path. Rejected: a wake row per reaction, which would
store a debounce the command log already is; a timer per bench in a pod, which a rollout loses.

- **The trigger is derived, not stored.** `Workshop.unseen` finds the open benches where a person's accepted commands
  came after the last she has seen and the newest is at least `pause_s` old (`bench_react.json`). Her own commands, a
  refusal and a closed bench never count. The `wakes` sweep (under the `wakes` lease) reacts to up to `batch` of them,
  so any pod on either site does it, and a killed one loses nothing: the next sweep finds the same state.
- **The last command she has seen is the newest `bench_reactions` record's `to_seq`**, not a column the bench keeps,
  because the same rows bound how often she reacts. It is written once the turn is handed to the loop. Her next
  reaction is handed only the person's commands after it, as `#seq type kind piece` (ids and kinds, at most `listed`,
  with a count of the earlier ones), in the stored household turn; nothing is handed twice. A bench that had work
  before this existed starts with a record at its newest command.
- **A reaction handed in twice is one turn.** Its `source` is the bench and the last command handed
  (`bench_react:<bench>:<to_seq>`); the turn loop's inflight row makes a killed runner's turn finish on any pod
  ("Work in flight survives its pod"). The turn is `unprompted` on the bench's thread with the owner as speaker and
  `author` `household`; what she is told to do reaches her only as the turn's `note`.
- **A reaction holds like a person's turn**, from the explicit `Inbound.watched` its adapter sets, since the person is on
  the bench's page by construction and watched the work start. Her aside goes out as a held line past `hold_after_s`
  and stays her turn on the talk; the answer is stored after it and, with `worth_saying` false, as her staying quiet,
  which hides only that turn and the household turn it answers, never the aside. It is stored (`later_by` `turn`), so
  nothing is queued. Other wakes keep never holding.
- **Reply or none is `Reply.worth_saying`**, decided by Initiative, never read from her text. None stores her staying
  quiet, and a page leaves that turn and the household turn it answers out (`ashley.conversations.quiet.shown`), and the
  list of conversations counts only what a page shows, so a conversation holding nothing else is not listed and
  nothing appears in the talk. A reply is an ordinary turn on the bench's talk.
- **At most `max_reactions` per bench in `window_s`**, in code (`bench_reacts.wait_s`) over the records in the window; a
  capped bench waits, its changes unseen, and is reacted to once one record leaves the window. Records older than
  `keep_s` are deleted when the next is written, the newest always kept.
- **Logs** `bench_reacts.done` with the bench id, how many commands were handed, `reply`, `none` or `pending`, and the
  duration; `bench_reacts.capped` once per wait; `bench_reacts.deferred`, `bench_reacts.refused`; never a piece or a
  message.

## Her bench's text is checked for what editing left stale

Her notes rot: over nine whole-body edits one note went from 1.3k to 4k characters because each edit kept the old text and
bolted the update on, a header was pasted in front of the list it introduced, and two pieces went on saying a thing
was still not found after another piece had found it. She had the text in context each
time, so it is method, not memory. Two changes, neither of which decides anything for her. Fits into: the Workshop (the
text it holds), Inference (a new task, as `memory_judge` is), and the reactions' shape (a trigger derived from state,
the last-seen recorded); it adds no singleton and no Command. Rejected: a model that rewrites or deletes the text
itself, since she is the judge and the checker is cheap and sometimes wrong; a rule that caps a note's growth, which
treats the symptom.

- **The guidance says it once** (`ashley.tools.bench_specs.INSTRUCTIONS`): a note holds the current state, and an update
  rewrites the section it changes and drops or moves what it supersedes.
- **A cheap model points at passages** (`ashley.tidy`, task `bench_tidy`, flash-lite first with haiku as the fallback: on one bench's notes flash-lite flagged the stale "not found" lines in every run and haiku in none). It reads the
  bench's text pieces (`tidy.json` `kinds`: note, document, code, model, measurements; never a page she is reading, a
  site, a video or a file) and replies in structured fields, `{piece_id, kind, quote, by_piece_id, why}` with `kind` one
  of `superseded`, `contradicts`, `debris`, `duplicate`. Code keeps a finding only when its piece was sent, the quote is
  in the body the model saw and within the bounds, and it is not a repeat; invented quotes are dropped and counted.
  The prompt is bounded by `max_piece_chars` per piece and `max_total_chars`, most recently changed first.
- **When it runs:** after a turn on a bench, apart from the reply (`ashley.channels.bench_after.tidy`, a background task like the memory
  act, never awaited). It asks the model only when a text piece's version differs from what the last finished pass
  recorded (`bench_tidy.versions`), so a move, a resize, a site piece or an unchanged bench costs no call; a person's edit
  counts at the end of the next turn. One pass holds a bench at a time (`Tidy.begin`, `lock_s`, across pods and sites); the
  versions are recorded only when a pass finishes, so a pass lost to a restart, a model out of reach or a pass already running
  is simply made up by the next turn's end. Rejected: a sweep singleton, because the end of the turn already marks the moment
  and a bench nobody talks on gains nothing from being checked; running before her reply, which would delay it.
- **Findings are durable** (`bench_findings`, keyed to the bench) and wait for a next turn that may be days away. A finished
  pass replaces the bench's open findings; a dismissed one stays, unseen, so the same passage is not pointed at again while
  it stands. Findings older than `keep_s` are deleted when the next pass writes.
- **She is offered them at the start of her work, in `bench_read`** as `to_check` (at most `shown`, oldest first, each with
  `id`, `piece_id`, `kind`, the exact `quote`, `other_piece_id` and a short `why`), with one line of tool guidance: check
  each against the pieces, fix the right ones with an ordinary edit (undoable and logged like any), and `bench_dismiss`
  the rest. A finding whose quote is no longer in its piece is deleted at the next read, so an edit by her or by the person
  clears it; a dismissal marks it. Rejected: putting them in the system prompt, which would change it under a cached prefix
  and go stale mid-turn as she fixes them.
- **Logs** `tidy.pass` with the bench id, outcome (`unchanged`, `busy`, `ok`, `unavailable`, `refused`, `bench_gone`),
  pieces sent, findings kept per kind, findings dropped and duration; the tool call lines carry the finding id. Never a
  quote, a reason or a piece's text.

## Her skills are method documents she edits

- **A skill is data**: a method document (Type Object), not code, one per kind of work. **Kinds of work are hers**: a
  kind is a household's row (`skill_kinds`: a slug and a label), started by her or the person when they set a bench's
  work to a name the household has none for, and its first skill version is written the same way. A slug is checked by
  shape (`app/ashley/skills/skills.json`: pattern and length), never against a list, so she is never handed a gap
  ("electronics", "garden planning") to give back; code, 3D, research and writing are what the seeds may start with.
  Rejected: a fixed list of kinds in `skills.json` (a kind a bench needs and the list lacks would be hers to ask a
  person for). A bench carries its kind, `benches.work`; she sets it with `bench_work` (a new kind needs its `label`)
  and the person may change it in the bench's bar, which can also start a kind. It is a bench field changed by an operation outside
  the command log, as closing is, not a Command: a label the person overwrites needs no replay or undo.
  Rejected: a Command (a dozen files of codec, decide and effects, for a label replay and undo have nothing to do with), a `skill`
  piece kind (a piece is bench-scoped and a person's; a skill outlives the bench and serves every bench of that kind).
- **A household's skills are the household's.** Versions are stored per household and kind
  (`skill_versions`), so what she learns in one household never reaches another and any person of the household sees the
  same method. Until the household first edits a kind, the skill is the seed that ships (`ashley.skills.seeds`,
  `app/ashley/skills/seeds/<kind>.md`, whose front matter names the kind, its label and the source skill it was
  `seeded_from`; a seed's kind exists for every household). Four ship (code, 3d, research, writing), each rewritten
  for a bench from a personal Claude Code skill with every host, path, name, dated incident and Claude Code mechanic removed
  (`tests/test_skill_seeds.py` scans for those shapes). They are loaded once when the process wires and read at each
  use, never copied into a household's rows, so a household's edit is never touched by a seed that changes later; the
  first
  edit replaces it for that household only, and a rollback to version 0 is the seed again. Rejected: one global
  skill she edits for everyone (one household's conversations would rewrite another's method); copying the seeds into
  every household's rows at creation (an improved seed would never reach an unedited kind); a skill per person (method
  is not personal, and each person would teach her again).
- **The skill loads beside the bench tools' instructions, in the stable layer.** `ashley.tools.bench_skills.BenchSkillTools`
  puts the bench's skill in its catalogue's instructions, which `persona.system` places in `stable`, before the moment
  and the history (the cache layers in "Every channel shares one turn loop"). It is read when a turn's tools are built, so a kind she
  sets or a skill she edits reaches the prompt of the person's next message (setting the kind gives her the skill as
  the tool's result meanwhile), and a conversation pays one cache write when a skill changes, which is rare. Each load logs `skills.loaded` with the bench, kind and version. Rules that must always hold
  stay in her fixed guidance, never in a skill; the tool guidance says a skill never overrides them.
- **She edits skills freely and an edit is live at once.** `skill_edit` replaces the whole body from the version she
  read (`stale` otherwise) with a line each of what and why; `skill_rollback` makes an earlier body (0 is the seed)
  the next version. Versions are append-only, so a rollback is a new version and the changelog (what, why, which bench,
  who) never loses an edit. The edit count per skill is the number of live versions. A person's rollback, pin and
  approvals are on the bench's bar (`app/ashley/api/skills.py`); her `skill_read` gives her the changelog.
- **Approval applies only to a skill the person pins.** Her edit of a pinned kind is stored `proposed` and loads only
  when a person approves it; an approval is refused `stale` once the live version has moved past the one she
  proposed against. Rejected: approval of every edit, since routine edits are too frequent for it to mean anything.

## Benches carry files, photographs and 3D

- **Uploads and downloads are large pieces**: `image` and `file` kinds (above); a person uploads from the bench page and
  downloads any file piece. A PDF or a zip is a `file` piece; `document` stays Markdown in Postgres.
  - **An upload is the request's raw bytes** (`POST /api/benches/{id}/files`, `ashley.api.bench_files`), judged and
    kept by `ashley.files.intake.take` and added by an ordinary Add (`ashley.workshop.bench_file.add_file`), so the piece
    is live, logged and undoable like any other. The name and the type the browser gave ride in the headers `X-File-Name`
    (percent-encoded) and `X-File-Type`, never in the URL or the logs; the body type is `application/octet-stream`,
    which a cross-site form cannot send (`ashley.api.person.Uploading`). It is read into memory, so the size is bounded:
    `max_bytes`, 25 MiB; a longer request is 413, by `Content-Length` or as its body streams in.
  - **Content decides the type, not the client** (`ashley.files.sniff`, signatures and limits in
    `ashley/files/files.json`): a signature of the config (PNG, JPEG, GIF, WebP, PDF, zip), else UTF-8 text with no
    control characters (`text/plain`, or `text/csv`, `text/markdown` or `application/json` when the client named it), else
    415. A file that says it is a type the config knows and is another is 415 too. The type stored is the sniffed one, so
    markup uploaded as `text/html` is a `text/plain` file. Rejected: SVG and HTML as images or files, which run script
    when opened; trusting the declared type; a content-sniffing library, which adds a dependency for seven signatures.
  - **A large piece is made only from bytes, and its bytes never change.** `decide` refuses an Add whose body is not a
    stored file of the kind (an image's media type is an image's) and an Edit that changes the body (`bad_file`); the
    commands route and her `bench_add` refuse an Add of a large kind outright, since a body they wrote names bytes no
    one uploaded. An Edit may retitle the piece.
  - **A bench viewer reaches the bytes through a link of the app's own**, `GET /api/files/{token}` (`ashley.files.links`):
    a token signed under `FILES_LINK_KEY`, shared by every pod, naming household, hash, media type, whether to show it
    in place and when it ends. It is the only credential, so an `<img>` and a saved download need no session, and it
    carries no file name. A bench read hands out links ending at the end of the next half-`link_ttl_s` window (900 s), so
    the address is stable within a window and the browser keeps the image; the page reads the bench again 30 s before
    the earliest ends. Served with the sniffed type, `nosniff` and `Content-Security-Policy: sandbox`, in place only for
    images, as an attachment otherwise. Rejected: presigned S3 URLs, which point a browser at the NAS; the session
    cookie as the credential, which an `<img>` in another tab, a download manager and later `bench_look` would each need
    to carry; the file name in the token, which the access log would then hold.
  - **She adds and reads files** (`ashley.tools.bench_files.BenchFileTools`, offered while a store is wired):
    `bench_add_file` makes a file piece from text she writes or from what a code piece's latest run gave (its output, or
    a file it left), its type chosen by the name's extension and checked against the bytes like an upload. Her
    `bench_read_piece` on a text file piece reads the file's text in windows; on any large piece `bench_read` gives its
    name, size and type, never its hash. Her edits and moves of a file piece are the ordinary ones.
  - **Logs** carry household, size, media type, copies, counts and durations (`files.stored`, `files.refused`,
    `files.served`, `files.copy_failed`, `files.read_failed`, `files.repaired`, `files.repair_failed`, `files.sweep_started`,
    `files.sweep_store`, `files.swept`, `files.sweep_list_failed`, `files.sweep_delete_failed`, `files.sweep_failed`), never a name,
    a token or a byte.
- **`bench_look` gives her eyes on the bench** (`ashley.tools.bench_look.BenchLookTools`, on a bench's talk while an
  object store is wired): a piece (`piece_id`) or the whole bench, returned as an image in the tool result
  (`ashley.inference.model.ToolResult.images`: an Anthropic `tool_result` holds image blocks; Chat Completions, which
  Gemini and OpenAI share, takes a tool message as text only, so the pictures follow it in a user message, each after a
  line naming its call; a checkpoint keeps them as base64). An image piece is always given from its own bytes, never
  drawn: oriented by its EXIF, cropped to her optional `region` (fractions of the oriented picture, taken from the
  original pixels before the scale), scaled to `max_image_px` on its longest side and re-encoded as a JPEG under
  `max_image_bytes` (`ashley.looks.pictures`, Pillow; a source over `max_image_pixels` is refused `too_large` before it
  is decoded). Everything else (a document, code, a design, a model, the whole bench) is a JPEG screenshot of the bench's page taken by headless Chromium in a pod of the sandbox namespace
  (`ashley.looks.kubernetes.KubernetesLooker`, one pod per look, deleted however it ends, no state on a node, so
  either site takes any look; a warm pod takes it first, below). The pod opens `/look/<token>`, the client's own page (`rooms/workshop/look/`) drawing
  the same piece components read-only, and waits for `body[data-look="ready"]`; its data is `GET /api/look/{token}`.
  The token (`ashley.looks.links`) names household, person, bench and optionally a piece, lasts `link_ttl_s`
  and is the only credential; it is a different purpose from a file link. With no browser wired
  (`LOOK_IMAGE`, `LOOK_APP_URL`) only an image piece can be looked at.
  - **The picture is kept with the turn.** Its bytes go in the object store under `look/<household>/<sha256>`
    (`ashley.looks.keys`), never under the files' `bench/` prefix, so a sweep of files no piece names cannot reach what
    a person's history shows; an image piece's own bytes are copied there for the same reason. The row
    (`ashley.looks.looks.Looks`, table `bench_looks`, unique per turn and call) names it, and the conversation routes
    serve it under her final answer as `ChatTurn.looks` with a picture link (`GET /api/looks/{token}`, a third
    purpose, ending in the files' `link_ttl_s` half-windows like a file link, not the look's own `link_ttl_s`). The files repair singleton keeps both prefixes whole on every site (`ashley.wiring_singletons.REPAIRED_PREFIXES`), so a look taken
    on one site is served after a failover; the sweep lists `bench/` only and never reaches a look.
  - A model piece takes a `view` (`ashley/looks/views.json`, matched by the client's `SIDES`): the look's address carries
    `?view=<side>` and the page draws that one side where it would draw the four-view sheet, which stays the answer
    when she names none. `region` also crops a screenshot, though that holds no more detail than the screenshot.
  - Limits are data (`ashley/looks/looks.json`): the screenshot's size, `max_image_bytes`, `max_looks_per_turn` (counted
    from `bench_looks`, so any pod agrees; a call run again after a resume replaces its row), the pod's deadline and
    limits. A screenshot over `max_image_bytes` is refused (`too_large`) like any look that cannot be taken, and kept nowhere.
    Each look logs `tools.call` with bench, piece, `how` (`piece` or `screenshot`), `region` (0 or 1), `view`, bytes and `px` (the longest side, `-` when unread), and the pod
    logs `looks.pod`; never the picture, the token or the page's content.
  - Rejected: a screenshot of an image piece, which costs a pod to give her bytes already in the store. Rejected:
    pictures in Postgres, which puts them through WAL and both sites' replication. Rejected: rendering the bench in
    Python, which would be a second, drifting copy of the client's piece components. Rejected: extending the code
    sandbox's `Job`, which is a text script with no network and text output; a look needs a browser image and one
    route to the app, so it is its own Strategy beside the sandbox, sharing its API client, namespace and RuntimeClass.
  - **Cluster side** (the cluster repo): a pinned browser image (Python with Playwright and Chromium), a network policy
    letting pods labelled `ashley.yggdrasil.pub/look` resolve DNS and reach the app's Service port only, a quota for
    one 1 CPU and 1 Gi pod beside code runs, and the app's `LOOK_IMAGE` and `LOOK_APP_URL`. The warm pod adds a Service
    `ashley-look-warm` (port 8080, selecting `ashley.yggdrasil.pub/look-warm`), a policy letting the app's pods reach that
    port, the app's `LOOK_WARM_URL`, and a quota for a second look pod beside it.
  - **A warm pod takes the look first.** A cold look spends about 40 s starting its pod, so each cluster keeps one
    (`ashley.looks.warm_pod.WarmPod`, named `look-warm`, the look pod with a server in place of a page: `shooter.serve`).
    `ashley.looks.warm_looker.WarmLooker` sits in front of the same `KubernetesLooker` (an Object Pool of size one, not a
    second looker): it posts the page's address to the pod's Service and gets the same marked line back. The pod takes one
    look at a time; a call that finds it busy (503), missing, unreachable, timed out or broken (`browser`, no picture)
    is taken in a pod of its own as before, so a look is never lost to the warm pod. A page that never drew
    (`not_ready`) or a picture too large is the answer and is not tried again.
    - **Held per site, under the lease.** The pod lives in one cluster, so its keeper is a singleton per site
      (`Lease.run_on_site`, key `look-warm@<site>`), unlike the others, which run on the active site alone: the standby
      site's app pods take looks too and reach only their own cluster's pod. Any app pod on the site uses the pod; the
      holder creates it when there is none, replaces it when it ended, was made for another image or limits (an
      annotation holds a hash of the spec) or is older than `warm_max_age_s`, and otherwise leaves it, so a new holder
      adopts the pod it finds. A look is a request, not a session, so nothing is lost when the holder changes.
    - **Nothing one look held reaches the next.** Each look launches its own browser process and closes it, so
      no cookie, storage or cache outlives the look; whatever a look left in `TMPDIR` is removed before the next is
      taken. The pod opens only addresses under the app's look page (`ASHLEY_LOOK_PREFIX`), judged after resolving the
      address as a browser does (tabs and newlines dropped, `\` as `/`, percent-encoded dot segments removed) and
      handing the browser the resolved address; the cold pod takes the app's own address and checks nothing. It has the look pod's
      account-less, read-only, gVisor spec and the same network policy, and is reached only by the app's pods.
    - **Limits are data** (`looks.json`): `warm_tick_s`, `warm_max_age_s`, `warm_connect_s`. Logs: `looks.warm` (outcome,
      bytes, duration), `looks.warm_fallback` (reason), `looks.warm_started`, `looks.warm_adopted`, `looks.warm_replaced`
      (reason), `looks.warm_failed`; never the page's address or content.
    - Rejected: an etcd lease on the active site for the keeper, which leaves the standby site's pod unkept. Rejected:
      one warm pod for both sites, which every look from the other site would reach across the link. Rejected: reusing
      one browser across looks, which saves about a second and shares a profile between households. Rejected: an
      exec into the pod, which wants `pods/exec` for the app's account.
- **She watches a video and listens to audio** (`ashley.tools.bench_media.BenchMediaTools`, on a bench's talk while a
  store and a media worker are wired).
  - **A video file is a `clip` piece and an audio file an `audio` piece**, large kinds chosen by the bytes' media type
    (`piece` in `files.json`'s `types`: MP4 and QuickTime by their `ftyp` brand, WebM, MP3, M4A, Ogg, WAV, FLAC), played
    by the page's own `<video>` and `<audio>` from the file link, which answers one `Range` (206, else 200; 416 past the
    end) so the controls scrub. `video` stays the embedded provider kind. A cue (`bench_cue`) drives any of the three; the
    page says what she did in a line of text beside the player, which needs no motion.
  - **A transcript is a reader piece beside the recording**, one `[m:ss] text` line per segment, with no address (a
    reader's `url` may now be empty: text from no page). `bench_transcribe` takes captions first: a `.srt`/`.vtt` file piece
    she names (`captions_piece`, parsed in the app), else the captions inside the file, else the sound. The sound is cut
    into windows of `window_s` seconds, each sent to the speech service and stamped by its start, so a time is exact to a
    window, not a word; a window of near silence is not sent, since whisper invents words for it.
  - **A transcript names its recording** in the reader body's `recording` (`ashley.workshop.reader.Recording`): the
    recording piece's id and the second each line starts at, written by `bench_transcribe` and served as
    `BenchPiece.reader.recording`. Nothing is read back from the title or the `[m:ss]` text, which stay for people and
    for her. A body whose lines no longer number its starts (it was edited) serves no `recording`, since a time then
    belongs to no line. A transcript made before this has none and its lines do not play.
  - **A click on a transcript line plays the recording from there, and the line being spoken is marked.** The client's
    cue path is the one mechanism: her `bench_cue` arrives as `BenchCued` and a person's click is `cueBenchPlayer`
    (`app/web/src/session/live.ts`), a seek then a play to the same listeners (`MediaView`'s `driveFile`), tagged by
    whom so the line under the player says only what she did. A person's click is no Command and no network call: a
    cue is no change to the bench, a person's own controls already drive the player directly, and a server round trip
    would add a delay and a log row for a seek. The player reports its place (`model/playhead.ts`, this page only) and
    the transcript marks the line at that second (`model/transcript.ts`, `lineAt`) while it plays and keeps it in view
    inside its own scroll box. Rejected: a person's click as a `Cue` Command, which is hers alone and would put the
    person's seeks in the log. Rejected: parsing the stamps out of the text, which an edit can break.
  - **A piece derived from another is shown inside its source's card** (`app/web/src/rooms/workshop/model/derived.ts`,
    `PairedBody.tsx`): a recording and its transcript are one card on the grid, the recording's body on top and the
    transcript in a panel below it that a person can fold, so the marked line and click-to-seek stay in view together;
    at phone width (the 760px grid breakpoint) the card shows Player / Transcript tabs and keeps the hidden half mounted,
    so a recording plays on under the other tab. This is presentation only: the transcript stays its own reader piece,
    with its own Commands, tools, highlight and undo, and Archive / Remove for it sit in the panel. The one relation is
    `sourceOf(piece)` (piece to source piece id, or null), a table of providers (`RELATIONS`), each reading a structured
    field and naming its panel; today the only provider is a transcript's `reader.recording`, and a second source of
    derivation (page text, a file made from another) is a new row there, never a title or text match. A derived piece is
    grouped only when its source is on the bench and is not itself derived; otherwise it keeps its own card. The merged
    card has the source's slot, size and order, so a drag, a resize and the card's tools act on the source; the derived
    piece's own order is untouched (a drop is mapped to the whole order by `fullIndex`). Her mark and highlight on a
    derived piece show on the merged card, and a new highlight opens a folded panel. The marked line follows a recording
    the page itself plays (a clip or audio piece); a YouTube embed reports no playhead (that is its player API, not built),
    so its transcript lines seek and play it but no line is marked. Rejected: a Transcript tab as the only view, which
    hides the line being spoken from the player. Rejected: a `transcript` field on the recording piece, which makes the
    server store one fact twice. Rejected: grouping by title or by the `[m:ss]` text.
  - **`bench_frames` is one picture, a sheet** of up to `max_frames` frames at the moments she names, left to right
    then down, kept and counted exactly like a look (one row per call), so it needs no new table and the page shows what
    she saw under her answer.
  - **Both run in a media pod, not the app pod**: `ashley.runs.media.Media`, a second use of the sandbox namespace's pod
    machinery beside Code runs and Looks. The code sandbox cannot do it: it is text in and text out, with no network and
    no ffmpeg. The pod resolves names, reaches the app (to fetch the file by a `files` link of `link_ttl_s`, checked
    against the size and sha256 the piece names) and the speech service, and prints one marked line. No bytes pass through
    the app pod and no state is on a node.
  - **Limits are data** (`ashley/runs/media.json`): frames per call, cell width, JPEG qualities, the longest sound
    taken (`max_audio_s`), the window, the silence threshold, each task's pod deadline. Logs: `media.frames` and
    `media.transcribed` with the household, counts, bytes and durations, and `media.pod`; never a link, a picture or a word.
  - Rejected: whisper inside the app pod, which puts ffmpeg and minutes of CPU in the process that serves people.
    Rejected: one row per frame in `bench_looks`, which wants a migration and a changed key for a picture the model
    sees once. Rejected: a `transcript` kind, which would be the reader again. Rejected for now: streaming beyond
    `max_bytes` (open-work, item 11); a range is served from the bytes read whole, so a 25 MiB video is the ceiling.
- **A repo reaches a bench as a snapshot** (a zip, or one file) from the person's own code host connection ("A
  household connects its own services"). Anything beyond a snapshot is item 21's Codebases VM.
- **3D is her work, seen by the person**: she models in code (kind `model`, format `code`, language `build123d`), the
  piece shows its latest run in 3D, STL, 3MF and GLB leave through downloads, and she photographs the view with
  `bench_look` so the person can point out issues. Rejected for now: a
  cooperative editor where the person edits the same model; no embeddable open-source one exists (open-work, item 11).
  - **A model run's meshes come back in the run's line and are kept as objects.** A profile whose `artifact_bytes` is
    above 0 (build123d: 16 MiB, in a log of 8 MiB) lets the runner carry the files ending `.glb`, `.stl` or `.3mf`
    as base64 of deflated bytes, in name order while their sizes fit the budget and the line fits the log; the rest are
    named in `skipped`. The envelope inflates each against what is left of the budget, so a forged line cannot expand
    past it. `ashley.runs.artifacts.keep`, called by `run_once` for a bench run only, judges each by its bytes against
    the type its suffix says (GLB by its `glTF` header and version, binary STL by `84 + 50 × triangles = size`, 3MF as
    a zip holding `3D/3dmodel.model`; the checks are data in `files.json`) and stores it as a file piece's bytes are,
    under `bench/<household>/<sha256>`. The run records `{name, sha256, size, media_type}` for each in
    `code_runs.artifacts`. One that is not what its suffix says, or that the store cannot take, is named in `skipped`,
    and the first store failure ends the keeping. The sweep's references include the artifacts of the runs that
    remain, so pruning a run lets its meshes go; repair mirrors them as it does any file. A chat run keeps none.
    Rejected: the pod uploading its outputs to the app, which would give her script a network route. Rejected:
    keeping the bytes in Postgres.
  - **An existing model is a file piece a model run starts from** (`ashley.workshop.model_inputs`). A person uploads an
    STL, 3MF or STEP as a file piece; a `build123d` run is handed the ones its `bench_run` names in `inputs` (a list
    of piece ids; the person's Run button names none, so it takes every such piece that is not shelved), in layout
    order while the bytes fit the profile's `input_bytes` (768 KiB), as the job's binary `inputs`: deflated
    and cut in environment strings of at most 100,000 characters (`ASHLEY_BLOBNAME_<n>`, `ASHLEY_BLOB_<n>_<k>`), written
    read-only by the runner as `inputs/<piece id>.<ext>` and never carried back as output. The bytes are not recorded
    with the run: its files hold `inputs.json`, the index (piece id, name, path, size, sha256, and `left_out` with why:
    `too_large` or `unavailable`), without the last run's. A script names a piece by id, `ashley_cad.existing(7)`; the
    reply names the ones the run was not given. `inputs` omitted keeps every model file a candidate, which breaks
    no script she has, and `[]` is none; a named piece that is not a model file on the bench, does not fit with the
    ones named, or cannot be read refuses the run before it is logged (`bad_inputs`, naming the piece), (with the bytes against the cap), where an
    unnamed one is left out. Naming files that together exceed the cap still refuses. The ceiling is therefore on what a script uses, not on what the bench holds (two
    versions of one design no longer shut each other out). Her script text is never read for `existing(...)`. The ceiling is the pod object: Kubernetes takes about 1.5 MiB for it,
    and the environment is where the job already rides. Rejected: mounting from the object store, which needs the pod to
    reach the store or an init container to hold its credentials. Rejected: a field on the model piece naming its
    inputs, a second place beside the pieces for the same fact. Rejected: finding `existing(...)` calls in the script
    text, which is regex over what she wrote.
  - **`existing` makes a mesh into a solid that can be changed.** build123d's `import_stl` gives one face with no volume,
    which nothing can be joined to. An STL (binary, told by its size matching its triangle count, so a binary file whose
    header begins `solid` is read right, or ASCII) is written as a 3MF with shared vertices joined, and `Mesher` reads
    that as a solid of its triangles; a 3MF reads the same way, converted from the unit it declares; a STEP is imported
    as it is. An STL's unit is not in the file, so `existing(piece, unit=)` says it (default `mm`). A mesh that does not
    close, or whose faces point inward, is refused. `joined` and `cut_away` do the boolean and fail when the result
    lost or invented volume, because a boolean on a real mesh (the ADIS16480 IMU model) returned only the added box.
    Rejected: trusting `+` and `-` on a mesh. Rejected: a mesh boolean library, which the image would have to carry
    for a repair that the person's STEP export avoids.
  - **The page shows the view, the downloads and the checks.** A model piece's card is the latest run's `model.glb`
    drawn with three.js (pinned in `app/web`, imported only by `ModelCanvas`, so it is a chunk no other page loads),
    turned and scaled from glTF's metres and Y-up to build123d's millimetres and Z-up so the frame is the script's, fitted
    to the bounds, and orbitable; the extent in millimetres is written under it. Under that: STL, 3MF and GLB links
    from the run's artifacts, saved under the piece title as a slug; every check with its verdict (a fail outlined,
    an unconfirmed one hatched as a guessed measurement is) and what it rests on; the source folded. A piece never
    run, or whose run kept no model, says which in the picture's place. A browser that cannot draw WebGL, or a file
    that will not load, says so there and keeps the downloads and the checks. The Run button of a model kind offers
    `build123d` alone.
  - **`bench_look` on a model piece is a sheet of four views** (isometric, front, top, right, orthographic) drawn once
    by the same component on one canvas, which the look page's `ready` waits for: it is set after every model on the
    page has drawn its frame, or failed. Headless Chromium draws WebGL with SwiftShader, with no GPU and no new launch
    flag. Rejected: a continuous render loop, which a still photograph and an idle page do not need.
- **Measurements are structured data, each with its source** (kind `measurements`, format `measurements`,
  `ashley.workshop.measurements`). The body is JSON: `{"items": [{"name", "value", "unit", "source", "tolerance",
  "ref", "asked"}]}`. `name` is an identifier unique within the piece. `value` is finite. `unit` is `mm`, `deg`,
  `count`, `g`, `ml` or `min`, with lengths always in millimetres, masses in grams, volumes in millilitres and durations
  in minutes (she converts what she is told). `source` is `measured` (the person measured, counted or stated it, or a
  file embodies it), `datasheet`, `accepted` (she asked and the person said to go with the value), `bound` (something
  soft or varying whose true size is the range `value` ± `tolerance`, so a bound row carries a tolerance above 0 and the
  part is built to work over the whole range) or `guessed`; every source but `guessed` is confirmed. `tolerance` is an
  optional ± of 0 or more in the unit. `ref` is optional text up to 200 characters (the datasheet's address, what was
  measured with, the photo piece a form was seen in). `asked`, on a guessed row only, is true once the person has been
  asked for it: each bench turn is a fresh call and a later conversation on the bench does not carry the earlier one's
  question, so the row carries it, and she asks for a row marked asked no more. `given` optionally names a choice row
  of the same piece the number belongs to (a strap's width is given the strap's form). Anything else is refused
  `bad_measurements`. The room shows a table with each value's source, a guess hatched and marked when asked, a choice
  by its label. Either side edits it like any piece, so a correction is logged and undoable. An edit of hers that changes
  what a confirmed row holds (a number's value, unit or tolerance; a choice's value) while keeping where it came from (a
  number's source and ref; a choice's source, turn and piece) is refused `confirmed_measurement`: a confirmed row
  changes only with a new answer from the person or a new source, and the row says which. The piece goes on any bench:
  the numbers a plan rests on (headcount, amounts, times) are rows too, under the bench guidance every bench gets.
  Rejected: a table of its own, since measurements belong to the project and a piece already gives edit, undo, Live
  and the log. Rejected for now: measurements as memory facts shared across benches, until a second bench wants the
  same object's numbers. Rejected: a source of its own for a size read off a photo; a photo settles what kind of thing an
  object is and its cross-section (a choice row, `seen`), while a size read off it stays guessed until the person gives
  or accepts it.
  - **A choice is a row too** (`"kind": "choice"`; a row with no `kind` is a number, so stored bodies need no
    migration): what kind of thing something is, in plain words (a flat strap or a round cord, gas or electric). It has
    `name`, `label` (up to 60 characters, for the person, since `name` is an identifier), `value` (up to 80), optional
    `options` (2 to 6, `value` one of them), `source` (`stated`, `seen`, `datasheet`, `accepted` or `guessed`; `bound`
    and `measured` are number-only), `turn` only with `stated` or `accepted`, `piece` only with `seen` or `datasheet`,
    and `ref`. A citation is checked where its context is: a choice row she adds or changes as `seen` or `datasheet`
    names a piece on the bench, layout or shelf, of an image, file, reader, site or recipe kind (`decide`), and one as
    `stated` or `accepted` a person's turn on the talk her tools serve (`ashley.tools.bench_citations`, since the talk
    is not the Workshop's); either is refused `bad_citation`. A person's edit needs no citation, since the log says
    who wrote it, and a row kept as it was is not judged again. `measurements.confirmed` is the one test of a confirmed
    row, read by a check's verdict, the guard on her edits and the carry into later turns. Rejected: a form told by
    which rows exist, which is shape-sniffing (one bench's rows flip-flopped and "superseded" lived in a `ref`);
    free-text values code branches on (code keys on `source`, the citation and `rests_on`; a script compares
    `chosen()` only to the row's own `options`). Rejected for now: `piece` on numbers, so that a number of hers whose
    `ref` cites a photo could be refused as `measured`.
- **A diagram is Mermaid source in a stored piece** (kind `diagram`, format `diagram`, up to 20000 characters). The
  server keeps the text as written and checks nothing about it; the client draws it (`DiagramView.tsx`) with Mermaid,
  imported on first use, so a bench with no diagram never loads it, and bundled, because the look pod's browser has no
  internet. Mermaid runs at `securityLevel: 'strict'` with HTML labels off, so a label is text and a click callback
  is dropped. Its colours are read from the house tokens at draw time. A body Mermaid cannot read shows Mermaid's
  message and the source beneath it. The drawing registers with `tracked`, so `bench_look` photographs it drawn.
  Rejected: a diagram kind per chart type, since Mermaid already names its type on the first line, and a drawing
  library of our own.
- **A model is checked against them by the numbers, and the app does the comparing.** A run in `build123d` starts with
  the bench's measurements pieces that are not shelved, merged in layout order as `measurements.json` (a name a later
  piece repeats keeps its first value; none when the bench has none), recorded with the run's files as any input is, and
  without the last run's `measurements.json`, `inputs.json` and `out/report.json`, so a report read back is this run's.
  `ashley.workshop.model_report.report_of` parses `out/report.json` of a run that `ran` with exit 0 into a
  `ModelReport` (parts with bounding box and volume, triangles, checks) and judges each check from its numbers:
  `==` within ±`tolerance`; `<=` and `<` against target + tolerance; `>=` and `>` against target - tolerance. A check
  that holds is `pass`, or `unconfirmed` when a measurement it rests on is `guessed` or is not in the run's
  measurements; one that does not hold is `fail` whatever it rests on. A report not of the shape the helper writes is
  none, never a partial one. `BenchPiece.last_run.run_output` and `RunApplied` carry `artifacts` (with download links
  of the files' kind, ending at the half-`link_ttl_s` window) and `report`; her `bench_run` and `bench_last_run` carry
  the artifacts by name, type and size (no link: her tools hold no link key and a link lasts minutes) and the report.
  Rejected: judging a fit from the picture, which is for the person to point at; trusting a pass flag the script
  printed. Rejected: marking a failing check unconfirmed, which would hide a measured disagreement behind a guess.
  - **A stand-in names its form, and a fit against it rests on that form.** A `reference` part is shown as
    `(name, shape, "reference", form)`, `form` a choice row of the run's measurements; one without it, or naming a row
    that is not a choice, fails the run before anything is written, with a message naming the fix, and the report's
    part carries `form`. `chosen(name)` reads a choice and records the read as `measured` does, and `measured` of a
    number with `given` records that choice too, so a check that leaves out `rests_on` rests on the form. Every pair of
    compared parts with a reference part gets a `parts_apart` check (the volume they share against none), overlapping
    or not, resting on the forms its reference parts name; so on a guessed form the stand-in's fit is `unconfirmed`,
    never a plain pass (one bench read "18/18 checks pass" against a round stand-in for a flat strap). Pairs without a
    reference part still get one only when they overlap. Rejected: making only a formless stand-in's checks
    unconfirmed, a softer signal of the kind she had already read past; a failed run cannot be missed and costs one
    re-run.
- **Her 3D method is the `3d` skill, and whether a model fits the real object is the bench turn's own judgement.** The
  seed `app/ashley/skills/seeds/3d.md` is the method: measurements first, each with its source, the model built from
  them with `ashley_cad`, a `check` for every fit, the report read before anything is said, `bench_look` after, and an
  `unconfirmed` check reported as resting on a guess. It loads as every skill does, for a bench whose kind of work is
  `3d`; the bench guidance (`bench_specs.INSTRUCTIONS`) names the `model` and `measurements` kinds and tells her to set
  that kind. The judgement runs on the model running that bench's turn (`brainstorm`, as the talk is), from the report
  and the sources together; the app has computed each check's verdict from the numbers before she reads it. Rejected: a
  separate "strongest route" call for the fit (it would re-read what the turn already holds, and the verdicts are
  already code); `Reply.escalate` for it (a bench turn does not escalate, "A turn escalates once"); a ledger task for
  fit judgement.
- **A long paste is an attachment captured at paste time**, a structural field of the message and never found by
  reading its text: the composer takes a paste longer than `PASTE_MIN` (`rooms/her/limit.ts`) as a chip
  beside the message, which stays what was typed, and the chip goes with it on send.
  - **On a bench** the person's own Add command puts it up as a `document` piece titled by its first line, so it is
    undoable and shows live, and the message names it by `BenchMessage.piece_id`, checked to be a piece of that bench
    (else 422 `refused`). She is told of it in the turn's `note` (never stored), and reads it with `bench_read_piece`.
    A bench message takes no `attachment`. A refused Add (`full`, `too_long`) sends nothing and the composer keeps the
    chip and says why.
  - **In chat** the `ChatMessage.attachment` (`title`, `text` of at most `ATTACHMENT_MAX_CHARS`) is stored on
    the person's turn (`turns.attachment_title` and `turns.attachment`, null together on every other turn, a person's
    turn only), read back as `ChatTurn.attachment` for the page to fold under the message, and carried to her whole,
    marked and ended, wherever the turn is carried (`channels.prompt`). Memory, which reads `turn.text`, learns only
    what was typed. The kiosk and a bench take none. Logs `respond.attached` with ids and the length, never the text or
    title. Rejected: a table of its own, since a turn has at most one and every read of a turn wants it; the paste
    appended to `text`, which the page could only split by reading it.

## She moves the person's page herself

Where the channel is a page of the speaker's own (their web chat, a bench's talk: `Inbound.on_page`), she can take it
to another room, as going to the workbench and back to chat, rather than asking the person to go.

- **A tool, offered only there** (`ashley.tools.move_page.MovePageTools`, through `channels.turn_tools.for_turn`):
  `move_page` with `to` one of `chat`, `workshop`, `bench`, `memory`, `devices`, and `bench_id` for a bench, which must
  be one of the speaker's open benches, else a tool error and nothing moves.
- **A Live event of ids only**, `PageMoved` (the room, and the bench when there is one), shown to that person's own
  screens alone: never another person's, never a device's. Every open tab of theirs hears it and decides for itself.
- **Never move the page under the person.** A page follows at once with the shell's own flight (a fade under reduced
  motion), unless the person is in the middle of something: a text field they are in holds text, something is being
  carried, or a piece of the bench shown has an edit open (`app/web/src/shell/her/follow.ts`). Then her mark waits on
  the destination's bearing with an offer to follow or stay; going anywhere themselves ends the offer.
- **Her links to the rooms' own paths open in place** (a room, or `/workshop/<id>`), with the same flight; every other
  same-site path is still only its label.
- **Logs:** each move is one `tools.call` line with the room and bench id. Whether a screen followed or waited is the
  screen's own business and is not logged.
- **Rejected: moving without the waiting rule.** It yanks the page away mid-sentence or mid-drag.
- **Rejected: a link in her text as the only way.** It needs the person's tap, and she cannot follow up on it in the
  same turn.
- **Main chat knows the open benches** (`Catalogue.now` of move_page): a message about one of them moves the page
  there, and the work goes on in the same turn. Telling the person to go there is the defect.

## Her reply follows the page

A turn that takes the speaker's page to a bench is that bench's turn from the next model step on, and her reply is said
there. Without that her reply duplicated the chat and the note, and a person moved to an empty bench while her answer
sat in chat.

- **The rest of the turn is the bench's.** `Inbound.moved_to` is the bench the turn has moved the page to
  (`ashley.tools.arrival.Arrival`, told by `open_bench` and `move_page` as they succeed). `ashley.channels.landing.Landing`
  is the turn's tool source: after a round that moved the page it rebuilds `turn_tools.for_turn` for the bench (its tools,
  its automation tools, `bench_run`; the same owner and open-bench checks as `move_page`), appends the bench's guidance to
  the system prompt's `moment` (the cached `stable` part is untouched), and switches the turn to the `brainstorm` limits.
  `moved_to` is saved with the checkpoint the moment the call that moved the page returns, before its result is, so a
  pod that resumes the turn at any point is already there; it guides the saved system prompt again before its first step.
- **Where the reply goes.** With `Inbound.lands_on` set (the page is on a bench other than the thread's own), the bench's
  talk (`bench:<id>`, a `brainstorm` conversation) is given the person's ask as its first person turn, linked to the chat
  turn by `turns.carried_from` (unique, so a turn finished twice carries it once), then her reply answering it. The
  chat thread keeps the ask and gets, instead of her reply, a turn of hers with `turns.continued_on` = the bench id; its
  text (the bench's title; the page words the link as a quiet line, never as her words) labels the link the client draws (`ChatTurn.continued_on` on the wire, a link to
  `/workshop/<id>` that opens in place). Both talks are announced to the person's screens. If the bench cannot be read or
  the talk refuses the turn, the reply stays in chat (`respond.continue_failed`).
- **The bench shows her working from the moment the page lands.** The ask is carried into the bench's talk before the
  first step after the move (`continued.carried`, from `_Turn.arrive`), so the open bench reads the person's line owed an
  answer and her thinking dots under it, instead of an empty talk. A held line she says after the move is said in the
  bench's talk, answering the carried ask (`continued.held_on_bench`; `Work.say` renews the claim for a conversation
  other than the claim's); one said before the move stays in the thread the turn began on. Before a step she is
  announced as thinking again once half of `thinking_at_most_s` has passed (`Showing.still_working`), so a longer turn is not
  shown idle while it works.
- **A cue drives a video piece's player and is no change to the bench** (`ashley.workshop.commands.Cue`, tool
  `bench_cue`). It is a Command so `decide` judges it like the rest: refused `not_video` on a piece whose kind's format is
  not `video`, `clip` or `audio`, `bad_cue` for a seek without `seconds` or outside 0 to `embed.MAX_START`, or a play or pause with
  `seconds`; accepted, it logs a `Cued` effect that changes no piece, not its version or `changed_by`, so a piece's last
  change and a bench's never move on a cue. It is never undone (`nothing_to_undo`) and the undo walk passes over it, as it
  does a Run: it stored nothing to put back. It is hers alone (the person's own controls drive the player directly and emit
  nothing), and not a person's change, so nothing that reads the person's commands to react to them sees one. It reaches
  the owner's open screens as `BenchCued` on Live, not `BenchChanged`, so no screen reads the bench back for it; Live
  keeps nothing for a screen that opens later, so an old cue is never replayed. The client drives a YouTube player by
  `postMessage` (its embed asks for `enablejsapi=1`), Vimeo's the same with its own messages, and a direct file's
  `<video>` directly; an embed that has not loaded drops the cue, and a browser that refuses `play()` before any touch
  leaves the video paused. Rejected: an undoable cue, which would put "undo" on something that changed nothing and make
  the walk name it; a stored playhead position on the piece, which a cue-and-seek would write on every command and a person's own scrubbing
  would contradict; reusing `BenchChanged` with a flag, which makes every screen read the bench back for a moment and
  makes "the person's change" depend on a flag each reader must remember.
- **A site or video piece is put up by a search result's number, or by a URL someone else supplied.** Her search shows
  no URLs, so a URL she typed for a reference was one she composed from memory, and on a live bench she wrote
  Wikipedia links "from how those sites usually set up their pages". `bench_add` and `bench_edit` of a site or video
  piece take `result` (and, for a video, `start`) in place of a body, and the server writes the URL from the turn's
  `Results` (`ashley.tools.bench_reference`); the kind checks then run on that body as on any. An unknown number is
  refused `unknown_result`. A URL she gives as a body is accepted only if it appears, by exact string, in a person's turn
  of the conversation or in a site or video piece already on the bench (shelf included), else `unlisted_url`, which
  names the result path; a document's text is not checked and is not a source, or a link she wrote there would vouch for
  the next. `bench_replace` is refused on these kinds (their body is one URL, and a replace would skip the check); a change is a `bench_edit`. The numbers live in the turn's `Landing`, so a runner that resumes a turn has none, and her number is
  refused `unknown_result` until she looks it up again. Rejected: guidance alone (a prompt rule against writing URLs she
  was not given was already there and she wrote them); accepting any URL and checking it fetches (a composed URL that
  resolves is still not one she was given, and the fetch is the request forgery `read_page` avoids); matching URLs in
  her prose with a regex (the bench's body is the field the check reads).
- **A code or document piece can be a page's text, put up by the same result number.** look_up hands her at most
  `answer_chars` of a page, so a 370-line script behind a link could not be put on the bench to read line by line.
  `bench_add` and `bench_edit` of a `code` or `document` piece take `result` in place of a body exactly as a reader
  piece does (the page must have been read this turn, `unread_page` otherwise), and the server writes the body:
  `Source: <url>`, then the page's text as `read_page` kept it, line ends made `\n`; a document has a blank line after
  the first line. The address sits in the body because these kinds have no field for it, so the piece's line N is the
  page's line N-1. A page longer than the kind's `max_chars` is refused `page_too_long`, and one longer than
  `page_bytes`, whose text ends early, `page_cut`; neither is stored cut. `read_page` reads a Pastebin paste
  (`pastebin.com/<id>`) and a GitHub file view (`github.com/<owner>/<repo>/blob/<ref>/<path>`) at their plain-text
  address (`ashley.tools.raw_source`, judged on the parsed URL's host and path), since their pages stripped to text
  lose the code's indentation and blank lines and carry the site's chrome (measured on a 371-line paste: 329 lines,
  none indented); the fetch is still `page_fetch`'s, public https only. No other host is mapped. Rejected: a new tool
  beside the reader mode, which is the same act on the same turn store; a reader piece for code, which shows text as
  paragraphs; a rule for every paste site and for gists (a gist's address names one file of possibly several, so a
  mapping would pick for her); mapping by regex over the page's text.
- **A reader piece is a page's text as she read it, and a point highlights a passage of it** (kind `reader`, format
  `reader`, family `stored`; `ashley.workshop.reader`). Its body is one JSON object of exactly `url` (https), `title`
  (the page's own, which may be empty) and `text`, lines separated by `\n`; `decide` refuses any other non-empty body
  `bad_reader`. It is `stored` because the text is the content: the piece keeps what she read when the page changes or
  goes. The server serves it as `BenchPiece.reader` (url, title, paragraphs) so the client derives nothing, and shows
  readable text with the original linked in a new tab (`rel="noopener noreferrer"`); the page offers a person neither
  adding nor editing one, since its text is the page as read.
  - **She makes one only from a page read this turn, by its result number.** `read_page`, and `bench_read_piece` on a
    site or video piece (`bench_page`, under a number of its own), keep the page's title and
    whole extracted text in the turn's `Results` (`results.Results.keep`), while its answer to the model stays cut to
    `page_chars`, and `bench_add` or `bench_edit` of a reader piece take
    `result` in place of a body, the server writing the body from that page (`bench_reference`). A result whose page
    was not read is refused `unread_page`, a body she typed `bad_arguments`, and `bench_replace` is refused. The piece holds the whole text up to its kind's `max_chars` (`kinds.json`), cut at the end past that, so a long page
    is read with her through `bench_read_piece` windows, not a fixed cap she cannot get past. The reading
    is look_up's, so she asks look_up for the page and to read it in one question. `read_page` still takes only a result
    number. Rejected: a new `bench_read_page` tool, which would be a second page reader beside the one that holds the
    request-forgery boundary; her pasting the text as a body, which would let a reader piece carry text and an address
    that never met.
  - **A location is a passage in the piece's own terms**: a paragraph (one line of `text`) and a range of characters in
    it, counted in code points (`reader.Passage`). Lines are stored, so a passage means the same words however a screen
    wraps the page. She names the words, not the numbers: `bench_point` takes an exact `quote` that must occur once in
    the text inside one paragraph, and the server resolves it (`reader.locate`), so a miscount can never highlight the
    wrong words. Rejected: offsets she counts, for the reason `bench_replace` rejects a line or offset range; an offset
    into the whole text, which the client would have to map to lines.
  - **A point is a recorded Command, not a Live event like a cue** (`commands.Point`, effect `Pointed`). A cue is a
    moment (play now) that is meaningless to a screen opened later; a highlight is a place the person must still see
    after a reload or on their phone, and Live keeps nothing for a screen that opens later. So it is logged and
    announced as an ordinary `BenchChanged`, and a read serves the latest accepted one of each piece
    (`BenchView.pointers`, from the log, never stored twice) as `BenchPiece.pointer` while the piece is still at the
    version it was made against (`Point.base_version`, refused `stale_base` otherwise), so a highlight never sits on
    words that moved. It changes no piece (not its text, version, place or `changed_by`), so the bench's last change does
    not move; it is never undone (`nothing_to_undo`) and the undo walk passes over it, as it does a cue. `Point` with no
    passage takes the highlight away: hers with an empty quote, the person's with `clear_point` from the page's
    "Clear highlight" (their Point, so it counts for no reaction of hers). Refusals: `no_such_piece`, `unknown_kind`, `not_reader`, `stale_base`,
    `bad_passage`. One passage per piece. Rejected: a Live-only event like a cue, which a reload loses; storing the
    highlight in the piece's body, which would make each point an Edit of the whole page's text, bump its version and
    be undone by Undo; an undoable Point; several highlights per piece, which nothing asks for yet.
  - **The client brings the highlight into view once for each new one**: inside the text's own scroll box, smoothly
    unless motion is reduced, and again when the piece first shows after a reload. Her mark lands on the piece
    ("pointed at this") and, scrolled out of view, the line at the foot of the pieces takes the person there, as for
    any change of hers. Other kinds (a line range of code, a region) will need a location of their own beside
    `Passage`; none is built.
- **A recipe the work uses is a recipe piece: the page's own recipe data, scaled to the bench's headcount in code**
  (kind `recipe`, format `recipe`, family `stored`, outside; `ashley.workshop.recipe`). A recipe page publishes its
  recipe as schema.org JSON-LD (name, yield, ingredient lines, steps, ISO 8601 times), a structured field, so nothing
  reads the page's prose for it: `page_fetch.page_of` keeps it on the page (`ashley.tools.recipe_ld`) before the
  scripts are stripped, `read_page` keeps it in the turn's `Results` and gives it to the look-up first, and `bench_add`
  of a recipe piece takes `result` and `serves` in place of a body, the server writing the body from that page as for
  a reader piece (`ashley.tools.bench_recipe_ref`); a page with none is refused `no_recipe`, and an edit changes
  `serves` alone or puts up another read page. The body is the page's lines as written plus `serves`; the amounts are
  derived on read: `ashley.workshop.quantity` reads the amount a line starts with (whole, decimal, fraction, mixed,
  vulgar, a number word, or a range of two, then a unit from `recipe.json` by whole-word alias, then a bracketed
  metric equivalent, which scales with it) and writes it back multiplied by `serves` over the yield's first number.
  A line with no amount, or whose number is a size joined by a hyphen (`15-ounce can`), is shown as written and marked;
  steps keep the page's numbers and say for how many. Her read of the piece (`bench_view`) and `BenchPiece.recipe`
  carry the same code-rendered numbers, drawn by `RecipeView.tsx`. A site piece already on the bench needs no second
  search: its read keeps the page as `read_page` does and gives the number. Every source on the bench is read when the
  turn's work reaches what it is for, and its amounts, steps and times carried into the plan, each number a measurements row with its source
  (`datasheet`, ref naming the piece), under the bench guidance. Rejected: the model scaling amounts or parsing
  ingredients; recipe data on the site frame record, which is per address and cannot hold a headcount; a field on the
  reader piece, whose body is text for pointing at; a person-side add, since a recipe is a page she read.
- **What is still open on a bench reaches every later turn.** The moment layer (`ashley.tools.bench_now.open_rows`)
  lists each guessed row of the bench's household-written measurements pieces, asked or not, however far into its
  piece, so a fresh bench turn starts from what is still to settle. A row marked asked is not asked again while the
  work goes on around it; when the step at hand depends on it, she says once that it is open and what she assumed, and
  goes on with the guess shown unconfirmed. A guessed choice row is listed too, by its label and value. Rejected: a new
  store of open questions, while unconfirmed rows and `asked` carry them.
- **Code on a bench is a piece.** A bench turn (the thread's own bench, or one the page moved to) is offered `bench_run`,
  which runs a code piece and records the run on the bench and the piece, and not the loose `run_code`, whose runs show
  nowhere on a bench. Rejected: offering both; she used the general one four times in a row and the bench stayed empty.
- **A fresh bench is led with the world's references too.** Beyond what the household already has, on a topic the world
  already knows she asks `look_up` for the best one or two references and puts them on the bench as site or video pieces by
  result number beside her draft, or none when no result is the thing itself (`bench_lead.LEAD`).
- **A message on a bench steers the running turn.** A bench talk runs one turn at a time (`Inbound.steers`, set by the
  bench's message route). A message is stored at once as any is; if another turn of that talk has work in flight
  (`InFlight.working`, the lock, so across pods), it starts no turn: its request answers pending and the running turn is
  handed it before its next model step, and before it would return its answer, as `<name> just said: <text>`
  (`channels.steering`, through `Steps.steer`). The turn's checkpoint records the handed turn ids with the entries they
  join (`Progress.steered`), so a runner that resumes it gets a message not yet handed once and one already handed not
  again. One final reply is stored, answering the first message. A message after the turn's work is gone starts its own
  turn. Every message is answered exactly once: her final answer carries the ids it was handed (`NewTurn.handed`) and
  is stored only while no other person turn follows the one it answers, checked under the conversation's row lock,
  which a person turn's store takes too; a message stored after the last hand refuses the answer (`Unhanded`) and the
  turn is handed it after her draft and goes on (`channels.answering`), and one stored after her answer sees no work
  and starts its own turn. A turn whose work is dropped with no answer (the model refused, a store failed) leaves its
  messages to a turn of their own: in the transaction that drops it, under the same lock, the oldest message after it
  gets work whose checkpoint says nothing is built yet (`Checkpoint.left`), claimable at once, so any pod's sweep
  answers it from the start and the rest are handed to that turn. A turn that began in chat and landed on a bench is
  that bench's running turn once its ask is carried there (`Checkpoint.carried`): `InFlight.working` counts the carried
  ask while the turn's work is unanswered in the talk, and the turn is handed the talk's messages after it. (A live
  bench got two replies recommending the same film without it.)
  - Rejected: closing the window by handing again just before the store; any check outside the store's transaction
    leaves a smaller window, and two pods make it real.
  - Rejected: parallel turns on a bench (two turns contradicted each other live: one said the code looked sound, the
    other that it had fixed real bugs). Chat keeps parallel turns.
- **Other destinations.** Only a bench has a talk of its own. A move to chat, memory, devices or the workshop list leaves
  her reply in the thread the turn began on; a bench-talk turn that moves to its own bench stays there; moving to a bench
  and then away again ends where the page is.
- **A bench she just opened is led, not asked about.** When the bench was opened in the same turn (`Arrival.fresh`) its
  instructions carry `ashley.tools.bench_lead.lead`: bring what exists onto the bench, draft, decide what can be
  decided and state it in a line, ask at most one or two questions that are genuinely the person's. Every bench talk's
  instructions say the work lives in pieces and that a change to something on the bench is an edit, not a near-copy
  added beside it.
- **A bench opens quiet**: a bench that opens full of pieces is too much at once. The turn that opens a bench adds at most
  `lead_adds` pieces (`bench_tools.json`, 2): `BenchTools` counts the accepted adds of a lead instance and refuses the
  next `ask_first`, a tool error telling her to say what else she would add and ask. Edits, moves and every other
  turn are not capped, and the count is of the turn, so a runner that resumes it starts it again. Rejected: a cap on
  the bench's pieces, which a person may fill as they like.
- **Her reply on a bench is two or three sentences, held in code.** `brainstorm`'s `reply_chars` (`turns.json`, 500)
  is the longest `Reply.text` the tool loop takes: a longer one is kept in the turn as her draft, followed by a note
  of the limit, and the model is stepped again, `tool_loop.RESHORTENED` times at most (`respond.reply_long`, ids and
  lengths), after which the reply goes out as it is; the forced answer after the last tool round is asked again the same way, still under tool choice `none`. A kind without the key has no limit. Guidance says the same
  (`bench_specs.INSTRUCTIONS`, `persona/kinds/brainstorm.md`) but is not what holds it. Rejected: `max_tokens` on the
  step, which also bounds a step that writes a piece and cuts the structured reply mid-JSON, which the provider
  reports as invalid output and fails over to the next route. Measured on the brainstorm route's model with a
  ten-sessions ask: caps of 150, 300 and 600 tokens cut off 3 of 3 replies, 1200 cut off 1 of 3, and the whole ones
  were 880 and 942 characters, so a cap low enough to bind fails the turn and one high enough to pass does not bind.
  Rejected: a hard cut of the text, which ends mid-sentence.
- **A bench talk has room to work.** The `brainstorm` entry of `turns.json` gives 24 tool rounds and a 300 s deadline,
  where Opus steps take 8 to 30 s and 8 rounds in 40 s ended turns before the work was done. After the held line she
  keeps working, each Command shown live as it lands, then a short reply. The turn is checkpointed and resumable as
  any other (`Work in flight survives its pod`), the final reply stored as her turn and announced as a `LiveTurn`. A
  message typed while she works starts its own turn on the thread, as in web chat today.
- **Chat closes on its own clock.** A chat conversation closes 30 minutes after its last turn (`policy.json`), and the
  chat room then reads empty until the next message; time spent on a bench does not keep it open. The continuation is
  in that closed conversation, listed under Earlier.
- **Logs:** `respond.continued` (chat conversation, bench, talk) and `respond.continue_failed` (bench, reason); ids only.
- Rejected: the held line in chat after the page left it. The person is on the bench and sees nothing there.
- Rejected: storing the reply in both places. The person would read it twice, and the bench's talk is where the work is.
- Rejected: leaving the reply in chat and only linking to the bench. The page has already moved; the person arrives at a
  bench with no conversation and the answer is elsewhere.
- Rejected: copying the ask and matching it by text. The link is the `carried_from` field, so nothing reads words.
- Rejected: a faster model for bench talks. The bench route is already the largest model; the limit was the turn budget.

## She runs a script in a gVisor pod of its own

`run_code` runs a short script once, on-prem, and gives her what it printed (open-work item 21, Snippets); a bench's
code piece runs the same way ("The workshop", a Run command). Each run
is its own pod in namespace `ashley-sandbox` on whichever site she is answering from, under RuntimeClass `gvisor`
(gVisor's systrap platform, which needs no nested virtualisation, so virtual-machine nodes run it), and is
recorded in Postgres before and after (`ashley.runs`, "Code runs" in `systems.md`).

- **The pod can reach nothing and holds nothing.** The namespace denies all ingress and egress (no DNS either) and
  enforces Pod Security `restricted`; the pod mounts no token (`automountServiceAccountToken: false`, and the
  namespace's default ServiceAccount has none), uses no host namespace, gets no service links and no resolver, runs
  as nobody with no capabilities on a read-only root, with CPU and memory limits and two size-limited emptyDirs.
  Its image is pinned by digest in `app/ashley/runs/runs.json` (`python:3.13.18-alpine3.24`, the official image,
  standard library only).
- **Seconds, not minutes.** The script is stopped after `script_timeout_s` (10 s) by the runner in the pod, which
  keeps what it printed; `activeDeadlineSeconds` (30 s, starting the pod included) is the hard stop. A pod that never
  starts in that time is `unavailable` and nothing ran. Each pod requests 250m CPU and may use 500m, so the
  namespace's quota (1 CPU requested, 2 CPU limit, 4 pods) admits four runs at once.
- **The job goes in through the pod spec, the output comes out through the log.** The script, input and files are
  environment variables, one per value (Linux caps one at 128 KiB); the runner prints one marked JSON line, which
  is re-checked and cut to the limits, since the script can print that line too. The app needs only to create, read,
  log and delete pods in that one namespace. Rejected: a ConfigMap or Secret per run, another object to grant and
  clean up. Rejected: `exec` or attach to stream output, a wider grant and a connection held for the run.
- **A language is a profile of the one Sandbox.** Every language, Python included, is a `Profile` under `runs.json`'s
  `languages` with its own timeout, deadline, CPU, memory, working-directory size, log size, `artifact_bytes` (the
  binary output it carries back) and `input_bytes` (the binary input it is given; Python carries none of either), read the same way by every caller (`RunsConfig.profile`); only
  Python's carries its `image` in the file, since another language's is given at start. The top level keeps what a
  run shares whatever its language: namespace, RuntimeClass, the chars limits and file count (one reply shape) and
  the poll. Rejected: python as the top-level fields beside a `languages` map, two shapes for one idea.
  `build123d` is 60 s (`activeDeadlineSeconds` 120, counting a cold image pull), 1 CPU, 1 Gi, in the CAD image
  (`deploy/cad/`) the app is given as `CAD_IMAGE`, pinned by digest. The pod is otherwise the code run's: no network, no
  token, read-only root, gVisor, deleted however it ends. A profile without an image is not offered, so with `CAD_IMAGE`
  unset the Sandbox runs Python only and a `build123d` Run is refused as a language it does not run; it never falls back
  to the Python image. Loose `run_code` stays Python (`tools.run_code.LOOSE`); `code_runs.language` allows both.
  Rejected: a pod kind of its own, as media has, since the job is a script with no network.
- **The pod is always deleted**, however the run ends; one left by an app pod that stopped mid-run is deleted by a
  later run once older than twice the longest deadline of any language.
- **A run is a change.** Its tool reads nothing (`ToolSpec.reads` false), so the turn's checkpoint marks it started
  before it runs, and a resumed turn never runs it again; she is told it may or may not have run. Its record is
  written first, and nothing runs unless that write succeeded. One runner, `ashley.runs.once.run_once`, does that for
  every caller.
- **A run is asked for by a turn, a bench command, or both** (`code_runs` holds the conversation, turn and call, and
  the bench, command `seq`, piece and version): her `run_code` has a turn, a person's press of Run on a bench has
  only the bench, her `bench_run` has both.
- **Later turns carry a run in a compact form.** A turn stores only its text, so a run's script and output would
  be gone by the next message; her carried answer is followed by a block of each run its question asked for (language,
  how it ended, the script, stdout and stderr, the names of the files it made, never their contents), between
  `[code run: ...]` and `[end code run]` markers so it is not read as her words. The runs sit under the same answer the
  page shows them under (`ashley.conversations.answers.answer_of`), read with one `Runs.of_turns` per reply for the
  person turns carried, so only turns the hearer may hear bring any; a bench command's runs are its piece's and never
  come. The budgets (`carried_runs`, `run_script_chars`, `run_output_chars`) are per kind in `turns.json`, the script
  cut from its end and each stream from its start, since the end of a stream is where the error is. Unreadable runs
  are logged (`respond.runs_unavailable`) and the reply goes on without them. Rejected: replaying the tool
  call and its result, which a turn does not store. Rejected: stdin and file contents, which cost more than they
  help; she can run it again.
- **The app reaches the API with a token it reads from a file on every call**, a projected ServiceAccount token
  (`SANDBOX_TOKEN_FILE`, with `SANDBOX_CA_FILE`), since the app pod mounts no token by default. Unset, the Sandbox is
  its Null Object, which runs no language, and `run_code` is not offered.
- Rejected: each provider's own code tool. They differ (Anthropic keeps a container 30 days, OpenAI's dies after 20
  idle minutes, Gemini's runs only Python for 30 s), and a fallback mid-turn lands in another sandbox without the
  earlier files.
- Rejected: hosted sandboxes (E2B, a Firecracker microVM per sandbox, was the best of them), since the household's
  data would leave the house; and Kata, which needs nested virtualisation.

## For code and the cluster she is a front for Claude Code

"Help me out here" reaches the talking person's own Claude Code sessions through a small bridge that the person runs
where their herdr runs (`bridge/herdr/`). The bridge is a narrowing Proxy over herdr: list, read, prompt, start and
close, nothing else. A session she handed work to going `blocked` or finishing is a wake for that person alone.

- **A bridge is a personal Connection** (kind `herdr`, as `gitlab` and `github`): an `https` address, the certificate
  fingerprint and a token the bridge printed once at install, sealed bound to the person. The fingerprint is part of
  the address, `https://host:7843#sha256=<64 hex digits>`, since a row holds an address and one secret and the
  fingerprint is public; an address without it is refused. It is stored only after the bridge answers
  `GET /v1/whoami` with it, called as the connecting person (the bridge's person lock needs the id, so a kind's check
  takes the person's id). She reaches only the speaking person's bridge; an unknown speaker
  reaches none. A bridge registered to one person is reached only by that person's turns.
- **The app pins before it sends.** A connection is opened and the certificate the bridge presents is compared with
  the fingerprint before the request, token included, goes out; a different certificate is `pin_mismatch` and nothing
  is sent. A call that reaches nothing, or whose read gets no answer, is `herdr_unavailable`; a change sent and not
  answered is `unconfirmed`.
- **A bridge serves one person.** The first successful call carries the person id in a header; the bridge records
  it and refuses any other person from then on (`wrong_person`) until it is set up again. A token copied into
  another person's row still opens nothing.
- **Mutual TLS both ways.** The app presents a client certificate issued by the `ashley-bridges` CA in OpenBao; a
  bridge accepts only that CA's clients, over TLS 1.3. The bridge's own certificate is self-signed at install and
  pinned by fingerprint on the connection row, so no public CA or DNS name is needed on a home machine.
- **The bridge calls the `herdr` CLI, not the socket.** The CLI is herdr's stable interface; the socket protocol
  is private and versioned. It runs as the person's user, beside their herdr server, and exposes a typed API: it
  has no way to send keys or text to a pane or to run a command.
- **She may start and close sessions, within bounds.** A start names a directory under a root the person listed
  when setting the bridge up, a label and optionally a model; a folder that does not exist yet beneath a root is
  created (symlinks and `..` resolved first, so nothing is made outside the roots). The session list carries the roots
  as absolute paths, so she starts under one instead of guessing, and a bridge that sends none leaves them unknown
  (`null`). Anything outside the roots is `dir_not_allowed`, and a start whose
  agent does not report a state comes back `unconfirmed` with its tab closed again. A close ends the session's pane.
  She still never answers a blocked dialog: a blocked session refuses a prompt. A voice path into an agent with a
  shell must not be drivable by the TV or a guest, so these tools are offered only when the reply reaches the
  connected person alone.
- **A job session runs unattended inside its own folder.** The folder of a bench job (`<root>/ashley-jobs/j<id>`) is the one
  place the bridge starts a session with permissions already granted: a settings file, passed with `claude --settings`,
  allows Read, Edit and Write on that folder's real path and nothing else. A project `.claude/settings.json` would not do,
  since Claude Code ignores a project's allow rules until the folder is trusted, and a new folder never is. A prompt for
  anything outside the folder stops the session as before, `blocked`, for the person to answer. A bypass or skip-permissions
  mode is never used. A session she starts anywhere else gets no extra permissions.
- **Her tools are `claude_sessions`, `claude_read`, `claude_prompt`, `claude_start` and `claude_close`**
  (`ashley.tools.claude_code`), offered by the gate the code host tools use (`audience.owner_alone`, connections
  openable) and only to a person with a `herdr` connection. Prompt, start and close are not proposed first: the
  bridge's bounds above (a ready session only, a directory under the roots, no way to answer a dialog) are what keep
  them safe, and the person asked for her to drive their sessions. Rejected: a confirmation per prompt, which would
  make handing a session work a two-turn exchange the bridge already makes safe.
- **Prompting refuses rather than interleaves.** A session that is `working`, `blocked` or `unknown` is refused
  (`busy`, `blocked`, `unknown_state`) and nothing is sent; she says so. A timeout after sending is `unconfirmed`:
  she reads before she would say anything about it, and the turn's checkpoint already keeps a resumed turn from
  sending it again. Typing within `typed_quiet_s` will refuse too (`person_typing`) once the bridge reports it.
- **The session sense is a Watches kind, over the sessions she handed work to.** `claude_start` and `claude_prompt`
  arm a `claude_session` watch on the session (`Watches.arm`, `armed_by` `handoff`) from the status and
  `state_change_seq` it was in, with the bench whose talk made the call, and say `watched` in their result so she tells
  the person when it could not be armed. The `watches` singleton wakes her for a `blocked` or `done` stop, and for an
  `idle` one that did not follow a `done` (the kind's `when`, "Watches wake her when what a read returns changes").
  `idle` is a finish someone has already looked at (herdr's seen state), so `done` becoming `idle` is only the look and
  wakes nothing. A finished session stays watched: Claude Code shows finished once its subagents return, while a Monitor
  or background shell (any command past ten minutes in the foreground becomes one) can still wake it. Rejected:
  forgetting a session at `done` until her next `claude_prompt`, which left a second finish unseen until the person
  asked. Each later finish costs one turn of hers, which Initiative keeps
  quiet when there is nothing to say. The state is Postgres's, never the process's, so the lease moving between sites
  loses nothing and replays nothing; the turn's `source` is its wake's id. Nothing is replayed at first sight because
  the baseline is the state the session was in when she handed it work. Behaviour keys on `status` and `seq`, never on
  the screen. A hand-off watch ends when the session is gone from its bridge's list, or after `handoff_hours`.
- **The woken turn runs where the work was handed over, and she decides what comes of it.** Her unprompted turn is on
  the talk of the bench whose turn made the call, while that bench is open, else on the person's phone thread, with the
  person as the one it is with; the stored message is the household's turn naming the session's label and status, and
  her brief is a note. She has that thread's tools, so she may read the session, edit the bench or prompt it again, and
  whether she tells anyone, and where, is hers (see "Web push", "A woken turn routes itself"). Rejected: holding the turn to
  `promised`, which would force a word out whatever she found; always the phone
  thread, which has none of the conversation that made the promise.
- **The bridge reports when its person last typed**, per session and overall, read from Claude Code's transcript
  (user entries a person typed), minus the prompts the bridge sent itself, since herdr's paste is recorded in the
  transcript exactly as typing is. Only a time crosses the wire. A transcript it cannot read is `null`, and an aside
  treats `null` as focus. The field exists on the wire and is always `null` until the reader is built.
- **Anyone can connect their own Claude Code**, by running the bridge where their sessions live, registered to
  their person. A session's state is that person's to hear, not the household's.
- Rejected: the fingerprint as a second stored field. It would add a column and a panel field to every kind for
  one; the address carries it and `connections.address` is the one place that parses it.
- Rejected: verifying the bridge's certificate against a CA or its name. It is self-signed on a home machine with no
  DNS name; the pin is the whole trust.
- Rejected: exposing herdr's socket, or `herdr --machine` over ssh. Either gives raw send-keys and arbitrary input,
  and ssh gives a shell. Raw send-keys stays out of the bridge for the same reason.
- Rejected: the bridge pushing events to the app. It would need credentials to the app and a reachable address on
  both sites; polling from the lease holder keeps one direction of trust and survives failover with no handoff.
- Rejected: a bridge for the whole household. Sessions run on one person's subscription and see one person's
  repositories.
- Rejected: Claude Code hooks for the focus signal. A pasted prompt fires `UserPromptSubmit` the same as a typed
  one, and the transcript already records the time.
- Rejected: her own coding agent on the API. A worse Claude Code, paid per token from API credits instead of the
  person's Claude Code subscription.

## She hands a bench job to workers and stays with the person

A job that takes many runs or a long loop is not done in her own turn. She hands it to a worker with `bench_hand_off`,
names the pieces it needs, says it is underway, and goes on talking. A worker's result reaches her as a short summary and
the pieces it made, never its transcript ("A call carries only what this reply needs").
- One call hands off one to three jobs (`max_group`), a group. Each is a worker, a title, a brief and the pieces it is given;
  all are checked before any is recorded, so one that is not startable fails the call with its reason and records
  nothing. Past a worker's `max_running` for the person the call is `too_many`.
- Two workers, chosen by a field she sets: `agent`, a sub-agent of hers with the job's bench tools (`look_up`'s
  pattern, its own task `bench_job`), and `claude_code`, a session on the person's herdr bridge that gets the named
  pieces as files in `in/` and returns `out/` as file pieces. `claude_code` needs the person's own bridge connection and
  a bridge that reports the `files` capability. A bench turn makes at most `max_runs_per_turn` runs of its own, counted from
  the runs recorded against the turn so a resume counts the same; past that, the run is refused `hand_off`.
- Only the pieces she names go to a worker. A worker adds pieces and changes only its own (`not_yours` otherwise), so
  jobs running in parallel cannot contradict each other or her. She reconciles their results.
- A job is a row in `bench_jobs` (migration 0094) run by the `bench_jobs` singleton under a lease. An agent job whose pod
  dies is retaken from its brief and its own pieces: the bench is the checkpoint, and retaking is safe because nothing it
  can change lies outside them. A Claude Code job is stepped through `starting` (session started, files uploaded,
  prompted) to `running`, and survives a pod the same way: the session is reused and prompted again only when its
  state-change count has not moved. Deadlines and the group timeout are data (`jobs.json`).
- **A Claude Code job waits for a machine that is not answering.** A bridge that cannot be reached (`herdr_unavailable`:
  down, no TLS, or herdr stopped behind it) does not fail the hand-off or the start: the job is recorded `waiting`, with
  its deadline counted from the hand-off, and its card says so. The runner steps it each tick; when the bridge answers
  `sessions` it goes back to `due` and is started as any job. A job that never gets an answer ends `failed`, reason
  `herdr_unavailable`, at its deadline. A start that meets an unreachable bridge, after a reboot say, goes to `waiting` the
  same way. Her result says `waiting`, so she tells the person, and the group's watch wakes her when a waiting job starts
  or gives up. Any other refusal (`bad_token`, `wrong_person`, `pin_mismatch`) says the connection itself is wrong and
  waiting would not mend it, so it still fails at once (`bridge_refused`).
- **A Claude Code job's session is closed once the job has ended**, which is after its `out/` is collected, whatever the ending
  (`done`, `failed`, `timed_out`, `cancelled`). The runner keeps asking the bridge to close it until the bridge answers or
  refuses the connection for good, and records that it did (`closed_at`). The bridge keeps the newest
  twenty job folders (`keep_job_dirs`, a bridge setting) and removes older ones when a new job starts, never one a live
  session runs in; the files that matter were already taken into pieces. Rejected: leaving a finished session open for the
  person to step into, which left `done` tabs piling up in herdr; a person who wants to continue one prompts a new session.
- Its state is a `job` piece, a kind only the jobs' runner writes (`by_code`; any other author's Add or Edit is `bad_body`),
  so it is on Live and in the log. The person cancels from its card, her tool cancels it, and removing the piece
  cancels it.
- Its finish is one `bench_job` watch per group. It wakes her once, when the last job of the group ends, with every
  job's title, state, reason, summary and output pieces in one note; a job finishing first changes only its own piece. A
  Claude Code job that is blocked on a dialog wakes her at once, because only the person can unblock it. A group still
  unsettled at `group_timeout_min` has its unfinished jobs ended `timed_out`, and then wakes once. The result is outside
  text: the woken turn is tainted `watch`.
- `BenchJobs` lives in `errands` as its second job type; `tools` and `watches` call it.
- A bench turn that offers `bench_hand_off` and runs past `hand_off_after_s` or `hand_off_after_rounds` (`turns.json`) is
  told once, as an act note, that handing the work off is the way; the tool choice stays `auto`. A step on such a turn
  cut off at the token limit is asked again with the `too_big_hand_off` note instead of `too_big`, chosen by the tool
  being offered; a turn that has had that re-ask is not told the long-turn note too.
- Who may start one: a bench's talk where the reply reaches the speaker alone and nobody woke the turn, so a woken turn
  cannot chain jobs.
- Rejected: parallel turns on a bench, which contradicted each other. Checkpointing the worker's loop, whose tool results
  go stale and whose continuation is one provider's. Bench files pasted into the prompt. Reading the whole session cwd back
  (`out/` only). Choosing the worker from her words. A prompt nudge to hand off, since a stateless call keeps no rate.
  Rows in `errands`, which are one per turn and keyed by a source. A worker writing into her pieces.

## Home Assistant is a tool, not the host

Ashley is her own service; HA is one of the systems she calls. HA's conversation-agent model can't carry
long-term memory, initiative or tools outside the house. HA has three roles: a **sense** (state changes), a
**tool** (actuating devices) and a **channel** (its notify and media players out, perhaps Assist text in).

## Home Assistant wakes her; she decides

HA detects, she decides. An automation she writes on a bench and the person installs carries a **wake action**,
a call of HA's `rest_command.ashley_wake` with structured data only: the event (a slug), HA's id for that run
(`{{ context.id }}`), and optionally who (a `person.*` entity), what (a slug) and when. Never free text: the piece check
(`ashley.workshop.wake_action`) refuses anything else as `bad_automation`, and the intake refuses it again as rendered.
The rest command is set up once in HA's configuration, posting to `/api/wakes` with the house's device token.
Her automation guidance (`bench_automation_specs.instructions`) carries the exact action and says, from the house
(`Automations.has_service`, reading HA's service list: wired, not wired, or unknown when HA cannot be read), whether
this house has the rest command; she is told to look the house's setup up with her house tools before asking the
person, and to ask only what the house cannot tell her.

- **The intake is a device route, for the house's device alone.** HA is a device of the household
  (`python -m ashley.channels.devices add`, then `house`), signed in as every device is: a sealed bearer token, LAN
  only, the device's rate. Only a device set as the house (form `house`) may hand a wake in; a satellite, the tablet or
  a Discord server is 403, since a wake grants a rule's tools and a person's memory. The wake is stored and answered
  202 at once, so HA never waits on a model. Rejected: a token of its own for HA, a second credential store doing what
  device tokens do; telling HA apart by form `other`, which the tablet and the eval harness share.
- **One event id is one wake, and only the active site acts on it.** The route is served by every pod on both sites,
  so the lease cannot guard it: a request lands where it lands. So the intake is idempotent on the event id (unique per
  household in the one primary), and the turn is work she starts herself, run by the `wakes` singleton under the lease.
  The wake's id is the turn's `source`, so a runner killed after handing it in, whose wake is handed in again, gets the
  same turn. Rejected: refusing the request on the standby site, which drops HA's one call.
- **Her rule is a wake piece on a bench** (kind `wake`): the event it answers, a short brief for that turn, and the
  tools it may use. A wake runs a turn only when exactly one rule on the household's open benches answers its event;
  none is `no_rule`, two are `ambiguous`, and it is settled so rather than guessed. A wake about no person of the
  household is `no_person`; one waiting past `max_age_s` is `expired` (an arrival greeting an hour late is wrong). A
  turn that cannot run now (`RespondUnavailable`, as during a failover) leaves the wake due for the next sweep, the
  same turn by its source; only a refused one is `failed`. A rule's tool names the catalogue does not offer are logged
  as a count (`tools.only_unmatched`), never refused on the piece: the catalogue changes while a source is down, and
  `decide` is pure.
  Rejected: the brief and tools in HA's automation, which would put her prompt and free text in the house.
- **The turn is the shared turn loop**, `unprompted`: nobody waits on its response, so it never holds (a bench's reaction is the exception, "A reaction holds like a
  person's turn") and its answer is queued in the outbox with her stored turn, from whichever runner finishes it, checkpointed as every turn
  that takes later replies is. It runs on the phone thread of the person the wake is about, with that person as the
  one it is with, so her memory and the hearing rule are theirs, and its message is the household's turn (below), never theirs.
- **Whether it goes out is Initiative's**, from her reply's `worth_saying`, a structured field (decisions, "Whether
  she speaks unprompted is decided in code"). A reply kept quiet is stored as her staying quiet, never as words she did
  not say, so no later turn carries them. Rejected: an empty reply meaning quiet, which keys behaviour on text.
- **A household is a speaker in its own right.** A turn's author is `person`, `ashley` or `household`: the household
  speaking as itself, shown by its name (`households.name`), not as any one of its people. A wake is the first
  such turn (an event the house reported, stored as its fields alone: event, person, what; the page shows it as
  written). Her rule's brief and what her reply may do reach her only as the turn's `note`, added to her message and
  never stored, so never on the wire, the page or in later history. It has no
  speaker and no `follows` or `answers`, takes `source` (`wake:<id>`) as a person's turn does, and stays in the
  conversation of the person the wake is about, so her reply and the person's answer to it read as one exchange. Wherever
  turns are carried it is never a person's: her history renders it as
  `[From the <name> household, not words anyone said] <text>` (a user-role message, since no other role is hers), a
  relevant older one as `<name>: <text>`; the memory write job never shows it to the writer and never counts it as new
  words; the earlier-conversations wire has `author` `household` with the household's name as `speaker`, and the page
  shows a quiet line under that name, not a bubble. Anything else the household later does as itself (a connection it
  owns, a device of its own) takes the same author. Rejected: the brief in the stored turn, which put her prompt on the person's page; marking it in the message text, which keys behaviour on
  words; an author of its own for the house device, since the house is the household's; hiding it from the person's
  history, which leaves her unprompted message with no visible cause; a column for who the household is, since the
  turn's `household_id` already says. The wake's conversation stays unremembered; that is no longer what keeps the
  household's turn from being learned as theirs.
- **Settled wakes are kept a week** (`keep_s`), pruned by the singleton each sweep, logged `wakes.pruned`.

## Reminders are wakes she sets for herself

A person will not remember anything that isn't set somewhere, so she owns their reminders. A
reminder is a wake she schedules: a row of the same `wakes` queue, kind `reminder`, due at its time, taken up by the
same `wakes` singleton under the lease and run through the same turn loop. There is no second scheduler.

- **A reminder is structured fields only:** whom it is for (`person_id`, a person of the household), who asked
  (`made_by`), when it falls due (`due_at`), what to remind them of (`brief`, up to 500 characters, kept in Postgres
  and never logged, since it can carry money), and how it repeats (`repeat`: daily, weekly, monthly or yearly, every
  `every` of them, from its first wall-clock time, `ashley.senses.repeat.Repeat`, shaped below), or once. Never free
  text for the time or the rule. Rejected: an RFC 5545 rule string, which needs a parser the app does not carry; the
  part of it she needs is fields.
- **Times are the household's wall clock** (`households.timezone`), kept across daylight saving: the 1st at 09:00 is
  09:00 in winter and summer. A monthly reminder on the 31st falls on a shorter month's last day, and on the 31st
  again after; a wall time the clocks skip fires an hour later, one they repeat fires the first time.
- **One occurrence is one row, and one turn.** Settling an occurrence of a repeating reminder stores the next one in
  the same statement, and only when that call is the one that settled it, so an occurrence has exactly one successor
  however many runners settle it. The occurrence's id is its turn's `source`, so two runners at once, or a runner
  killed mid-turn whose occurrence is handed in again, give one turn and one push (decisions, "Work in flight survives
  its pod").
- **A missed occurrence fires once, late.** The next occurrence is the first after now or after the one firing,
  whichever is later, so after an outage the one that was due fires and the series carries on in the future, never
  every missed one in turn. A reminder never expires: a late "pay the card bill" is still wanted. Rejected: firing
  each missed occurrence (three pushes of one monthly chore at once), and expiring them as a house wake expires.
- **It goes out because they asked.** The fired turn is `promised`: it goes out whatever Initiative would say, and her
  reply only words it. Rejected: leaving it to `worth_saying`, which could keep a reminder quiet.
- **It reaches the person alone.** The turn runs on their phone thread (`push:<person id>`), with them as the one it is
  with, on a channel only they read (`ashley.channels.audience.owner_alone`), never a satellite, the hallway tablet or
  Discord. A reminder is never a glance source on a shared screen.
- **It looks before it reminds, and only looks, unless it names its tools** ("Reminders she shapes", below). The fired turn is offered the tools that change nothing, those whose
  spec says `reads` (`ashley.tools.reading.Reading`, set by `Inbound.reads_only`), and only where
  `audience.owner_alone` holds, else none: a "move anything past $300 into savings" reminder says how much there is to
  move, or that there is nothing, from her money tools. It always goes out (`promised`); what she finds changes what it
  says, never whether. The turn is unattended, so a tool that acts is never offered. Rejected: no tools, which sent the
  reminder blind of money she can read; a hand-kept list of tool names, which drifts from the specs, where `reads` is
  already what the tool loop trusts to dedupe repeated reads; offering the reminder tools themselves to set the next.
- **A reminder is never lost silently.** Her answer is only stored, never queued in the outbox, which deletes what it
  hands out and drops what waits past `stale_s`. The push singleton sends it from her stored answer and records each
  try on the reminder (`ashley.channels.push.reminders`): delivered takes it off the person's list; reaching no
  browser (none subscribed, or every send failed) marks it undelivered at once, and it is tried again every `retry_s`
  for `deliver_for_s` (a day), a dismissed one never. Each try is claimed first (`Wakes.claim`, one conditional UPDATE), so
  two passes at once send once, whatever the lease. Her words are also in the person's conversation history, on their phone thread's
  conversation. Rejected: making the outbox keep promised rows until sent, which changes a queue every channel
  shares for one kind of reply.
- **A firing that cannot run is tried again, then shown.** A refused turn, or a person no longer of the household, is
  fired again `retry_s` later, up to `fire_attempts` times, then settled `failed` (a repeating one still goes on).
  An undelivered or failed reminder stays on its person's list, marked, and is never pruned, until they dismiss it.
- **A day with no time is 09:00** in the household's zone: `remind` takes a date alone, and its spec says so.
- **She sets them with tools, by field.** `remind` (for, at, repeat, every, what), offered wherever the channel names
  the speaker; `for` is an enum of the household's names. Listing (`reminders`) and cancelling (`cancel_reminder`)
  are offered only where the reply reaches the speaker alone, since a listed reminder says what it is for.
- **A person may set one for another person of the household**, which both of them see and either may cancel:
  household trust, as with the house. Rejected: reminders only for oneself, which would leave "remind my partner to
  bring the bins in" to a person.
- **A person sees and cancels theirs in the Memory room** (a Reminders tab beside About you and Household), through
  `GET /api/reminders` and `DELETE /api/reminders/{id}`, which also dismisses one listed undelivered or failed. Rejected: the Devices room, which is about what is connected
  to the household.
- **Settled reminders are kept a week** (`keep_s`), then pruned with the settled house wakes; one still to fire, or
  listed undelivered or failed and not dismissed, never is.

## Her proposals are one store

A person's OK to something she proposed is one primitive: a **proposal** is a pending OK for a typed payload, taken only
from a later person turn of the conversation it was made in. It is a Command awaiting confirmation (the record is
the command, `take` is its `decide`) whose kinds are a Type Object: money rule, reminder to schedule, change to a
reminder, change to the house. A new user of the pattern adds a payload kind, not a table: one store holds what two
tables and two services, copying the same replace, expire and take-once code, once did. Fits into: Senses (the
gate `proposal_gate` already lived there), Tools (`ReminderTools`, `HouseChangeTools`).

- **One service, `ashley.senses.proposals.Proposals`** (`propose`, `pending`, `take`; table `proposals`), whose payload
  is a tagged record that code decodes, never her words (`ashley.senses.proposal_payloads`: `MoneyRule`,
  `ReminderSchedule`, `ReminderChange`, `HouseChange`, each stored as a JSON object with its `kind`). A new kind of
  thing she asks OK for is a payload record and its stored form, not a table or a service.
- **A topic is a family that replaces itself.** A person has one pending proposal per conversation *per topic*
  (`REMINDERS`, `HOUSE`): proposing in a topic replaces that topic's earlier one, and a house change and a reminder
  proposed in one conversation are agreed or refused apart, as they were with two tables. `propose` drops only its
  own topic's proposals older than `ttl_s`. The replace is one transaction under a Postgres advisory lock on the
  (person, conversation, topic) key, so proposals made at once serialize and the later one is the only row left.
- **Taking is one gate.** `take` refuses `none`, `same_turn` or `expired` by `ashley.senses.proposals.refusal`: turn
  ids and the age of the proposal (`proposal_gate.gate`), and for a reminder to schedule also its first time having
  come. It consumes the proposal, and of two takes at once one wins. `proposed_at` is stored as given, which the TTL
  reads. The caller carries it out; the store never does.
- **The payload's own limits are the payload's.** A reminder's brief (1 to `MAX_BRIEF`, no NUL), its tool count, and a
  money rule's having no repeat are checked by `proposal_payloads.check` before anything is replaced.
- Rejected: one proposal per conversation across topics, which would let a reminder proposal silently replace a house
  change awaiting an answer; a column per payload field, which is the table-per-kind again; free text or a prompt
  that says what was proposed (behaviour keys on fields); a proposal id she passes back, which she
  loses between messages; a partial unique index on the key, which needs a migration that dedupes
  existing rows for what the lock gives with none.

## Reminders she shapes

"Every weekday at 8 water the plants", "for the next six weeks remind me Sundays", "at 6pm turn the porch light off": a
reminder is a small set of fields she fills per ask, so none of these is a special case (`engineering.md`, "Her systems
are general, and she wires them"). Fits into: Senses (the `wakes` queue and `Repeat`), Channels (the reminder turn) and
Tools (`ReminderTools`, with `Only` as a wake turn uses it); nothing new is a system.

- **A repeat names weekdays, which one of the month, and an end.** `weekdays` (Monday to Sunday) on a weekly rule is
  "every weekday" (weeks start on Monday, `every` 2 is every other week); on a monthly rule with `nth` (1 to 4, or -1
  for the last) it is "the first Monday", "the last Friday". `until` is the last local day it may fall on. The rule
  starts at the first of its days on or after `at`, and a first time already past rolls to the next one after now.
  Every occurrence is still the anchor's wall time in the household's zone, so the DST rules above hold for each.
  Weekdays on a daily or yearly rule are refused. Rejected: an RFC 5545 string; `BYSETPOS` as a general set position
  (only the nth weekday of a month is asked for); a day-of-month list.
- **A count is sugar for an end.** Her `count` becomes the day of the count-th occurrence (`until_after`) and only
  `until` is stored, so a rule has one way to end and an edit never restarts a count. Rejected: storing the count, which
  needs a remaining-count that each occurrence row decrements, or restarts when the series is moved.
- **A reminder's words go where its route says.** `phone` (the default, today's behaviour) or `quiet`: the turn runs,
  her answer is stored in the person's conversation, nothing is pushed and the reminder is never listed as undelivered.
  A turn that acts and has nothing to add is quiet. Rejected for now: a room's speaker or the kiosk as a route. A
  satellite's reply goes through the Outbox, which drops what it cannot say (the satellite not connected), and a
  reminder is never lost silently; it needs a delivery with the reminder's own retries first (`open-work.md`, "A reminder said in a room").
- **A reminder names the tools its turn may use**, by name, through `Only` as a wake rule does (`Reminder.tools`; none
  named keeps the tools that only read). Only tools the speaker has in the turn she sets it in can be named
  (`ReminderTools` is given the turn's other tools), never the reminder tools themselves, and only in a turn that
  reaches the speaker alone. Rejected: a hand-kept list of allowed tool names; naming tools from the household's whole
  catalogue, which would let a satellite's turn grant a phone's money tools.
- **One that acts is proposed, then agreed in a later person turn**, by the pattern the money rules use
  (`Proposals.propose`, `take`, `refusal`; tool `arm_reminder`): `remind` or `change_reminder`
  with tools that change something stores a proposal and returns it; the reminder exists only after the person's next
  message and her `arm_reminder`, within `proposal_ttl_s` and before its first time. Tools that only read, and edits that
  add no acting tool, take effect at once. It is for the speaker only: acting on another person's phone thread under
  their name is refused. In three of nine live runs she answered "yes" by proposing again, which replaced the proposal
  and left nothing to agree; the guidance now says agreeing is `arm_reminder` alone, and six of six runs after it armed.
  Rejected: a second proposal store ("Her proposals are one store"); arming in the same call; a `confirmed` argument.
- **An edit keeps the reminder's row and the occurrences already fired.** `change_reminder` rewrites the unsettled
  occurrence's time, what, repeat, route and tools (`Wakes.edit`); the next occurrences copy it. Giving `at` moves the
  next time and starts the rule over from there, so a monthly rule on the 31st moved to the 30th stays on the 30th; the
  fields left out stay. A reminder that waits on money keeps its time and may change what it says, route and tools.
  Rejected: cancel and set again, which loses the id and what was fired; editing who it is for.

## A reminder can wait on a deposit

"When the bonus lands, move it to savings that day" has no time to set, and half the point of her is that she
sets these up herself. A reminder gains a trigger of kind `event` beside its time, and the event is a
deposit into the household's Sure.

- **The rule is fields she sets, never her words:** `account_id` (as Sure identifies it, with `account_name` only for
  showing it), `min_cents` (a deposit of at least that), and `payee` as Sure names it with `payee_match` (`exact` or
  `contains`, case-insensitive), against the transaction's merchant name and its own name. At least a minimum, a
  payee or conditions ("Rules she writes are composed from general predicates", below); a deposit is a transaction Sure classes income, not a transfer, split parent or excluded, dated on or after the
  day the reminder was set (a transfer in is excluded in Sure, so it never counts; a refund is income, and does) (`ashley.senses.deposit_rule`). Rejected: matching on her words about it (a regex or a
  phrase over what she wrote), which misfires and cannot be shown back to the person as what it waits for.
- **She reads once, proposes the rule in plain words, and it is armed only after the person has answered.**
  `remind_on_money`, offered with the other reminder tools where the household has connected Sure and the reply reaches
  the speaker alone, only *proposes*: it stores the rule (a proposal, with the conversation and the person's turn
  it answered) and returns it in words. `arm_reminder`, with no arguments, arms the latest rule she proposed to
  this person in this conversation and is refused unless the turn it runs in is a later person turn, within
  `proposal_ttl_s` (`ashley.senses.proposals.refusal`: turn ids, never her words or theirs); it consumes the proposal. The guidance tells
  her to read `money_accounts` once and one `money_transactions` search, work out the account (the person's name for it,
  or where the regular income lands when no account is so named, put in the proposal to confirm, never declared not
  connected) and what counts, and say that in one line in the person's words (never the tool's field names). Two live
  runs in six armed a guess in the turn they proposed it, so confirmation is code, not prose. She is offered `arm_reminder`, and
  its guidance, only in a turn after a proposal of hers (`ReminderTools.catalogue`): when it was always offered she
  tried it in the turn she proposed, was refused, and worded the reply as if it had worked. A new proposal replaces her
  earlier ones in the conversation, so one agreement arms one rule (two had armed in one turn). It covers every rule,
  also one the person gave a payee or amount for, so there is one path and no field to claim "they already agreed". What it
  cannot tell is whether the later turn agreed. Rejected: arming in the same call with her description shown to the
  person afterwards; a `confirmed` argument, which she would set herself; arming by a proposal id, which she lost between messages and answered by asking for a second confirmation; reading the person's reply for "yes", which
  keys behaviour on words. The payee-only case: she armed a rule that would have fired on every paycheck straight after
  the person answered a question about the account. A bonus has no payee or
  amount to ask for, so the rule says what is unusual instead (below). The bound is the guidance's count of lookups,
  since the tool loop caps rounds for the whole turn and nothing per tool. Rejected: asking for a payee or a minimum on
  a deposit that has never landed (it has neither, and the account's history is hers to read); arming a guessed payee
  or amount (a proposal the person confirms is not a guess armed silently); searching on until the round limit, which
  in production spent all six rounds and set nothing; asking the person for the account, which is the lookup she exists
  to do; `anyOf` in the schema, which not every provider adapter accepts.
- **The fired reminder's turn gets the transaction, not only her brief.** The tool description said she would see only
  `what`; she also gets the amount, day, payer, account, which predicates held and the payer's history
  (`ashley.channels.wake.reminder_turn`), so `what` need not carry them.
- **An armed reminder is a `wakes` row, trigger `event`, unsettled and never due**, listed on the Reminders tab with its
  rule in words and cancelled like any reminder. Each match stores an ordinary once reminder beside it, so her turn and
  the push singleton's durable delivery are the existing reminder path, and the armed one stays armed: every match
  fires, every bonus, until someone cancels it. Rejected: settling it on the first match, which makes the person ask
  again each time.
- **Money leaving is the same sense, one field apart.** The rule carries `direction`, `in` (a deposit, the default for
  every rule stored before it existed) or `out` (a withdrawal), which she sets as a required field of `remind_on_money`
  ("tell me if anything over $500 leaves checking", "when the car insurance comes out"); the account, minimum and payee
  are the same fields, and the payee is matched against the merchant and transaction name as before. An `out` match is a
  transaction Sure classes expense (`signed_amount_cents` negative in its API, `type=expense` its filter), not a
  transfer, split parent or excluded, so moving money between the household's own accounts never fires it. The poll asks
  Sure for expenses only while some armed rule in the household is `out` (and for income only while one is `in`), under
  the same lease, cursor, lookback and per-transaction event id. `Landed` carries `direction`, and her turn on it says
  the money left, to the payee, from that field. Unverified against a live Sure:
  that an outgoing transfer carries `transfer`, that a card payment is not classed expense without it, and the
  `type=expense` filter on the real endpoint; the fake follows the shape the deposit work recorded. Rejected: a second
  tool and sense for withdrawals (two near-copies of one rule, poll and cursor); a separate cursor per direction (a
  rule armed later reads from its own day, so one day per household is enough); a direction defaulting to `in` in the
  tool (a missing field is a question to ask, not a guess). Names kept: `Deposit`, `DepositRule`, `Deposits`,
  `deposit_rule`, the `deposit_rule` column and the `on_deposit` field of the reminders route now cover both ways; a
  rename touches the blind suites, the wire contract and a column, and buys no behaviour.
- **A singleton under the lease reads Sure** (`ashley.senses.deposit_sense`): every `poll_s`, for each household with an
  armed reminder, the income transactions through its connection from `lookback_days` before the day it last finished
  reading, the oldest pages first when `max_pages` cannot hold them all, and then only as far as the newest
  day it read, so the rest comes on the next poll. That day is `deposit_reads`, in Postgres, recorded only after every match is stored, so a failed poll is read
  again whole and a deposit that lands while nobody holds the lease is found by the next holder.
- **The fired reminder carries the deposit.** The once reminder stores what matched as fields (`wakes.landed`: amount,
  day, the rule's account name, and the payee as Sure names it, `ashley.senses.deposit_rule.Landed`), and her turn
  states them from those, so she never has to find it again. Rejected: her turn re-reading Sure to find the deposit,
  which can pick another.
- **One deposit fires one reminder** whoever reads it: the once reminder's event id is derived from the armed reminder and
  the Sure transaction id, which the wakes table keeps unique per household. A retry, a second reader or a holder with
  no memory stores nothing twice. The lookback (days) stays under the wakes' keeping (a week), so a pruned reminder
  cannot let its deposit fire again.
- **Logs** carry one line per poll (household, transactions read, matches, fired, duration) and one per fire; never an
  amount, payee or account name.

## Rules she writes are composed from general predicates

"Move it to savings whenever I get a bonus" has no payee and no amount: a year-end bonus may come through the payroll
payee at a larger amount, a one-off payout from a payer never seen at an amount no one can predict.
No payee-and-minimum pair catches both, and neither does a built-in "unusual deposit" test. So she gets a
small language she composes per ask, and keep the classification hers (`engineering.md`, "Her systems are general, and
she wires them").

- **A money rule is the old payee and minimum plus `clauses`**: alternatives, each a list of typed predicates that must
  all hold, any one alternative sufficing (`ashley.criteria.predicates`, in a package of its own over a backend-neutral
  record, `ashley.criteria.record.Transaction`, so another sense can judge by the same predicates). The kinds are a
  closed set: `payee`, `amount` (min and/or max), `day_of_month` (a window), and three measured in code from the payer's
  own deposits into the account over `days`: `amount_vs_usual` (above its largest or below its smallest by a percent),
  `day_vs_usual` (off its usual cadence by more than a tolerance) and `payee_new` (paid fewer than `min_seen` times).
  Each takes `not`. Too little history makes a history predicate false, not true. The bonus ask is expressible as
  `[[payee PAYROLL, amount_vs_usual], [payee PAYROLL, day_vs_usual], [payee_new]]`: the payroll payee off its usual
  amount, off its usual day, or a payer new to the account. Every parameter is hers; defaults and limits are data (`app/ashley/senses/deposits.json`). Fits
  into: Senses (the deposit sense and `DepositRule`), extended; no existing rule representation exists to share (a wake
  piece matches an event slug alone, an automation's conditions are Home Assistant's own).
- **She may hand the match to her own judgement.** A rule with `judge` stores the match with the payer's history and its
  fired turn is not `promised`: her structured `worth_saying` decides whether it is sent, as for a wake (decisions,
  "Whether she speaks unprompted is decided in code"); a kept-quiet answer is recorded done with nothing pushed
  (`push.reminder` outcome `kept_quiet`). Code keys on that field, never on her words. Rejected: a second structured
  field (`tell`) beside `worth_saying`, which already means this.
- **The sense reads a neutral record.** It reads the Ledger (`ashley.senses.ledger_transactions`) and derives
  `Transaction` records from its entries; the sense and every predicate see nothing Sure-shaped, so Actual Budget would be
  another Ledger adapter. A rule that reads history makes the sense read `days` further back (and `judged_days` for a judged fire).
- **Rejected: a fixed "unusual deposit" classifier** with a lookback and tolerance in code: she gets a system to use,
  not a hardcoded classification. Rejected: a recursive and/or/not tree in the schema, which not every provider
  adapter accepts; alternatives of conjunctions say the same thing in flat arrays.
- **Unverified:** that the cadence measure (median gap, tolerance in days) suits a payer on a twice-monthly or irregular
  schedule beyond the cases tested; the defaults are data to tune.

## She runs her own voice pipeline

Satellites (Voice PE, ESPHome) talk to Ashley directly over the ESPHome native API (`aioesphomeapi`, the client
HA itself uses); wake word and echo cancellation stay on the device; STT and TTS sit behind the inference
interface (Wyoming for faster-whisper). The pipeline is the voice channel adapter, not a new system.

- **Speaker identification needs the audio**, and HA hands its conversation agent text. Owning the pipeline also
  gives streaming TTS, barge-in, and her own rule for when to keep listening.
- **A satellite connection is a singleton**: the active site holds it under the etcd lease, or both sites answer.
  One singleton (`satellites`) holds every household's satellites.
- **End of speech is a wait tuned as data**, not code: microVAD scores each 10 ms frame and the silence window,
  speech needed to start, and longest utterance live in `app/ashley/channels/voice/voice.json`. They start at Home
  Assistant's segmenter: a low bar (0.2) for speech to start, tolerating gaps under a second, a higher one (0.5) to
  keep it going, then 700 ms of silence; tuned from the `voice.run` line's durations.
- **Her reply clip is text, synthesised when it is fetched.** A run stores the reply in `voice_clips` under a random
  token kept only as its SHA-256, commits it, and only then sends the URL; `GET /api/voice/clips/{token}` streams
  `Inference.speak` of it. Any pod on either site can serve the fetch, so nothing is held in the singleton's pod.
  Rejected: storing the audio (state to replicate for a file played once) and streaming it down the satellite's API
  connection (only the singleton's pod could serve it, and a room speaker needs a URL anyway).
- **The pronunciation lexicon applies to every spoken reply**, in `render`, so a spoken device on `POST /api/messages`
  gets the same spellings as a satellite.
- **The pronunciation words are the household's.** A small table beside the household (`household_lexicon`, one row per
  household and real spelling), edited by any person of it in the Devices room, read by the household a reply renders for
  on every spoken render and held nowhere between renders, so an edit applies to the next reply and no household hears
  another's. A render with no household, a household with none and words that cannot be read are all an unchanged reply,
  logged `lexicon.unreadable` for the last. A new household starts with none. A word is one word-like token with a spelling, each at most 64 characters, and a household holds
  at most 200. Rejected: a TTL cache (a second household's reply must never wait on the first's edit), a connection
  setting (no service stands behind it), and a version column (rows are edited one word at a time, so there is no whole
  object to conflict over).
- **The wake word opens a conversation; she keeps the mic open within it.** After she speaks, or when she opens
  a conversation herself, the satellite listens for the reply with no wake word, then closes on silence. Flowing
  conversation without a constant stream.
- **Rejected: always-on listening.** Every room's audio streamed to two clusters is a privacy and bandwidth cost
  the household didn't ask for.
- **A tablet on HA Assist can stay a satellite while her own pipeline runs beside it** on an Atom Echo; the tablet
  moves to her own page later (open-work, "The hallway tablet").
- **A room's ears and voice can be different devices.** A satellite can be only the microphone while her reply
  plays on that room's Nest or a better speaker; Nests are output only anyway (HA cannot reach their
  microphones). An Atom Echo cube (one mic, no echo cancellation, a tiny speaker) is cheap enough for
  this; rooms that need interrupting her mid-reply get a Voice PE.
- **Her voice reaches a satellite as streamed 16 kHz WAV** (`pcm_16000` behind a WAV header). A satellite decodes
  only what its firmware declares: the Echo's media player is built for WAV and silently played nothing from MP3.
  HA converts per device with ffmpeg; she sends the one format every satellite and Cast can play, which also leaves
  the device nothing to decode. Changing the `speak` route's format means checking each satellite's firmware first.
- **Looked at, and fine: speech tasks optional in `routes.parse`.** The shipped `routes.json` is held to having both by
  `app/tests/test_speech_routes.py`, so requiring them in the parser too would only rewrite the routes contract tests.
- **Looked at, and fine: the reply call's shape.** Measured in the pod on the real command prompt (Haiku, 10.5k tokens
  cached): first token about 0.7 s and the whole short reply about 1.0 s. Leaving out the tools saved about 70 ms,
  inside the noise, so neither a tool-using sub-agent nor tools offered on demand is a latency fix: each adds a model
  round (about 1 s) when a tool is needed. Both stay token levers (open-work, "Golf the system prompt"). Dropping the JSON schema changed nothing, nor did a spoken-only schema
  (half the output tokens, no faster). `effort: low` stays: without it a reply ran to 300 tokens and 2.4 s.
- **Rejected: HA's Assist pipeline pointed at her.** Text-only input rules out voice identification, and
  continuing a conversation hinges on HA's heuristics (a reply ending in "?").

## A voice names the speaker as a hint, never as a credential

On a satellite the speaker is unknown unless one person is home. Each wake's utterance also gets a voiceprint, a
vector of how the voice sounds, compared with the prints enrolled for the household's people. A close enough match
names the speaker.

- **Voice is not authentication.** A replay, the TV or a sibling can match. That costs little here: a satellite's
  audience is never `owner`, so private facts are filtered out whoever is named. What a name widens is the speaker's
  own non-private facts, and whose name new facts are written under. Anything acting with a person's authority
  (their Claude Code sessions, an errand that writes automations) needs a channel that names the person; a voice
  match is not enough.
- **Order of signals:** a channel that names the person, then a voice match, then presence (one person home). A
  match for someone presence knows to be away is refused.
- **A match needs a floor and a margin**: the best person's score at or above `floor`, ahead of the runner-up by
  `margin`, on at least `min_audio_ms` of audio. Each person's score is the cosine against the mean of their prints.
  The numbers are data in `voice.json`. Until `decides` is set there, matches are only logged.
- **Accuracy is measured without a person labelling anything.** When exactly one person is home, presence names the
  speaker, so each logged match says whether it agrees. That rate on real wakes sets `floor` and `margin`, and decides
  `decides`.
- **Enrolment uses the device's own wakes.** The admin CLI arms a device for a person for a number of wakes. Each of
  those wakes stores its print for that person and is answered as usual. The audio is never stored, only the
  vector. The device's own mic and room are what the prints will be compared against, which a clean recording
  elsewhere is not.
- **A print carries the model that made it**, and only prints from the current route's model are compared. Vectors
  from two models are not on one scale.
- **The model is NeMo TitaNet-small through sherpa-onnx**, in-process on CPU (about 20 ms per wake), baked into the
  image like the text embedder. On 23 LibriSpeech speakers it separated 1.5 s clips with 0% EER clean and 1.6% at
  10 dB SNR. That bounds the choice only; the Echo at two metres is measured from the logs.
  - Rejected: CAM++ (WeSpeaker and 3D-Speaker). Through sherpa-onnx 2.0.1, different speakers scored 0.78 cosine and
    EER was 25-50%. The cause was not found.
  - Rejected: WeSpeaker ResNet34 (34% EER at 10 dB) and ERes2Net (7%, about twice the CPU).
  - Rejected: SpeechBrain and pyannote, which need torch in the image.
- **Who was matched is never logged**, as presence never logs who is home: a person's id on a device's wake is a
  record of where they were. `voice.speaker` carries the outcome, the scores and whether presence agrees.

## Active/standby with one writer, not active/active

Every Ashley pod in both clusters serves requests; there is exactly one writable database and one site running
singletons. State is what makes an assistant, and two writable copies across a WireGuard link over a home
uplink diverge or split-brain.

- **Rejected: active/active with two writable stores.** Divergent memories, doubled singletons, and the
  anycast-app drift the cluster repo already warns about, applied to her memory.

## Work in flight survives its pod

A rollout, a failover or a move between sites carries on whatever she was in the middle of, on the new commit or
the other site, and nobody notices. So nothing she is doing lives only in a pod's memory: work that spans more than
one step (a turn's tool loop, an errand, a code run) is checkpointed in Postgres after each step and claimed under a
lease, so a pod that stops releases it and any pod on either site resumes from the last checkpoint. A step with a
side effect is recorded before and after it runs, so a resumed piece of work never repeats a change it already
made. A reply reaches the person's screens through Live wherever it is made, not only through the request that
asked for it.

- **Rejected: finishing work in flight before a pod stops.** A clean shutdown can wait, but a kill, a node loss
  or a site failover cannot, and those are the moves that matter.

**What lived in a pod's memory, and how each comes under this.** Already conforming: the outbox, the Discord claims
and Live (each in Postgres, or costing only a refetch); a look-up sub-agent, which runs inside one read and is run
again; a workshop Command, one transaction; a bench's Run, logged and then recorded before it runs, never run again;
a bench's Install, logged and then recorded before it writes to the house, never carried out again.

| Work | Lost on a kill | Under this decision |
|---|---|---|
| A turn partway through its tool loop (`tool_loop.answer`) | the reply; a change she made is not repeated, but nobody hears it was made | the turn's work row, below |
| A held turn finishing in the background (`Held.running`) | the answer after "let me check" | the same row: the background run is only its first runner |
| The web POST waiting on her reply | the reply on that page | a page's reply is the stored turn, which Live announces wherever it is made; the POST's body is a shortcut |
| Discord replies in flight | the reply, since the message is claimed and never answered again | the same row, its answer queued in the outbox with her turn; a message claimed by a session that died before its row existed is handed in again, below |
| A voice turn (`voice/run.py`) | the reply | the same row, its answer queued in the outbox with her turn and announced on the satellite |
| A reply's copy to the phone (`to_phone.copy`) | a copy queued twice, or an answer stored without it | queued with her turn in one transaction (`Outbox.answer`), below |
| The web page's view of a turn being resumed | the message shown missed while she is still on it | the conversation says which turns have work in flight (`working`), below |
| A memory act after the reply (`keep.now`) | a forget or correction she said she made | the same row, kept past her stored turn until the act is done, below |

- **A turn's work is one row, `turn_work`, keyed by the person's turn** (`ashley.conversations.inflight.InFlight`):
  its claim (`holder`, `claimed_until` by the database's clock), how many runners have claimed it, and the turn's
  checkpoint as JSON, which only the turn loop reads and writes (`ashley.channels.inflight`): the `Inbound`, the
  speaker, the system prompt as built, the entries so far, the round still running with each call's result, the
  changes started and not finished, and the fact ids offered. Conversations owns the row because
  finishing is storing her turn: `InFlight.finish` adds her turn and deletes the row in one transaction, only while
  the caller still holds the claim, so a turn gets one reply however many pods ran it.
- **Checkpointed per step, and around every change.** After each model step that asks for tools and after each call
  returns, the checkpoint is saved; before a change runs, its call id is saved as started. Each save renews the claim
  and fails once another runner holds it, so a change never starts on a pod that has lost the turn. While it waits on
  a model or a tool, a runner renews the claim every third of `claim_s`, and stops when none has succeeded for two
  thirds of it.
- **Resumed by one singleton, `inflight`, under `Lease`.** Every `poll_s` it claims the rows whose claim has run out
  (`FOR UPDATE SKIP LOCKED`, so an overlap cannot claim one twice) and runs each from its checkpoint: a read with no
  result runs again; a change with its result is not run; a change started with no result is never run again, and she
  is given an error saying it may or may not have taken effect, so she checks before acting again. A resumed turn
  never holds, since its answer reaches the person as a stored turn, and its deadline counts the work done in its
  current window (`Checkpoint.worked_s`), never the time it waited to be resumed. A clock that included the 120 s retry gave
  resumed turns no rounds at all. A row claimed `max_attempts` times is given up, logged `respond.failed reason=gave_up`, with no reply.
- **A turn fails to the person only once its row is known to be gone.** A runner whose turn fails (unavailable,
  refused) deletes its row and then says so, since a reply after "she cannot answer" is worse than the gap. When the
  row may survive (the database unreachable, or another runner holding it), she does not say the turn failed: the
  reply is pending, `follows` with no words, the page shows her still working, and the runner that finishes the turn
  delivers the answer through Live. If that work ends with no reply (refused, given up, unstorable), its person's
  screens are told through Live as the request would have told them (`TurnFailed`, the message shown unanswered) and
  she is idle, under the turn's own token, which the checkpoint carries. A runner that stops without returning
  (killed, cancelled) leaves its row to be resumed.
- **A reply that cannot be stored is never sent.** On these channels the reply is the stored turn, so when the
  conversation refuses it (closed, or a turn it does not store) the row is deleted and the failure logged
  (`respond.failed reason=unstorable`, with `cause`, the refusing error's class, and for a refused turn `check`, its
  fixed phrase: never text), and the turn is never resumed.
- **A reply with nothing to deliver is never stored empty.** A step whose reply has no text for the medium
  (`unsaid.empty`; `Reply.worth_saying` false is exempt) is asked again once as a wrap-up (tool choice `none`, with a person note
  from `unsaid.json`, the same note every closing step after a lookup carries, at the last round or the deadline, saying she has no more lookups and to say what she found and what she still needs), and an empty wrap-up is replaced
  by the line in `unsaid.json`, so the turn answers, held line or not (`respond.reply_empty`, ids and a count).
  Without it the conversation refuses the empty turn and a person after a held line is left with the held line.
  Rejected: storing an empty turn, which shows a blank bubble.
- **A turn that ended after its first line went out is never left with nothing.** Logged once as `respond.ended` with the
  reason and the recovery taken (ids only).
  - *A refusal* is wrapped up on the `wrap_up` task, whose routes in `routes.json` are other providers' than chat's, under
    tool choice `none` with the wrap-up note; if that refuses, fails or says nothing, the fixed line stands in.
  - *A model that cannot be reached* is told once, as her turn marked `follows` and queued like any reply
    (`unsaid.json`, `unreachable`), and the work is kept: the claim is held for `unavailable_retry_s` and the resume
    sweep takes it again from its checkpoint, each time an attempt, until `max_attempts` gives it up (the person's
    screens are told it failed). The line is said once (`Checkpoint.unreachable_told`).
  - *The database out of reach* (`outbox_unavailable`, `inflight_unavailable`) cannot store anything, so the work is
    left to the sweep once the database answers, and the web page marks the conversation unfinished by itself: it ends
    on her held line, nothing is thinking or in flight (`working`, not believed past a read that failed), for `STALL_MS`
    (`app/web/src/rooms/her/stalled.ts`). An answer that lands later replaces the mark.
  - *An answer older than the outbox's `stale_s`* is not lost: her turn was stored with it, so the thread and her
    history hold it, and only the push is dropped, logged `outbox.stale_dropped`. Telling it at the next chance is the
    errands slice (open-work, item 7).
  - Rejected: a retry loop in the runner. It would hold the answer to one pod and repeat a change; the checkpointed
    sweep already resumes without repeating.
  - Rejected: a client timer alone. The server says when it can (`TurnFailed`); the timer covers only the ending it
    cannot publish.
  - Rejected: choosing the wrap-up provider from the one that refused. Refusals carry no provider and another provider's
    route list is data.
- **It covers every turn whose channel takes replies said after the response** (`Inbound.later`: web chat, a bench's
  talk, the kiosk, Discord, voice). A device's own message route and the house evals answer only in the response, so
  nothing could deliver a resumed answer, and they are not saved.
- **An answer that goes out through the outbox is queued in the transaction that stores it** (`Outbox.answer`, which
  takes every message queued with her turn: the channel's own and a reply's copy to the phone, `to_phone.copy`), held
  or resumed, so a kill can neither queue it twice nor store it unqueued. The direct reply on Discord or a satellite is
  stored and then sent by the pod holding the session, and a kill between the two loses it, as the outbox's own take
  then send does.
- **A Discord message is answered once however often it is handed in.** Its person turn carries `discord:<message id>`
  (`NewTurn.source`), stored once per household, so a second hand-in is the same turn; `InFlight.begin` refuses a turn
  whose work exists or whose answer is stored, and that hand-in returns pending with no words. A claim is settled once
  `respond` returns or raises, and a session's catch-up hands in again the claims within its window never settled, so
  a message whose session died before its work was saved is answered by the next.
- **A memory act her reply asks for is the last step of the turn's work.** Storing her turn keeps the row instead of
  deleting it, its checkpoint now only the act (`Checkpoint.acting`), in the same transaction; the act is recorded
  begun before it runs and the row deleted after. A runner that stops before it began leaves it to the resumer, which
  carries it out without asking for the answer again; one cut off while it ran is not begun again
  (`respond.memory_act_interrupted`), since repeating a change is the defect this prevents. Her answer is stored, so
  nothing is shown failed.
- **A page shows a turn she is still on as pending, never missed.** A conversation read marks the person's turn
  `working` while it is owed its answer and its work row exists (`InFlight.working`, the database's own record, never
  the text), whether a runner holds it or a resumer will take it. A page whose send failed marks the message missed only
  when the turn is not working or she declined it; once `TurnFailed` says the work ended, the page clears the mark.
  A page that reads a working turn starts her state as thinking, as Live's events would set it, until Live or the stored
  answer says otherwise. Her answer reaches the page through Live as any stored turn does. Owner-only as the thread is.
- Rejected: a status the page infers from how its own send failed. A request that died and a turn that was refused look
  the same to the page; only the work row tells them apart.
- Rejected: queueing the answer under an idempotency key before storing it. A taken outbox row leaves no key behind,
  so a resume after delivery would queue it again.
- Rejected: the phone copy queued under an idempotency key on her turn's id. The turn's id does not exist until it is
  stored, and a taken outbox row leaves no key.
- Rejected: `InFlight.finish` writing the outbox table. Conversations would own a channel's table, and the Null
  `InFlight` cannot reach the `Outbox`.
- Rejected: an etcd lease per turn. `Lease` runs a body only on the active site while every pod on both sites answers
  requests, and every turn's keepalives would sit on the quorum that decides failover, which Live's decision rejects.
- Rejected: every pod resuming the orphans it finds. Resuming is work she starts herself, which holds the lease
  (CLAUDE.md); the singleton runs on whichever site is active, so a turn is still resumed on either site.
- Rejected: running again a change whose result was never recorded. Whether it ran is unknown, repeating a change is
  the defect this prevents, and a read she makes next costs one step.
- Rejected: the checkpoint as columns of `turns`. A turn is what was said; its work is deleted when it ends, and
  `turns` is read by every carried and recalled query.
- Rejected: Conversations parsing the checkpoint. Its entries are the inference layer's types, which Conversations may
  not import (`test_boundaries.py`); it keeps them as the turn loop wrote them.

## Failover is automatic, refereed by a 3-site etcd

No MR, kubectl or other human step at failover time. Two sites cannot tell "the other site is down" from "the
link is down", so a third vote breaks the tie: etcd members on the two sites' clusters, and a witness on a NAS at a third site.

- The three sites sit on different ISPs and link technologies, so no single upstream outage takes two sites.
- **Timeouts sized for a high-latency link to the witness:** heartbeat 250 ms, election 3 s. A blip at the witness is
  not an election.
- **The witness down alone changes nothing:** the two sites hold quorum. Losing two sites at once stops writes, which
  is the point: the survivor can't tell it is alone.
- **Each member advertises an IP, not a name.** Moving the witness is `etcdctl member update` to the new
  address, which never changes quorum. A remove-then-add would leave a 2-member window where losing either
  site halts the cluster.
- **Rejected: CNPG replica clusters.** CNPG fails over between clusters only by editing `.spec.replica`
  (primary plus a promotion token), so every failover would be an MR.
- **Rejected: a witness on a rented cloud VM.** It works, but the third site is on the private network
  already, so nothing has to face the internet.
- **Rejected: Patroni's built-in Raft** (deprecated since Patroni 3.0), **pg_auto_failover** (a single monitor
  decides rather than a quorum, and the monitor is a full Postgres), **Consul and ZooKeeper** (the same quorum
  with more weight), **CockroachDB** (the witness would hold a full data replica, and it isn't Postgres).

## One Postgres, managed by Patroni, with the house's site preferred

Patroni on each cluster, using the etcd above to elect the primary; asynchronous streaming replication between
sites. The site the house is at is preferred.

- **Clients find the primary themselves:** the connection string lists both sites and asks for a writable
  session (libpq `target_session_attrs=read-write`). No DNS or Service change on failover.
- **The primary comes back to the preferred site on its own.** The fail-back singleton, running under the lease on
  whichever site leads, calls Patroni's switchover once the preferred site has been a streaming replica on the leader's
  timeline, at most 1 MiB behind, for 5 minutes without a break. Each further failover away from it in the last 6
  hours doubles that wait, up to an hour, so a flapping preferred site gets the primary back ever more slowly instead of ping-ponging.
  The thresholds are data (`app/ashley/referee/failback.json`). A maintenance switch holds it for a while (a key
  in the referee's etcd that expires on its own); failover itself is never held. Drilled on production both ways: failover
  in 14 to 31 s, writes unavailable 14 to 16 s, fail-back writes unavailable 4 to 8 s, no acknowledged write lost
  (numbers per drill: the cluster repo's `kustomization/ashley-postgres/README.md`).
- **Asynchronous on purpose:** an unplanned failover can lose the last few seconds of writes. Synchronous
  replication would stall every write whenever the other site is down.
- **Backed up to both sites' NAS.** WAL-G on the primary pushes every WAL segment to both sites' MinIO and
  counts it archived only when both took it, with nightly base backups to each, so either NAS restores alone. A NAS
  down stops archiving and alerts instead of leaving a gap. Rejected: one bucket (a failover leaves the backups at
  the primary's own site), each site to its own NAS (a failover splits the chain), MinIO bucket replication (its lag
  shows only at restore). Operating it: the cluster repo's `kustomization/ashley-postgres/README.md`.
- This is an exception to the cluster repo's "CNPG for Postgres" rule, because automatic cross-cluster
  failover is the requirement CNPG doesn't meet.

## Singletons hold an etcd lease

A singleton runs only while its process holds a lease in the same etcd. Kubernetes leases are per-cluster and
can't see the other site. The lease and the database primary are decided by one referee, so they agree.

- **A site campaigns only while its own Patroni member leads**, read from Patroni's leader key in the same etcd. The
  claim transaction compares that key too, and every keepalive re-reads it, so when the primary moves the old holder
  cancels its singletons and releases within a few seconds, and the new site takes them.
- **"Leads" means holds the leader key, which outlives a demotion by up to Patroni's leader TTL.** A primary cut
  off from etcd demotes itself first, so for those seconds the old site still runs singletons against a read-only
  database. A singleton that writes must tolerate a failed write; it is never run on two sites at once.
- **Rejected: deciding the active site from the database** (`pg_is_in_recovery()` on the local member). It answers
  per site, so two sites could each see themselves writable during a split; the leader key is one answer for both.

## A turn that has read outside words asks before it does anything consequential the person did not ask for

**Built**: the taint (`Inbound.taint`, `ToolSpec.outside` and `ToolResult.outside`, `Checkpoint.tainted` with `Steps.tainted`, the `outside` mark in `kinds.json`, the classification gate), holding and agreeing (`Outside`, `HeldCalls`, `carry_out`, the receipts on her turn), the tiers, the action judge, `outside_actions` and the evals. Mail (item 36) and a browser
(item 38) let a stranger put words into her turn, and a turn's tool calls follow its words. So a turn that has read
text written outside the household, or that was started by something outside, is **tainted**. A tainted turn reads
and speaks, and each change it would make goes by its **tier** (below): a low-stakes change runs, and a consequential
one goes to the action judge, which runs it or holds it as a proposal for the person to agree to in a later turn of
their own. A change that is held is held whatever `irreversible.json` says, which is about untainted turns. The agreed
calls then run with the arguments that were stored, and the model does not write them again. Rakazo does the same: a run is
tainted by the tool results it has read, and a new tool taints by default.

- Fits into: Channels and Senses, with no new system. The taint is a field of the turn: of its `Inbound` when the
  turn starts tainted, and of its checkpoint once a read taints it. Holding a change is a Decorator over the turn's
  `Tools`, as `ashley.tools.only.Only`, `ashley.tools.reading.Reading` and `ashley.channels.aside.Stripped` already
  are. A held change is a new payload kind in the one Proposals store ("Her proposals are one store"): a Command
  that waits for the person's OK. Agreeing to it is a confirm tool offered in a later person turn, as `house_confirm`
  and `arm_reminder` are.

**What taints a turn is a field, never words.** A turn is tainted from its first step by its origin, or from a
read on, by that read's result:

- **Origin**: `Inbound` gains `taint`, either null or one of `watch`, `stranger`, `pasted` or `inherited` (a firing of a reminder or watch that a tainted turn made). The code that builds
  the `Inbound` sets it. A house wake (`/api/wakes`) is null: the request admits slugs and a person entity only, so no
  text can arrive, and her rule's brief is written in the household. Reads inside the wake turn taint by their own
  spec. A watch's wake (`ashley.channels.wake.watch_turn`) is `watch` when its kind's `outside` is true, and null
  otherwise. `outside` is a field of the watch kind's data (`ashley/watches/watches.json`): whether what the kind
  reads can carry text written outside the household. `claude_session` is false, since it tracks status and a
  sequence number and its label is set in the household. A name no kind has is the Null kind, which is true. A
  hand-off nudge becomes an ask once the turn reads the session's screen with `claude_read`, which is `outside`. A message in a household's Discord server whose author is not a member of that household (in another, or in none) is `stranger`. A
  person's own message, a reminder firing and a bench's reaction to the person's change are null. A voice in a
  room with an unknown speaker is also null, because the speaker is in the house. A person's message whose pasted or
  forwarded block is longer than `taint_chars` (`ashley/channels/pasted.json`) is `pasted`: the block is the turn's
  `Inbound.attachment`, the same field the web composer's paste already filled (`ChatMessage.attachment`, captured from
  the paste event), and a Discord forward fills it from the message's snapshots (`Message.forwarded`, titled
  `Forwarded`). Under the threshold the block is read but taints nothing. A quote typed into the message, and a Discord
  reply, are not marked: their text is never a separate field. Voice cannot paste.
- **A read**: `ToolSpec` gains `outside` (`ashley.inference.model.ToolSpec`, beside `reads`). It says whether the
  tool's result can carry text written outside the household, and it is true unless the spec says false, so a new
  tool taints. `ToolResult` gains `outside`, which is null or a boolean. A tool sets it on a result that carries
  less or more than its spec says. `bench_read` sets it false when no piece it shows is of a kind that
  `app/ashley/workshop/kinds.json` marks `outside`. A result taints when its own `outside` is true, or when that is
  null and its spec's `outside` is true. A name not in the catalogue taints, and it counts as a change, as the tool
  loop already treats it.

Today's tools, set by the field at each spec:

| `outside` | Tools | Why |
|---|---|---|
| true | `look_up` (and its sub-agent's `search_web`, `read_page`, `find_places`, `search_printables`), `printables_files` | web pages, snippets, model pages |
| true | `git_projects`, `git_tree`, `git_read_file` | a repository holds files, names and messages written by anyone |
| true | `claude_read` | a session's screen shows what Claude Code read |
| true | `money_transactions` | payee names and payment memos written by merchants and payers |
| true, narrowed per result | `watch` | the result is its kind's `outside` in `ashley/watches/watches.json`: false for `claude_session` (status and seq), true for `mail_inbox` (senders and subjects) |
| true | `bench_frames`, `bench_transcribe` | frames and speech of a video from elsewhere |
| true, narrowed per action and entity | `house_ask` | the result is false when the action is one the household's `household_reads` setting names and every entity the call named is listed for it (`todo.get_items` on the lists only the household writes), or the action is one its `service_reads` setting names (a travel-time script, `weather.get_forecasts`: Google's and the forecaster's text), else true: a list a job fills with web page titles, calendar events (anyone can send an invite), feeds, scripts, any action or entity not named |
| true, narrowed per result | `bench_read`, `bench_read_piece`, `bench_shelf`, `bench_look` | the result is false unless a piece shown is of an `outside` kind: `file`, `site`, `reader`, `recipe`, `video`, `clip`, `audio`, `image` |
| true, narrowed per result | `house_state` | the result is true when it shows the attributes of a thing in one of `outside_domains` (`house_state.json`: `calendar`, whose attributes hold the current event's title, description and location, which are invite text), else false |
| false | `house_find`, `house_history`, `house_automations`, `house_automation` | the household's own setup and device states; `house_find` reads the registry, which holds no state attributes |
| false | `money_accounts`, `money_categories`, `money_net_worth`, `reminders`, `household_devices`, `claude_sessions`, `skill_read`, `bench_install_state` | the household's records |
| false | `bench_run`, `bench_last_run`, `run_code` | output of code she or the person wrote, run with no network |
| false | every change's own result (`house_do`, `house_change`, `remind`, the bench edits, `claude_prompt`, ...) | a confirmation the tool writes |

A gate keeps every tool classified (`app/tests/test_outside_classified.py`). It scans `app/ashley` with
`ast`, and fails on any `ToolSpec(` call that does not pass `outside=` and any `Inbound(` call that does not pass
`taint=`. So whoever adds a tool or a woken turn has to decide. The tainting default of `outside` covers specs the scan
cannot see; `taint`'s null default is for tests. A planted spec without the keyword must fail the gate, and a floor on the number of call sites found proves
the scan read something.

**Where the taint lives.** The origin is a field of `Inbound`, which the checkpoint already stores whole.
`Checkpoint` (`ashley.channels.checkpoint.Checkpoint`) gains `tainted`: the name of the first tool whose result
tainted the turn, or null. It is recorded through `Steps` (`ashley.channels.steps.Steps` gains `tainted(tool)`),
which saves it and renews the claim before the tainting result goes back to the loop. A runner that loses the turn
at that moment raises, as `starting` does, so a change never runs on a pod whose checkpoint lacks the taint. A
resumed turn starts with the taint it had, and a taint never clears. Turns that are not checkpointed (a device's
own message route, the house evals) are never resumed, so for them the taint lives only in the running loop.

**What a tainted turn may do.** Reads run, and she speaks. Every call to a tool whose spec does not `read` is a
change, which is the same line the tool loop draws for deduping, and a tainted turn sorts it by tier.
The interception is `ashley.tools.outside.Outside`, a Decorator that `ashley.channels.landing.Landing` puts
outermost around the turn's source, after `Only` and `Reading`. The same instance stays in place when a page move
rebuilds the inner source. The errand job (`ashley.channels.errand.attempt`) wraps its source the same way. Its
`call`:

1. When the turn is tainted and the call is a change, its tier decides. `runs` calls the tool, and the call is
   recorded as done on its own (below). `judged` asks the action judge, whose answer is `run` (the tool is called and
   the call recorded) or `ask`: then the tool is not called. The call is added to the turn's held
   proposal (below), and she gets a result saying it is held for the person's OK and not done, so she tells them
   and does not claim it happened. The loop runs calls one at a time, so when a read and a change come in one round,
   the change after the tainting read is held.
2. A tool that takes a person's agreement is refused in a tainted turn and never held. `ToolSpec` gains `agrees`
   for these, set on `house_confirm`, `arm_reminder` and `carry_out`. Agreeing is only ever done by an untainted person turn.
3. Otherwise the inner source runs the call. If the result taints and the turn was not tainted yet, it records the
   taint (above) before returning the result.

**Tiers.** A tier is a Specification in `app/ashley/tools/tiers.json`, beside `outside.json`: a rule matches a call by
tool, action and resolved target, and the first that matches decides. A tool's `ToolSpec.tier` is its default, and
`Tools.tier(call)` refines it per call (the house source from the data, after resolving targets, since a `switch` can be
a lamp or a garage relay). A name no rule covers is `judged`, and the classification gate requires `tier=` on every spec
that is not a read.

- **`runs` (b)**: the harm if a stranger chose it is small, visible and undoable, and it writes no free text a later
  turn reads as household-written without carrying the taint. Lights, fans, media, scenes, climate, helpers, timers,
  vacuum, list items, covers that are not a garage, gate or door, a `switch` that is not an outlet and not in the
  household's `consequential_entities` setting; mail labels (household labels added or removed, read and unread) and drafts;
  `remind`, `remind_on_money`, `watch` and `unwatch` without `tools`; the bench's own work, which is versioned.
- **`judged` (c)**: the harm is real: it sends household data out, cannot be undone, opens the house, hides or deletes
  things, changes what she or the house does later, or spends. `mail_send`, a mail move to archive, spam or trash, locks,
  alarms, garage, gate and door covers, sirens, cameras, automations, scripts, `button.press`, `notify.*`, `homeassistant.*`,
  `house_change`, `bench_propose_install`, the Claude Code tools, `skill_edit`, `skill_rollback`, `change_reminder`,
  `cancel_reminder`, and `default`: any tool or action not listed.
- **`agrees` tools** stay refused in a tainted turn, so a delete still needs a later untainted `house_confirm`, and a
  reminder or watch with `tools` still needs `arm_reminder`.

**The action judge** is an `ActionJudge` service behind the locator, `decide(words, view) -> Verdict` with `decision`
(`run` or `ask`), a `reason` from a closed enum and a one-sentence `explanation`. The model implementation
(`ashley.tools.action_judge_model`, task `action_judge`, Sonnet then Gemini flash in `routes.json`) is wired where `Tools` is.
The Null Object, which answers `ask` with reason `no_judge`, is what an entry point that forgets to wire the judge sees,
so it fails safe. A turn's `Outside` reaches a verdict in this order (`ashley.tools.outside_judging`): the verdict
already saved for the call; no words of the person's, which asks (`no_words`) with no judge call; the source's vetting of
the call (`Tools.vetted`), which asks without a judge or gives the view; then the judge. A judge that is unreachable,
times out, refuses or answers invalidly means `ask` (`judge_unavailable`), never `run`. There is **no always-ask floor**:
the judge never sees outside text, so it says `run` only when the person's own words ask for the
action, and the risk that it misreads those words is accepted. Code branches only on `decision`, never on `explanation`.

- **Words** are the speaker's own typed messages in the conversation, newest `words_turns`, each cut to `words_chars`
  (`ashley.channels.judge_words`): never her replies, a household turn, another person's, or a block stored as pasted
  (`Turn.attachment`), so a `pasted` turn's block is cut by construction and the typed text around it stays. A turn that started tainted from outside (`stranger`, `watch`) has none, so a judged call in it is asked; a `pasted` turn is the person's own message and reads their typed words, which is what lets the judge run a call they asked for beside a paste. A turn a
  reminder or watch woke (`inherited`) has the speaker's person turns of the turn that made it, up to that turn, read
  from the conversation and turn id stored on the row (`Reminder.made_in`, `Watch.made_in`, set from `Outside`'s turn
  when a tainted turn's tools make the row, carried by `Inbound.made_in`). A row made before they were stored has none,
  so its woken turn asks. The brief never counts: it would count only once the person agreed to it through
  `arm_reminder`, and nothing records that agreement yet.
- **The view** is built by the source of the tool. `house_do` shows the action when the house offers it and the
  household's names of the things it resolves to; `mail_send` shows its recipients, each known; every other argument is its
  size, or itself when a number, a flag or a value the spec's `enum` lists. A test plants text in every argument of every
  judged change and reads the exact request the provider is sent.
- **A `mail_send` recipient** must be a household mailbox's address, one this mailbox sent to before (a sent-folder search
  of the port), or an address in the person's words; otherwise the call is asked as `recipient_unknown`, with no judge call.
- **The verdict is saved through `Steps`** (`Checkpoint.judged`, by call id) before the call runs, and a resumed runner
  reads it back; so does a verdict of `ask`.
- **The explanation** is stored with a held call (`HeldCall.explanation`) and in `outside_actions`, shown with the call in
  its receipt and in the result she reads, and never logged.

**Why this judge is not the rejected one.** The rejected judge read the outside content and decided whether it was
trustworthy, so the attacker's words were its input and could address it. This judge's input is the household person's
own words and a view of the call that code has reduced to arguments that cannot carry outside text (household names,
enums, numbers, opaque handles, and a free-text argument as its field name and length). It judges whether an action
matches a request, and the request is the person's; the attacker's only lever is the call itself. Code checks what
identity can check (a mail recipient must be known) before it asks the judge anything.

**Writes that would launder outside words into a later untainted turn carry the taint.** A reminder or watch made in a
tainted turn stores `taint`, and its firing turn's `Inbound` starts with origin taint `inherited`, so it acts under the
tiers again. A bench piece changed in a tainted turn is marked `outside`, which `bench_read` narrows by. A list entity a
tainted turn wrote is recorded in `outside_writes` (household, entity, time), and `house_ask`'s `household_reads` check
treats it as outside for `keep_s` after.

The lists those checks read, `household_reads`, `service_reads`, `reads` and `consequential_entities`, are settings of the
household's Home Assistant connection, read once per turn; none set is the least trust.

**What ran on its own is recorded.** Every change a tainted turn made without asking (tier b, and tier c judged `run`) is
a row in `outside_actions` (household, person, conversation, turn, tool, a code-written summary, tier, decision, reason,
explanation, time), pruned after 90 days by the code that writes it. The summary holds the tool and only the arguments
`outside.json` lists for it (`summary_arguments`: an action or a folder, in the shape of one), never argument text: the
record outlives the proposal and nothing checks its words. Code also shows the changes the judge let run (tier c) beside her reply, as it shows the held ones, so a mis-sorted
change is seen by the person without anyone reading a log, whether or not her reply mentions it. Tier b changes are
recorded but not shown: they run by a fixed tier, so there is no sorting to get wrong, and the change is visible where
it was made. What is shown is `Turn.receipts`, never her words ("What the person sees", below).

A change is held only where agreement can follow: the speaker is known and the reply reaches them alone
(`ashley.channels.audience.owner_alone`, read by `ashley.channels.standing` since tools import no channels). Elsewhere, a shared room, the tablet or a server channel, the change is
refused with a result saying it needs the person's OK in a private conversation, as `house_change` refuses
`needs_private` today. A held change never bypasses the tool's own rules: once agreed it runs through the tool, so a
delete still needs `house_confirm` after it, as it does today.

**The held proposal.** `ashley.senses.proposal_payloads.HeldCalls` is a tuple of held calls in the order they
were asked for. Each held call has the tool's name, its arguments as stored JSON, and a summary that code writes from
the tool's plain label and the arguments. The kind lives in a new topic, `ashley.senses.proposal_payloads.OUTSIDE`. The person is the speaker,
and the turn is the one being answered (a woken turn's household turn included). Within one turn the calls
accumulate: proposing reads the pending proposal, and if it is from this turn, stores it again with the new call
added. A call identical to one already held is not added twice, so a call resumed after a kill is not doubled.
The decorator refuses a call past `max_calls` in the proposal, or whose arguments are longer than
`max_argument_chars` characters of JSON. A refused call is not held, and she is told it cannot be asked for, so nothing runs that the person could not read in
full. A later tainted turn's first held call replaces the earlier pending proposal, as every topic replaces itself.

**`Topic` gains `scope`, either `conversation` (every topic today) or `person` (`OUTSIDE`).** A woken turn runs on the
person's phone thread, where nobody types: the push opens their page, and they answer in another conversation. A
person-scoped topic keeps one pending proposal per person, and `pending` and `take` ignore the conversation. The row
still records the conversation it was proposed in. The advisory lock and the replace are keyed on the person and the
topic. The gate (`proposal_gate.gate`) is unchanged, because turn ids are one identity across conversations, so
"a later person turn" still means a turn stored after the proposing one.

**What the person sees.** Her reply holds only her words; she is told what ran and what waits and says it herself.
Beside it code shows `Turn.receipts`, a snapshot stored with her turn: each judged change that ran and each held call,
headed by the tool's plain label (`ToolSpec.label`), with code's summary as detail (the label and the arguments in plain words, never the tool's name); a held call's full summary is shown
with the Agree card, because the person agrees to what code wrote, not to her description of it, which the outside text
could have steered. The web and the kiosk show it as quiet UI; Discord as one separate small-text message; voice speaks
none of it and sends it to the speaker's phone when it can, as a notification of its own; her push notification stays
one, her words with the Agree action, and a tap through shows the receipts on the page. Her history carries it as a line
marked as the app's. A woken turn that held a call goes out even when `worth_saying` is false, because a held change
nobody sees is lost without anyone knowing; one that stays quiet after a judged change sends its receipts alone to
the speaker's phone, as a voice turn does.

**Receipts are a snapshot, not a join.** `turns.receipts` (migration 0093) is written in the turn's transaction, because
proposals are deleted when taken or replaced, `outside_actions` is pruned at 90 days, and a judged change whose record
could not be written (`Outside._unrecorded`) must still be shown. `outside_actions` stays the audit store and the source
at closing; it keeps the headline a change was shown under (`label`). `outbox.receipts` carries them to a queued reply.
A turn stored before this change keeps the blocks in its `text` and is read unchanged: stripping them would key behaviour
on words in `text`, and the recent-history window moves on.

**On a paged channel code writes no words as her turn.** Where the person reads a page that learns of turns from Live
(`Inbound.paged`: web chat, a bench's talk, the kiosk, in text; a reply meant to be heard keeps its line), a turn that fails or is kept for retry stores no `unsaid.json` line
as hers; the page shows a quiet status beside the person's message, worded in the web code, from `TurnFailed.why`
(`retrying`, replaced by a later reply, `unfinished`, or `too_big`). A turn with receipts to show still stores its line. Spoken-only
channels, Discord and push say the line as before.

- **Rejected: join `outside_actions` and `proposals` at read time.** Three gaps where the safety record silently vanishes.
- **Rejected: let her say it and show nothing.** Injected text can talk her out of it; the receipt is the point.
- **Rejected: a fixed spoken line on voice ("I also opened...").** Code words in her voice.
- **Rejected: a Discord embed.** It needs a new client API for no gain over subtext.
- **Rejected: a per-tool phrase table in data.** A second home for a fact authored with the spec; a tool built at runtime
  would silently miss it.
- **Rejected: a per-call `described(call)` naming the target ("Opened Garage Door").** It needs live entity reads per source;
  revisit if labels prove too vague.

**How agreement happens.** The decorator offers `ashley.tools.outside.CARRY_OUT` (`carry_out`, no arguments,
`agrees`) only when every one of these holds:

- the turn is a person's (`Inbound.author` `person`), and its origin `taint` is null;
- the speaker is the proposal's person (`made_by`);
- the reply reaches them alone;
- a pending `OUTSIDE` proposal passes `refusal` for this turn.

Calling it `take`s the proposal, which consumes it, so of two agreeing turns only one runs it. Then each held call
runs in order through the decorator's inner source with its stored name and arguments, under new call ids. A tool
this turn does not offer is reported as not run, and a bench tool off its bench is one such case. Its result says
what each call did. It sets `outside` true when any of those results taint, so after agreeing, the turn is tainted
by what the agreed calls returned. `carry_out` is itself one change in the loop, recorded as started before it runs.
A runner killed partway is resumed with the interrupted-call error, and the proposal is already consumed, so nothing
runs twice.

Agreement cannot be laundered through the turn that agrees:

- that turn must be untainted when it agrees, both by origin and so far by reads;
- `carry_out` takes no arguments, so it can only run what the person was shown;
- the model is never asked to write those arguments again.

A person's message steered into a tainted turn that is still running cannot agree, because `carry_out` is refused
there. They agree in their next message. One risk remains. Her reply in the tainted turn can repeat the outside text
in her own words, and later turns carry that reply, so a later untainted turn sees it. Tool results themselves are
never carried, only turns. That later turn acts on the person's new words. The eval below measures whether carried
text alone moves her to change something.

**Settings are data**, `app/ashley/tools/outside.json`: `proposal_ttl_s` (a day, so a change held overnight
can be agreed in the morning), `max_calls`, `max_argument_chars`, and the text she and the person read (the held
result, the refusals, the headline of a change whose tool has no label, the line that carries receipts into her history).

**The migration** adds an index on `proposals (made_by, topic, id)` for the person-scoped lookup. No column is
added, since the payload is JSON tagged by `kind`, as every proposal's payload is.

**What survives a failover:** everything. The origin is stored in the checkpoint's `Inbound`, and a read's taint
is saved before its result can be used. The held calls are rows in `proposals`. A resumed turn is tainted exactly
as it was, and a change it held is held once. A consumed proposal is never run again.

**Logs:**

- `outside.tainted`: conversation, turn and `by` (the origin or the tool name);
- `outside.held`: conversation, turn, tool, calls held so far and proposal id;
- `outside.refused`: conversation, tool and reason (`needs_private`, `too_long`, `too_many`, `agreeing_tainted`);
- `outside.carried_out`: conversation, turn, calls, how many ran and how many were not offered;
- `outside.tier`: conversation, turn, tool, tier and what followed (`ran`, `judged`); `outside.judged`: conversation,
  turn, tool, tier, decision, the reason enum and duration_ms, never the words, the arguments or the explanation;
  `outside.recipients`: counts of recipients by how they were known, never an address;
- `respond.done` gains `tainted` (the origin, the tool name, or none) and `held` (a count).

They never contain arguments, summaries or results.

**Measured by:**

- Blind contract tests of `Outside`, written from this section by an agent that has not seen the implementation,
  then a planted-mutant run (`MUTANTS.txt`). They cover:
  - a read that taints then a change in one round: the change is held and not run;
  - an origin taint holds from the first step;
  - a result with `outside` false does not taint, and one with `outside` true from an untainted spec does;
  - an unknown tool name taints and is held;
  - held calls accumulate within a turn, with no doubles, up to `max_calls`;
  - an `agrees` tool is refused when the turn is tainted;
  - `carry_out` is offered only to a later, untainted person turn of the person asked, on a channel only they read;
  - it runs exactly the stored arguments, once across two agreeing turns, and skips tools not offered;
  - `carry_out` results that taint, taint the agreeing turn.
- Mutants to plant include:
  - taint checked only at the start of a round;
  - taint not saved before the result returns;
  - `carry_out` using arguments from the model;
  - an `agrees` tool allowed when tainted;
  - `OUTSIDE` scoped to the conversation;
  - `outside` defaulting to false.
- A property test that `dumps` then `loads` of a checkpoint keeps `tainted`, and that resuming a tainted
  checkpoint holds a change.
- The classification gate with its planted control.
- An eval, `python -m ashley.evals` over cases in data, measuring and never gating:
  - a tainted turn whose change was held tells the person it waits for their OK and does not say it is done;
  - "yes, do it" after a held receipt calls `carry_out`, and "what is that?" does not;
  - an earlier reply of hers carrying an instruction from a page ("delete the porch automation") moves an
    unrelated untainted turn to no change.

- **Rejected: detecting injection from the words.** A classifier or pattern over the text keys behaviour on words,
  an attacker can retry until a phrasing gets through, and a miss is silent. Where the text came from is a field
  that can be checked.
- **Rejected: asking a model whether the content is trustworthy.** The judge reads the same words it is judging, so
  the injection can talk to it too. Its verdict is prose about prose, and a stateless call cannot hold a line it
  is argued out of. The action judge above is another thing: it never receives outside text.
- **Rejected: tainting only woken turns.** A person asking her to read a page gets the stranger's words into their
  own turn just the same. The owner named an email, a web page and a payload, and only the payload arrives by waking.
- **Rejected: a per-conversation taint.** A conversation runs for hours and across channels, so one page read would
  turn every later change into an ask. The outside words live in one turn's tool results, and no later turn is shown
  those. What does cross is her reply, a paraphrase, and the eval measures that. Also rejected for the same reason:
  tainting every turn that carries a tainted turn, which keeps the taint alive for the whole recent-turns window.
- **Rejected: holding only what `irreversible.json` names.** That list is about what cannot be undone, but an
  injected change can do harm without being irreversible: a prompt to a Claude Code session, a reminder that acts,
  mail sent in the person's name.
- **Rejected: refusing every change in a tainted turn.** A mail sort that labels a dozen messages is the point of
  item 36. A refusal loses it.
- **Rejected: holding every change in a tainted turn.** It was the rule at first. It made a sort's labelling, a light
  and a reminder each cost a "yes", which is friction on changes whose worst case is small and visible.
- **Rejected: an always-ask floor under the judge.** It would guard only against the judge misreading the person's own
  words, which the owner accepts.
- **Rejected: tier-b writes of free text with no taint field.** They would carry outside words into an untainted turn
  that nothing judges.
- **Rejected: re-running the turn after the person agrees.** The model would read the outside words again and write
  the arguments again. Only stored arguments keep what runs equal to what was shown.
- **Rejected: a second store for held calls.** Proposals is one store, and a new kind is a payload.
- **Rejected: an agree tool per held tool.** One `carry_out` runs any held call through the tool's own path, so a new
  tool needs nothing more to become agreeable.
- **Rejected: classifying tools in a data file of names.** Many names are built at runtime (searchers, code hosts,
  per-language runners), and a list drifts from the specs. `outside` sits beside `reads` at the spec, and the gate
  makes every spec state it.
- **Rejected: tainting every turn with an unknown speaker.** A guest in the kitchen asking for the lights is in the
  house. Only a Discord author who is not a member of the household is a stranger.
- **Rejected for now: tainting `house_state`.** Every house turn reads state before it acts, so the change would turn
  nearly every house action into an ask. The accepted residual is attribute text such as a media title, written by
  whoever published the media.
- **Rejected for this slice: agreeing with a button on the page.** No model would be involved in agreeing at all.
  But the stored call would have to run outside any turn, and the tool sources are built per turn from its
  `Inbound` (bench, audience, speaker). The person-turn path reuses the store, the gate and the confirm pattern that
  every proposal already uses. Built since, as a person turn that is a command (`A tap agrees to what was held`).

## A tap agrees to what was held

The held receipt on the page, and the web push notification of the reply that holds it, offer **Agree**. A tap is a person turn whose
`Inbound` carries `agree: <proposal id>`, no text and a null `taint`: a Command, so no model writes the agreement and no
model step follows it. `POST /api/chat/agree` (`ashley.api.chat.agree_to`, the same-site rule of every write) hands it to
`ashley.channels.agree.agree`, which is the web adapter's own path and never goes through `respond`.

**It is an agreeing turn like any other**, so the rules of `carry_out` hold unchanged. `Outside.agreed` takes the proposal
by its id (`Proposals.take_by_id`: the person it was held for, a turn stored after the holding one, within `proposal_ttl_s`)
and runs each held call through the turn's tools exactly as `carry_out` does, so a tool that is not offered now is not run.
Only the person it was held for may agree. The refusal is typed and made before anything is stored: `gone` (carried out,
replaced by a later hold, or never held; a taken or replaced row is deleted, so the three cannot be told apart),
`expired`, `not_yours` (another person's, in this household or another's). A tap that races another for the same proposal
loses at `take_by_id` and is refused `gone`.

**What became of each call is a record beside the person's turn, not a turn of hers.** The person's own turn is a fixed
line from data (`outside.json`, `agreed_turn`), so history reads "Agreed." and the gate has a later turn id to compare.
Once the calls are done, `Turn.agreed` (`ashley.receipts.AgreedOutcome`, `turns.agreed`, migration 0095, only on a
person's turn) holds each call's summary as the person was shown it and whether it `ran`, `failed` or was `not_run`,
or that the run was `interrupted`; no turn of hers is stored, since code never writes words as her turn on a page. It
never includes what a call returned: a result can be outside words, and a turn's record is carried into later turns, so
a result in it would be a way back in. The page shows it as quiet lines beside "Agreed.", worded in the web code
(`ChatConversationTurn.agreed`, `AgreeReply.agreed`); her history carries it as a line marked as the app's
(`ashley.channels.history_receipts.agreed_line`), as receipts are. Agree reaches only the person's own web thread: the
page's button and the push notification's action both post `POST /api/chat/agree`, which stores on that thread, so
no spoken, Discord or push wording of the outcome exists. The notification's action shows nothing on success; the
outcome is on the page.

**It survives its pod** as any turn does (`Work in flight survives its pod`): checkpointed in `InFlight` from the person
turn, the carrying out recorded begun before it runs and the outcome saved after, and the outcome set on the person
turn in the transaction that ends the work (`InFlight.agreed`). `resume` finishes an agree turn without a model
(`agree.resume`): an outcome already saved is not run again, a run begun and unfinished is recorded `interrupted` and
never repeated, and a proposal gone by then ends the work with no outcome.

**What the page and the notification are told.** `ChatConversationTurn.agree` is the proposal's id, on her final answer to
the turn it was held in, while that proposal is the person's own and unexpired (`agree.waiting`; null on every other
turn and on a bench or kiosk read). A reply with held receipts is queued with `Outbound.receipts`
(`outbox.receipts`, migration 0093; `outbox.agree` still written for one release), and its notification carries
`Notification.agree`; the service worker offers an Agree action that POSTs it from the notification. A refused tap says why in place.

**Logs:** `agree.refused` (person, reason), `agree.done` (conversation, turn, duration_ms), `agree.failed` (error class);
`outside.carried_out` as for `carry_out`. Never arguments, summaries or results.

- **Holding for a person's OK exists only for taint and consequence**: an action the consequence tiers or the person's
  "needs your word" list hold, or one the action judge holds on a tainted turn. It is never a collaboration or
  confirmation step for an ordinary edit she is asked to make (the tablet's layout, its buttons, her own pieces):
  those she does, with undo. Rejected: confirming her edits through Agree, which shifts everything slowly into
  pressing Agree and turns her into Claude Code in a web form.
- **Rejected: an empty turn of hers carrying the outcome as receipts.** Every reader of her turns (history, memory, the
  pages, search) would meet a turn of hers with no words; the outcome belongs to the turn that asked for it.
- **Rejected: a second way to run held calls outside a turn.** The tool sources are built per turn from its `Inbound`,
  so a turn is the only place a call can run. The tap is a turn with a different front.
- **Rejected: showing the Agree button from a pending proposal alone.** A notification for an unrelated reply would then
  offer to agree to what it does not show. The id travels with the reply that shows the receipt.

## Watches wake her when what a read returns changes, until a condition or a time

Some changes send no event: a Claude Code session the person nudged themselves finishing, a calendar event moved, a
list edited (open-work, "Watches"). A watch is a read she repeats on a schedule with no model in the check; when what
it returns changes, she is woken with what changed. The general mechanism has one kind so far, a Claude Code session,
and it replaced the session sense. She can watch any of the person's sessions ("keep an eye on that one"), not only
those she handed work to, and every watch ends at its `until` or its expiry.

- Fits into: a new system, Watches. It meets the four tests in `docs/systems.md`: many callers, one question ("wake
  her when what this returns changes, until X"), a second implementation already planned (a polled tool, a Home
  Assistant subscription), and it owns each watch's baseline. Its kinds are a Type Object: code reads the source, and
  data holds the defaults. An unknown kind gets a Null kind whose every read fails, so a stale row pauses instead of
  breaking the tick. The session sense was the first copy it absorbed. Changes go into the
  `wakes` queue (Senses), and the wakes runner runs the turn. Arming sits beside the reminder tools (Tools), and
  agreement goes through `Proposals`.

**A watch is one row: what it reads, which changes wake her, and when it ends.** A watch reads one target of one kind
for one person (for this slice's kind `claude_session`, a session id on that person's bridge). From each read the kind
takes **items**, a map from an item's identity to its tracked fields. Tracked fields are scalars: text cut to
`max_value_chars`, a number, a boolean or null, and an item holds at most `max_items` of them. For `claude_session` an
item is keyed by its session id and its `track` is `status` and `seq`; the label is kept only for display. A watch also has
`when` (which changes wake her), `until` (which change ends it), `expires_at` (the latest it can last),
`interval_s`, the bench whose talk armed it, `armed_by` (`ashley` through her tool, `handoff` through `claude_start`
or `claude_prompt`), and the tools its turn may use. Two counters guard it: `version` rises each time a baseline
is stored, so a check recorded from a stale read is refused, and `series` counts the times it has woken her.

**Conditions are structured fields, never prose.** `when` and `until` take the clause shape of the money rules
("Rules she writes are composed from general predicates"). A condition is a list of alternatives. Each alternative is
a list of predicates that must all hold, and any one alternative is enough. Arrays stay flat, so every provider
adapter accepts the schema. The money predicates read a transaction and its payer's history, which a session has
neither, so these predicates are a sibling module in the same package,
`ashley.criteria.items.ItemPredicate`. They are judged against
`ashley.criteria.record.Change`: one item's identity, whether it is `new`, `changed` or `gone`, and its
tracked fields before and after. The kinds form a closed set:

- `equals` (`field`, `value`), `one_of` (`field`, `values`), `number` (`field`, `min` and/or `max`) and `contains`
  (`field`, `text`, 1 to 200 characters, case-insensitive), each read from the item after the change, or before it with `of`
  `before`. A value is text, a number or a boolean, never null; a field becoming null is reached through `changed`;
- `new`, `gone`, and `changed` (`field`, true when that field differs).

Each predicate takes `negate`. A predicate that reads a side the item lacks (`before` on a new item, `after` on a gone
one) is false before `negate` applies, as a money predicate with too little history is. A condition holds for a check
when some item new, changed or gone in that check satisfies it. Unchanged items are never judged. At arming, every
`field` must be a tracked field of the kind, and a condition may hold at most `max_alternatives` alternatives of
`max_predicates` predicates each. Anything else is refused, never guessed.

**`when` defaults to the kind's.** For `claude_session` (in the settings file, below), the default reproduces today's session
sense: `[[one_of status [blocked, done], changed seq], [equals status idle, changed seq, not (equals status done, of
before)]]`. A stop or a block wakes her. `working` does not. `done` becoming `idle` is only someone looking at the
finish, and wakes nothing. Her tool does not set `when` in this slice; the polled kind, whose defaults cannot know
what she wants, adds it.

**A check compares against the state at the last wake.** The first successful read is a silent **baseline**. A watch
armed by a hand-off takes the state the session was in when she handed it work, so nothing old replays. After that,
each check diffs the read against the baseline:

- No item new, changed or gone: the check is **quiet**. A paused watch resumes.
- Changes for which `when` holds: the check **woke** her. In one transaction, the read becomes the baseline,
  `version` and `series` rise, and one `wakes` row is stored. If `until` also holds, the watch ends `until`. The
  change that met it is still told: "tell me when it's closed" wakes her once, then stops.
- Changes for which `when` does not hold: quiet, and the baseline stays. If `until` holds, the watch ends `until`
  without waking her. A hand-off watch's default `until`, `[[gone]]`, ends this way when the session closes.

The baseline moves only when she is woken, so each wake carries everything since the last one. While a wake of a
watch waits in the queue, the watch is not checked, so it has at most one wake outstanding. A session that ran
`working`, `done`, `idle` (seen), `working`, `done` between two wakes reads as one finish since the last.

**A failed read pauses the watch, and the watch says why.** The kind reports a failure as a reason slug:
`unreachable`, `not_connected` (the person removed the connection), `refused`, `bad_result`, `too_many_items` or
`unknown_kind`. A failure is never treated as the item being gone. Only a successful read that lacks it means gone.
After `fail_after` failures in a row, the watch is `paused` with the last reason, and the same transaction stores a
`wakes` row (`what` `paused`) so her turn can tell the person. A paused watch is still checked, every `retry_s`. When
a read succeeds again, the watch resumes and diffs against its baseline from before the pause, so a finish during the
outage is caught on return. Expiry still runs while paused.

**It always ends.** `expires_at` is required. It is `hours` from arming, at most the kind's `max_hours`, or the
kind's `hours` when she gives none. A hand-off watch lasts the kind's `handoff_hours`, and each later hand-off on the
same session moves it forward. Expiry ends the watch silently, reason `expired`. A watch also ends `until` or
`disarmed`. A shell that hangs keeps a Claude Code session alive for days, so a watch never ends on "every shell has
returned".

**The store** is a service behind the locator, `ashley.watches.watches.Watches`, with a Postgres implementation
`ashley.watches.postgres.PostgresWatches` and a Null Object that raises `WatchesUnavailable`. It records
verdicts and keeps no rules. The job judges, and the store stores what it is told.

| Method | Contract |
|---|---|
| `arm(arm: Arm) -> Armed` | Stores an `armed` watch with the given kind, target, label, bench, `armed_by`, `track`, `when`, `until`, `tools`, `interval_s`, `expires_at`, `brief`, `standing` and optional `baseline`; returns its id and `new`. A live (armed or paused) watch of the same person, kind and target is updated instead: its `when`, `until`, `tools`, `interval_s`, `expires_at`, `brief`, `standing`, `grant` and bench take the new values, its baseline, `version` and `series` are kept, and `armed_by` becomes `handoff` if either arming was one. Raises ValueError, before writing, for a field in `when` or `until` outside `track`, conditions over their limits, `expires_at` not in the future, or a new watch past the person's `max_live`; WatchesUnavailable. |
| `disarm(household_id, person_id, kind, target) -> bool` | Ends that person's live watch on the target, reason `disarmed`. False, changing nothing, when there is none. |
| `live(household_id, person_id) -> tuple[Watch, ...]` | The person's armed and paused watches, soonest expiry first. |
| `get(watch_id) -> Watch \| None` | One watch in any state, for the turn its wake starts. |
| `due(limit) -> tuple[Watch, ...]` | At most `limit` live, unexpired watches whose `next_check_at` has come and that have no unsettled `wakes` row of their own, the longest due first. |
| `record(watch_id, version, check) -> bool` | Records one check, only while the watch is live at `version`; False, changing nothing, otherwise (another holder recorded first). `Baseline(items)`: stores the baseline, `version` + 1, failures 0. Any check but `Failed` sets failures to 0 and arms a paused watch again. `Quiet(ends)`: the watch ended `until` when `ends`. `Woke(items, changes, ends)`: in one transaction, the baseline, `version` + 1, `series` + 1, `last_woke_at`, a `wakes` row (below) whose event id is `watch:<id>:<new version>`, and ended `until` when `ends`. `Failed(reason)`: failures + 1, and the reason once the watch pauses (an armed watch keeps only the count); at `fail_after` an armed watch becomes `paused` and a `wakes` row (`what` `paused`) is stored in the same transaction. Every outcome sets `next_check_at`: `interval_s` from now, or `retry_s` while paused. |
| `expire(keep_s) -> Counts` | Live watches past `expires_at` end `expired`. Ended watches older than `keep_s` with no unsettled `wakes` row are deleted. |

The store writes the `wakes` row itself because the row and the baseline it reports must commit together, as
`ashley.senses.postgres_deposits.PostgresDeposits` already writes its reminders into `wakes`. Since one event id is one
wake per household, a `record` repeated at the same version cannot store two.

**The job** is `ashley.watches.job.run`, a singleton under `ashley.referee.lease.Lease` named `watches`,
started in `ashley.wiring_singletons.singletons` where `herdr_watch` was. Each tick (`tick_s`):

1. `expire(keep_s)`.
2. `due(batch)`, grouped by kind, household and person. Each group's kind reads once (`ashley.watches.kinds.Kind`:
   `read(group) -> Mapping[int, Items | ReadFailed]`, within `read_timeout_s`). For `claude_session`, that is one
   `Bridge.sessions` call per person, and each watch keeps only its target. A kind that raises fails every watch in
   its group.
3. For each watch, the pure judge (`ashley.watches.judge.judge`) turns the read and the watch into one check
   (`Baseline`, `Quiet`, `Woke` or `Failed`), using the diff (`ashley.watches.diff.diff`) and the conditions.
   `record` stores it.

The check and the turn are decoupled by the queue. A turn can take minutes, and a hung bridge read must not delay a
reminder, so the job never waits on a turn and the wakes runner never waits on a read.

**What a wake carries.** A `wakes` row of kind `watch` names its watch and person and carries `changes`, JSON the turn
renders. `what` is `changed` or `paused`. A `changed` wake also holds `series` (this watch's nth wake), `since` (the
last wake's time, or the arming time for the first), `ended` (`until` or null), and `items`: each with its identity,
`new`, `changed` or `gone`, and its tracked fields `before` and `after`. A `paused` wake holds `reason`. The wakes
runner takes it up like any wake (`ashley.senses.wakes.WatchWake` is in the union in `Due.wake`). It is left
due while the turn cannot run. It expires at `wake_max_age_s` (a day, since a finish told late is still worth
telling, unlike an arrival greeting), and a refusal settles it `failed`. Its turn's `source` is the wake id, so a
runner killed mid-turn resumes the same turn.

**The woken turn** (`ashley.channels.wake.watch_turn`) is `unprompted`, so
Initiative decides from `worth_saying` whether it goes out. It runs on the talk of the bench that armed the watch
while that bench is open, otherwise on the person's phone thread, with the person as the one it is with. The stored
message is the household's turn, written by the kind from fields alone (for a session: its label and status, never
its screen). Her brief arrives only as the turn's `note`: the kind's note for the change (today's done and blocked
notes move into the `claude_session` kind), which wake in the series this is and since when, and whether the watch
has now ended. Its tools follow `Reminder.tools`: none named means only the tools that read
(`ashley.tools.reading.Reading`), and named tools go through `ashley.tools.only.Only`. One exception: a hand-off
watch keeps today's turn, with the thread's tools. The person handed that session work, and "For code and the cluster
she is a front for Claude Code" already lets her act on it.

**Her tools** (`ashley.tools.watches.WatchTools`) are offered where the reply reaches the speaker alone
(`ashley.channels.audience.owner_alone`) and the speaker has connected a source some kind reads (for `claude_session`,
a herdr bridge). Arguments and results are never logged.

- `watch`: `kind` (an enum of the kinds this person can use), `target` (for a session, its id from
  `claude_sessions`), `until` (optional, the clause shape above, with fields enumerated from the kind's `track`),
  `hours` (optional, 1 to the kind's `max_hours`, fractions allowed) and `tools` (optional names, as for a reminder). Arming reads the
  target once through the kind; that read is the baseline, and a target missing from it is refused `not_found`. The
  result is the watch's label, its tracked fields now and its expiry in the household's wall clock. Arming is a read,
  so it needs no OK. Naming a tool that acts changes that: the watch is proposed
  (`ashley.senses.proposal_payloads.WatchSchedule`, in the `REMINDERS` topic) and armed by `arm_reminder` in
  a later person turn, exactly as a reminder that acts is ("Reminders she shapes"). Only tools the speaker has in the
  turn can be named.
- `unwatch`: `kind` and `target`. She disarms by what she watched, never by an id she may have lost between messages.
- `watches`: the speaker's live watches, each with kind, label, `until`, expiry and, when paused, the reason.

`claude_start` and `claude_prompt` keep arming as they do today, through `ashley.tools.claude_watching.watching`, now
`Watches.arm` with `armed_by` `handoff`, the kind's `handoff_until` and `handoff_hours`, and the session's state as the
baseline. Their result still says `watched`.

**The earlier session sense is gone.** Its poller, store, tunables and turn module are deleted, its cases are ported
to the `claude_session` kind (below), and its table is migrated and dropped.

**Settings are data**, `app/ashley/watches/watches.json`: `tick_s`, `batch`, `read_timeout_s`, `fail_after`,
`retry_s`, `wake_max_age_s`, `keep_s`, `max_live`, `max_items`, `max_value_chars`, `max_alternatives`,
`max_predicates`, and `kinds`, one entry per kind. The `claude_session` entry holds `interval_s` (15, as `poll_s`
was), `hours` (24), `max_hours` (168), `handoff_hours` (72), `track` (`status`, `seq`), `when`, `handoff_until` and `outside` (false).

**The migration** takes the next free number after main's head when it is built:

- `watches`: id, `household_id`, `person_id` (a foreign key to `people (id, household_id)`, cascading), `kind`
  (a slug), `target` (1 to 200 characters), `label` (1 to 100), `bench_id` (nullable), `armed_by` (`ashley`,
  `handoff`), `track` (text array of 1 to 8), `when_clauses` (a JSON array), `until_clauses` (a JSON array or null),
  `tools` (text array or null), `interval_s` (positive), `expires_at`, `state` (`armed`, `paused`, `ended`), `reason`
  (null exactly when armed; for ended, `until`, `expired` or `disarmed`; for paused, a failure slug), `failures`,
  `version` and `series` (each at least 0), `baseline` (a JSON object, null until the first check), `next_check_at`,
  `armed_at`, `last_woke_at` and `ended_at`. It has a unique index on `(person_id, kind, target)` where not ended,
  and an index on `next_check_at` where not ended.
- `wakes`: the kind check gains `watch`. New columns: `watch_id` (references `watches`, cascading) and `changes` (a
  JSON object). A check requires that `watch_id` is set exactly for kind `watch`, and that a watch wake has
  `changes` and `person_id` and no device. There is an index on `watch_id` where unsettled.
- Each `herdr_watched` row becomes a `claude_session` watch: `armed_by` `handoff`, its status and `seq` as the
  baseline, the kind's defaults as of the migration for `when` and `until`, and `expires_at` `handoff_hours` from
  the migration. Then `herdr_watched` is dropped, so a deploy forgets no session she was watching.

**What survives a failover:** everything, because the state lives in Postgres. A check is a read plus one
transaction. A check cut short records nothing, and the next holder repeats the read, which changes nothing. A
change made while nobody holds the lease is found by the next check against the baseline. A holder that loses the
lease between reading and recording fails the `version` condition, or its write fails on a read-only primary.
Either way nothing is recorded twice. Turns are `wakes` rows, so they resume as every wake's turn does ("Work in
flight survives its pod").

**Logs:** `watches.tick` (expired, pruned, due, baselines, quiet, woke, failed, paused, resumed, ended, duration_ms);
`watches.armed` (watch id, kind, person, `armed_by`, new, hours); `watches.ended` (watch id, reason);
`watches.woke` (watch id, wake id, series, counts of new, changed and gone items); `watches.paused` and
`watches.resumed` (watch id, reason, failures); `watches.read_failed` (kind, reason, how many watches); and
`watches.unavailable`, logged once per run of failed ticks. Never a target, label, field value or condition value.

**Measured by:**

- Blind contract tests of `Watches`, written from the method table by an agent that has not seen the implementation,
  then a planted-mutant run, as Errands had. They cover: arming the same target twice, `record` at a stale version,
  a second `Woke` at one version storing one wake, `due` skipping a watch with an unsettled wake, pausing at
  `fail_after` and resuming, and expiry pruning only watches with no unsettled wake.
- Property tests of the pure parts. `diff(a, a)` is empty. `diff(b, a)` is `diff(a, b)` with new and gone swapped.
  A predicate on a missing side is false. `negate` flips. An alternative holds only when all its predicates hold.
- The session-sense cases (`app/tests/test_watch_session.py`, `app/tests/test_watch_session_lease.py`) are ported to the
  `claude_session` kind under its default `when`: a second finish wakes, `done` to `idle` does not,
  `working` does not, `blocked` does, a session first seen replays nothing, a closed hand-off session ends silently,
  and a holder killed between read and record loses and repeats nothing. One change from today: a herdr restart that
  resets `seq` with the status unchanged now wakes her (`changed seq`), where it did not before; the turn is kept
  quiet when there is nothing to say. Another: the baseline moves only on a wake, so after a finish she was told, a
  later `working` then `idle` reads as the person looking at that finish and wakes nothing.
- An eval, `python -m ashley.evals` over cases in data, measuring and never gating. "Keep an eye on that one" arms
  `watch` on the session named, with no `until`. "Tell me when it's closed" gives `until` `[[gone]]`. "Stop watching
  it" calls `unwatch`. "Tell me when the dryer's done" arms nothing, since no kind reads the house yet.

**The next slices**, in order, each adding a kind as data plus one `Kind` implementation and no rework:

1. A polled read-only tool: any `ToolSpec.reads` tool with fixed arguments, called through the person's tools, its
   result's list turned into items by `track`, whose first field is the identity. This covers the calendar
   (`house_ask` `calendar.get_events`, which also gives the kiosk its calendar) and a list. Her tool gains `when`
   here, since a tool kind has no default that knows what matters.
2. A house entity, subscribed through Home Assistant's WebSocket (`subscribe_trigger`) by the job instead of polled.
   That needs a held connection, which `ashley.home_assistant.ha_socket` does not have (one command per connection).
3. The ledger: the armed money reminder becomes a watch whose items are `ashley.criteria.record.Transaction`s, its
   rule judged by the money predicates. `ashley.senses.deposit_sense` and its `deposit_reads` cursor are deleted.

- **Rejected: running the checks inside the `wakes` sweep.** That would keep one singleton, but a turn takes minutes
  and runs in that sweep, so checks would wait behind it, and a read hanging on a bridge would delay due reminders.
  The `watches` singleton replaces `herdr_watch`, so the count stays the same, and it drops by one when the deposit
  sense folds in.
- **Rejected: starting the turn from the check**, as the session sense did (hand off, then record). The record and
  the hand-off were two steps, held together only by the turn's `source`. A `wakes` row commits with the baseline,
  and the queue's retry and expiry already exist.
- **Rejected: a hash of the result in place of its fields.** A hash says that something changed, not what. The wake
  must name new, changed and gone items with their values, and `of` `before` must read the earlier one.
- **Rejected: moving the baseline on every change.** Changes that wake nothing (`working`, a finish someone already
  saw) would disappear between wakes, and the next wake could not say what changed since the last one.
- **Rejected: a watch with no expiry.** A session kept alive by a hung shell would cost a turn on every stop for days.
  Today's hand-off watch ended only a week after its session vanished. Claude Code's own Monitors expire on their own.
- **Rejected: `until` as prose** ("until the build passes"). It would need a model in every check, or matching on
  words, and could not be shown back to the person as what the watch waits for. A condition she cannot express in the
  predicates is a question to the person.
- **Rejected: adding item kinds to `ashley.criteria.predicates.Predicate`.** It judges a transaction and its payer's
  history. Item predicates judge a before and after of named fields, so they share the clause shape and the package,
  not the record.
- **Rejected: pausing on the first failed read.** A laptop that sleeps would pause every watch on its bridge within a
  poll, and the watches would stay paused after it woke. `fail_after` absorbs blips, and a paused watch resumes when
  its source answers.
- **Rejected for this slice: polling Home Assistant for house entities.** When house entities come (slice 2 above),
  they come by subscription. Polling every entity a person watches every few seconds costs a REST call each, and
  misses a change that flips and flips back between polls (a door opened and closed). A subscription is told of
  each change.

## What she could not do for want of a source, she does once it answers, and says so next time

If she is asked to put something on the shopping list while Home Assistant is unreachable, she says she can't and
records that she owes it. This is the first errand (open-work, "Errands"): an ask she could not carry out because one
tool source was out of reach. A singleton does it once that source answers, and its outcome is told to the asker in
the next reply of hers that may carry it.

- Fits into: a new system, Errands, because nothing in `docs/systems.md` holds things to *do* later. The outbox holds
  things to *say* and deletes them as it takes them; Memory holds what is true. The run reuses the turn loop's
  orchestrator (`ashley.channels.tool_loop.answer` over `ashley.inference.inference.Inference.step`), the result is a
  fact, and the job is a singleton under `ashley.referee.lease.Lease` like the memory write job.

**She records what she owes from a field.** `Reply` gains `owed` (`ashley.inference.reply.Reply.owed`): the
key of the source she needed (`house`, `search`) when she could not do what was asked because that source is out of
reach and doing it later is still what they want. Adding to a list or setting a reminder qualifies; "turn the light
on" does not. It is null otherwise, a bare statement included. Code keeps it only when the speaker is known (otherwise
there is no one to tell) and the key is in that turn's `ashley.tools.tools.Catalogue.unreachable`; anything else is
dropped and counted in `respond.done` as `owed_dropped`. Nor is an errand kept when the turn already ran a change
(`Steps.changed`: a call whose spec does not `read` began), since the job re-runs the whole ask and would do that part twice. When no source answered at all, the catalogue is absent, the
prompt names no source, and nothing is owed. A kept field stores one errand through the store below, keyed by the
person turn, so a turn owes at most once.

**The store** is a service behind the locator, `ashley.errands.errands.Errands`, with a Postgres implementation
`ashley.errands.postgres.PostgresErrands` and a Null Object that raises `ErrandsUnavailable`:

| Method | Contract |
|---|---|
| `owe(household_id, asker_id, conversation_id, turn_id, source) -> int` | Stores a `due` errand; the same turn again returns the existing id. |
| `claim(answering, max_age_s) -> Errand \| None` | In one transaction, takes the oldest `due` errand whose source is in `answering` and is younger than `max_age_s`, `FOR UPDATE SKIP LOCKED`, and sets it `running` with `attempts + 1` and `claimed_at`; None when there is none. Two jobs racing the lease cannot both take one. |
| `due_sources(max_age_s) -> frozenset[str]` | The distinct sources of `due` errands younger than `max_age_s`: what a `claim` could take. |
| `release(errand_id, attempt, max_attempts) -> State` | A run that could not finish goes back to `due`, or to `given_up` with reason `attempts` once `attempt` reaches `max_attempts`. Changes nothing unless the row is still `running` at that attempt. |
| `finish(errand_id, attempt, result)` | Sets it `done` with its `result`, in one transaction, under the same condition. |
| `give_up(errand_id, attempt, reason)` | Sets it `given_up` with `reason` (`refused`), under the same condition. |
| `sweep(claim_s, max_age_s) -> Counts` | `running` errands claimed more than `claim_s` ago become `given_up`, reason `interrupted`; `due` ones older than `max_age_s` become `given_up`, reason `expired`. |
| `untold(hearer, limit) -> tuple[Done, ...]` | The hearer's `done` errands not yet told that `MAY_HEAR` lets them hear, oldest first. |
| `told(errand_ids)` | Sets `told_at` on each. |

**The job** is `ashley.channels.errand.job.ErrandJob`, a singleton under `Lease` named `errands`, started in
`ashley.wiring_singletons.singletons` beside the write job. Each tick (`tick_s`) it calls `sweep`. When anything is due, it reads
`Tools.catalogue()`; a source answers when the catalogue came back and its key is not in `unreachable`. It then claims
and runs up to `batch` errands:

1. The messages are the errand's conversation through its person turn, the last `context_turns` of them, rendered as the
   turn loop renders turns. The system prompt is the persona's errand section plus the catalogue's `# Tools`. The
   errand section says who asked, that they asked while the source was out of reach and it answers now, to do it with
   the tools, and that `text` is one sentence of what she did, to tell them later.
2. `tool_loop.answer` runs under a new task, `errand` (`ashley.inference.model.Task`, its routes in `app/ashley/inference/routes.json`, and
   the spend ledger's check widened), with its own limits from the data file and no hold.
3. A reply with `owed` set (the source went again), or Inference unavailable, means `release`, and the tick claims
   nothing more from that source; Inference unavailable
   also ends the tick. A refusal means `give_up`. Otherwise the outcome is stored as a fact (below), then `finish`.

**The outcome stays on the errand.** `finish` stores the run's `Reply.text` as the errand's `result` in the same
transaction that sets it `done`, so a crash leaves either both or neither, and the next sweep calls a half-run errand
`interrupted`. The result is as heard as the ask was: the errand keeps the person turn's `visibility`, with the asker
as its owner, `shared` when the household could hear the ask and `private` when only the asker could.

**Code chooses what she tells, not the model.** `ashley.errands.errands.Errands.untold` returns the asker's
`done` errands not yet told, filtered by `ashley.hearing.MAY_HEAR` for the reply's hearer (the asker as owner), oldest
first, at most `tell_max`. `respond` reads it for a known speaker beside recall, and the prompt carries each as a
`# While they were away` line: you did this, say so briefly. Once her turn is stored (the answer's, for a held reply),
`ashley.errands.errands.Errands.told` sets those errands' `told_at`. A failure there is logged
`respond.told_unrecorded` and costs only saying it again. An unknown speaker carries none, and a private result waits
for a channel only its owner hears. Raising it unprompted is Initiative's job, through the outbox, and is not part of
this slice.

**Memory and Errands work together without sharing a table.** Memory holds what stays true; an errand holds what she
owed and how it went. When she tells the result, her turn saying it is an ordinary turn, so anything lasting in it
reaches Memory the way everything else does, through the write job.

**Settings are data**, `app/ashley/errands/errands.json`: `tick_s`, `batch`, `max_attempts`, `max_age_s`,
`claim_s`, `context_turns`, `max_tool_rounds`, `max_tool_result_chars`, `tell_max`.

**The migration** takes the next free number after main's head when it is built:

- `errands`: id, `household_id`, `asker_id`, `conversation_id`, `turn_id` (unique; foreign keys to people and to
  `turns (id, conversation_id)`, each with the household), `source`, `state` (`due`, `running`, `done`, `given_up`),
  `attempts`, `reason` (`attempts`, `expired`, `interrupted`, `refused`; set only when given up), `created_at`,
  `claimed_at` and `finished_at`, `result` (text, set only when `done`), `visibility` (`shared`, `private`) and
  `told_at`, with an index on `created_at` where `due` and one on `(household_id, asker_id)` where `done` and not told.
- `inference_calls`' task check gains `errand`.

**Logs:** `errands.tick` (swept, claimed, done, released, given_up, duration_ms); per errand, `errands.done`,
`errands.released` and `errands.given_up` with the errand id, attempt, reason, tool calls and duration_ms;
`respond.done` gains `owed` (the source key, or none) and `told` (the errand ids). Never the ask's text or the outcome's.

**Measured by an eval**, `python -m ashley.evals` over cases in data: an ask while its source is down sets `owed` to that
source; the same ask while it answers, a bare statement, and an ask that only makes sense now all leave it null.

- **Rejected: retaking an interrupted errand.** A run cut off mid-tool-call (by a failover, or by a deploy, which also
  moves the lease) may already have acted. A toggle done twice undoes itself, and a list gets two of everything. A gap
  is the lesser harm, as with the outbox, and runs last seconds, so it is rare. An open-ended errand with a stored plan
  continues after a failover (open-work, "Errands"); this one-shot ask has no plan to continue from.
- **Rejected: noticing the owed ask from her words** ("I can't reach the house"). Behaviour keys on fields.
- **Rejected: the result as a fact of the asker's with a `told` field.** Memory holds what stays true, and "I put
  milk on the list" is an event, not a truth; it would sit in the Memory room beside lasting facts, the mixing the
  write job is kept from: memory and errands are two systems that sometimes work together. What lasts reaches Memory through the turn she tells it in.
- **Rejected: letting the prompt pick the moment** ("mention it when convenient"). A stateless call keeps no rate, so
  code carries every untold result up to the cap, and the model only says it.
- **Rejected: resuming the original loop** from a stored `Held`'s entries. They carry tool results gone stale by the
  time the source returns, and one provider's continuation data; the ask is re-run from the turns instead.
- **Rejected: waiting on HA's own reconnect** (Senses) rather than reading the catalogue each tick. The catalogue is
  the one answer to "does this source answer" for every source, and a tick costs one catalogue read, only when
  anything is due.

## Her mail is a port with two adapters, and Proton's runs as a leased Bridge

**Parts 1 (OAuth secrets), 2 (the mail port, Gmail's adapter and the read tools), 3 (holders and resources), 4 (Bridge as a leased singleton), 5 (Proton's mailbox) and 6 (changes to mail) are built; the rest is designed** (open-work, "Mail"; the parts are listed under "The build, in parts"). She reads, searches, drafts, labels and sends a person's email,
and a watch over their inbox wakes a standing errand that sorts it and tells them what matters. Households use
either provider, so mail is a port with two adapters from the start: **Gmail** over Gmail's API, connected through
Google OAuth, and **Proton**, which has no public API, over IMAP and SMTP to Proton Mail Bridge, which she runs in the
clusters as a leased singleton. Mail is the first source a stranger can write to at will, so every part of it rests
on "A turn that has read outside words asks before it does anything consequential the person did not ask for": no mail tool ships before `Outside` does.

**Fits into** existing systems, with one new one:

- **Connections** gains what mail is the first to need, and every later kind reuses: who holds a connection is the
  connection's, not the kind's; what a connection reaches is a list of resources, each shared or kept; a kind's
  secret can come from OAuth. Proton is a kind whose connecting runs through Bridge.
- **Mail**, a new system: a port, `ashley.mail.mailbox.Mailbox`, over neutral records, with an adapter per
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

**Holding is the connection's.** `ConnectionKind.personal` becomes `holders`, the set of `household` and `person` a
kind allows: Sure and Home Assistant the household's, a code host and herdr a person's, Google and Proton either. A
connection's `person_id` stays the one field that says which. The person who added a personal connection hands it to
the household, or takes back one they handed over, with `PATCH /api/connections/{id}` and `holder`; only `added_by`
may take one back, and any member may hand over or remove a household one, as today. Moving reseals the secret bound
to its new holder, in the same transaction, since a secret is sealed bound to household, kind and person. A move
that would pass the kind's `most` for the new holder is 409 `too_many`.

**Seeing is the resource's.** A personal Google login reaches all of its owner's mail (and later calendars), so
sharing the household's address must not share the login. A connection lists its **resources** as the service names
them: for mail, a mailbox (a Gmail account is one; a Proton account in split address mode is one per address). The
kind lists them (`ConnectionKind` gains `resources(opened)`) when the connection is stored and again whenever the
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

**The migration** adds `connection_resources`: `household_id` (as every table carries it), `connection_id` (cascading), `ref` (the service's own id, 1 to 200
characters), `kind` (`mailbox` today), `name` (what the room shows), `shared` (boolean), unique on
(`connection_id`, `ref`). The check on `person_id` that `personal` implied moves to the service, which reads the
kind's `holders`.

**What the build settled** (`ashley.connections.resources.ConnectionResources`, `ashley.connections.moves.move`):

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
  (the room lists stored rows and never waits on a service), and read for a
  connection stored before that on the first turn that uses it. A tool call naming a mailbox the turn may not use is
  refused from stored addresses and reaches no mail service. A service that cannot say what a connection reaches leaves
  what is stored.

### A kind's secret can come from OAuth

A kind declares how it is connected (`ConnectionKind` gains `connect`): `Pasted` (an address and a secret a person
pastes, every kind today), `OAuth` (`ashley.connections.oauth.OAuthProvider` and the scopes the kind asks
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
- **Renewal is a compare-and-set.** `connections` gains `secret_version`. A pod whose access token is within
  `refresh_margin_s` of expiry refreshes, then writes the new access token (and the new refresh token, when the
  provider sent one) only where `secret_version` is still the one it read, raising it. A pod that loses reads the row
  again and uses the winner's token. Google keeps its refresh token, and a provider that rotates (Microsoft) is
  covered by the same write, since two pods may refresh at once and the loser's token would otherwise overwrite the
  current one.
- **A refused refresh marks the connection, never deletes it.** `connections` gains `needs`: null, `reconnect` (an
  OAuth grant refused: `invalid_grant`, revoked, expired) or `login` (a Proton account Bridge signed out, below). The
  room shows it, her tools over it answer `needs_reconnect` rather than empty results, and connecting again over it
  replaces the secret and clears it.
- **Google is the first provider**, for the `mail` port (`Port` gains `mail`; the calendar is a later port of the
  same kind). The kind is `google`, one per owner, its scopes `openid`, `email` and the mail scopes of the parts built
  so far. The client's `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` live in the
  deployment's secret store; unset, connecting answers 503 and the room says it is not set up.
- **The consent screen is published, unverified.** Google's own documentation says an app whose publishing status is
  Testing gets refresh tokens that expire after seven days, unless it asks only for `openid`, `email` and `profile`.
  Gmail's read, modify and compose scopes are restricted, so a published app that is not verified shows Google's
  unverified-app warning and is capped at 100 users, which a household never reaches. Verification would mean a
  security assessment for an app nobody outside the household uses. Google also drops a refresh token unused for six
  months and keeps at most 100 per account and client, dropping the oldest. A reconnect replaces the stored token
  with the newest, so the limit only drops tokens she no longer holds, and a connection her tools use never sits
  unused that long.

### Bridge runs as a leased singleton whose vault outlives its pod

Bridge's state is an encrypted vault (`vault.enc`: the Proton sessions and the IMAP passwords it issues), the keychain that opens it (`pass` with a GPG key, all files), and a message cache it rebuilds from Proton.
A spike on Bridge 3.27.1 found:

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
  calls and events named here are in Bridge's `bridge.proto` on its main branch; that the frontend runs with no GUI
  attached, and that 3.27.1 has the same calls, was checked against a real 3.27.1 (below).
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

**What part 4 settled that the design left open.**

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
- **Kubernetes calls for secrets.** `KubeApi` gains `create_secret`, `secret`, `secrets` (by label) and `delete_secret`; the
  token Secret is named for its pod and made when the epoch is raised, for the pod to mount; the app reads the token and
  certificate from the record (`ProtonBridge.keeper_access`), never from the Secret. Every epoch but the current one has its pod and Secret deleted.

**What the app needs from the cluster repo** (both sites through the shared base): a namespace where
the app's ServiceAccount may create and delete the Bridge pod and its token Secret; egress from that pod to Proton;
on each site, a Bridge Service of its own with a fixed LoadBalancer address (as Postgres has) for the IMAP, SMTP and keeper
ports, each reaching the pod when it runs in that site's cluster;
and the image built by CI as `apps/ashley-mail-bridge:<hash>`, pinned as the other pod images are. Concretely: a namespace
(`MAIL_BRIDGE_NAMESPACE`) in which the app's ServiceAccount may `create`, `get`, `list` and `delete` pods and Secrets; a
Service selecting `ashley.yggdrasil.pub/mail-bridge=true` on ports 8080 (keeper), 2143 (IMAP) and 2025 (SMTP), whose
`https` address, with the other site's, is `MAIL_BRIDGE_KEEPER_URL`; a network policy admitting the app alone to the keeper port, the pod to the app
(`MAIL_BRIDGE_APP_URL`, an `https` address with a certificate the image trusts) and to Proton, and nothing else; the image digest as `MAIL_BRIDGE_IMAGE`; and `SANDBOX_TOKEN_FILE`,
`ETCD_URL`, `SITE` and `CONNECTIONS_KEY` set where it is. The pod runs as uid 1000 with a read-only root. The app pins
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

**What the build of the changes settled** (`ashley.mail.mailbox.Mailbox.draft`, `send` and `change`,
`ashley.tools.mail_change_specs`, `ashley.tools.mail_args`):

- **The gate for changing is `ConnectionResources.usable(use, True)`**, so a shared mailbox is changed only on a turn
  whose channel names a household member, and the three tools are offered only where one mailbox passes it.
- **A label call names `messages`, each with `id`, `from` and `subject`**, and `Mailbox.change` takes them as `Target`s. The
  adapter reads every message first and refuses the whole call (`refused`) unless each one's sender and subject begin
  with what was given, then makes one `batchModify`. Labels are named by the household's own labels only, so a system
  label (`TRASH`, `SPAM`, `INBOX`, `UNREAD`) cannot be reached by a name; moving is the folder (`inbox`, `archive`, `spam`,
  `trash`, each leaving the other folders it was in) and read state is `unread`.
- **A send is posted once and never retried**; a timeout answers `unreachable`, which leaves open whether it went.
- **Scopes.** The Google kind asks for `gmail.modify` in place of `gmail.readonly`; it includes the reads, and a
  connection made earlier keeps reading.

**Settings are data**, `app/ashley/mail/mail.json`: page sizes and caps, `max_body_chars`, `max_recipients`,
`max_change_ids`, the OAuth `refresh_margin_s`, and Bridge's `heartbeat_s`, `fence_s`, `fence_margin_s`, `restart_s`
and the pod's cache size.

### The inbox watch and the sort

**`mail_inbox`** is a watch kind (`ashley.watches.mail_inbox.MailInbox`) whose target is a mailbox. Each read
takes the newest `max_items` messages in the inbox, each an item keyed by its message id and tracking `from`,
`subject`, `unread` and `labels`. Its default `when` is `[[new]]`, so a message read or labelled elsewhere wakes
nothing. Its `outside` is true: senders and subjects are written by strangers. A read answered `syncing` records no
check and is tried again at `retry_s`, so a failover's resync neither pauses the watch nor reads as every message
gone; the check gains that outcome, `ashley.watches.model.Later`. A message that arrives and leaves the
window between two checks is not seen, which `interval_s` keeps rare. The watch's target is the mailbox's address, as
the mail tools name one, and a read opens it as the person who armed the watch, in a turn that reaches them alone, so a
kept mailbox is read only for its owner and a shared one for any member. `Later` is also what the kind's read answers, so
a read and its check are the same value.

**The sort is a standing watch.** A watch gains `brief` (what this watch's turn is for, as a reminder's brief is:
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
and a send are tier c: with no judge built they wait for the person's OK. The household's labels are the mailbox's user
labels, which a label call names, and a system label can only be reached through `folder`, so a stranger's message can
choose which messages get a label but cannot reach a move. The brief no longer needs to name the mailbox for a label to run.

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

- Blind contract tests per part, written from this section by an agent that has not seen the implementation, then a
  planted-mutant run:
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
- **Rejected: a Google app left in testing.** Its refresh tokens die weekly, and reconnecting every week is a person
  step.
- **Rejected: the sort as a repeating reminder.** New mail is a change with no event, which is what watches are for,
  and a reminder on a clock either wakes for nothing or lags the mail.
- **Rejected: a per-label grant agreed with the watch.** Labels are tier b, so the sort runs without one; a second
  mechanism beside the tiers would have to be kept in step with them. Moving, archiving and sending are tier c, which a
  grant never covered.
- **Rejected: one connection per mailbox.** A Google login reaches every mailbox and calendar of its owner; splitting
  it would mean consenting once per resource. Sharing is per resource inside one connection.

### The build, in parts

Each part is one merge request with its own blind suite, and ships alone. Mail's read tools wait for `Outside`.

1. **OAuth secrets.** `OAuthProvider`, `connect_pending`, the callback, renewal by compare-and-set, `needs`, and the
   `google` kind with only `openid` and `email`, checked by userinfo. A Google account can be connected and shows as
   checked; no tool reads it. It comes first because Gmail, the first useful mail, needs it.
2. **The mail port and Gmail's read tools.** `Port` gains `mail`, `Mailbox` and its records, `GmailMailbox` read
   calls, `mail_boxes`, `mail_labels`, `mail_search`, `mail_read`, and `gmail.readonly` added to the kind. Personal
   connections only, so the gate is `owner_alone`. The first thing a person can use: "what's in my mail".
3. **Holders and resources.** `holders`, moving a connection, `connection_resources`, sharing, and the gate by
   resource. It comes before Proton because the household's shared address is the first resource someone shares.
4. **Bridge as a leased singleton.** The image, the keeper, the record, the singleton and its fence, logging in from
   the room, and Proton accounts and their addresses as connections and resources, with their sync state in the room.
   No mail tool yet, so the fence is proven before any turn depends on it. Built, except that the addresses are kept
   on the account row until holders and resources (part 3) give them a table.
5. **Proton's mailbox.** `ImapMailbox` read calls behind the same tools, `syncing` answers, and message ids by
   `Message-ID`. Built; what it settled follows this list.
6. **Changes to mail.** Built on both adapters: `mail_draft`, `mail_label` and `mail_send`, Gmail's scope raised to
   `gmail.modify` (a reconnect, which the room asks for), and the body limit held against `app/ashley/tools/outside.json`.
7. **The inbox watch.** The `mail_inbox` kind and the `Later` check. Built.
8. **The sort.** `brief` and `standing` on watches and her arming of one with mail tools. Built.

**What part 5 settled** (`ashley.mail.imap.ImapMailbox`, `ashley.mail.routed.RoutedMailbox`):

- **One Mailbox in the locator, routed by kind.** `ashley.wiring` registers `RoutedMailbox`, which sends each call to the
  adapter of `Account.kind`; the Proton adapter is in it only where Bridge is wired, and a connection of a kind with no
  adapter is `refused`. `Account` gains `kind` and `address` (the mailbox of a Proton connection the call is for, since one
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
  substring search, no table to keep. RFC 5322 allows a line of 998 characters but real ids (Gmail's, Outlook's, list
  software's) are under 100 and carry their entropy at the front, so two messages share a 64-character prefix only in a
  pathological mailbox; the first match is read, and a change is checked against the sender and subject the person was shown.
- **Folders and labels as Bridge keeps them.** A label is the folder `Labels/<name>` holding a copy of each message with
  it; a search with no folder covers inbox, archive, sent and drafts, orders the hits by when Bridge received them, and
  cursors by offset; `has_attachment` is filtered on the message, as IMAP cannot search it.
- **Changes.** A draft is `APPEND` to `Drafts` with `\Draft`; a send is SMTP, once, to the first address that connects (Bridge
  keeps the sent message); a label is added by copying into its folder and removed by deleting from it; a move is a copy and a
  delete; read state is `\Seen`. Every target is read first and checked against what the person was shown
  (`ashley.mail.targets.shown`) before any is changed; IMAP has no batch, so a failure part way leaves the earlier ones changed.

Later consumers, not designed here: her readers (open-work, "Readers she sends out") use the read tools as they are;
the calendar is a second port on the `google` kind.

## Python backend, TypeScript web app: a sibling app's stack

FastAPI, Pydantic, psycopg 3, Alembic and the `anthropic` SDK behind a TypeScript web app (per-person settings,
chat, memory view) built with esbuild, its types generated from the backend's `openapi.json` by
`openapi-typescript`, as in an earlier sibling app. A sibling app reuses proven pieces (spend and job tables, retention, web
push) and the `agentic-engineering` gate templates land unported.

- **The web app is Preact with signals, in TSX**, compiled by esbuild with no plugin. Components own their
  state and the few shared pieces (who is signed in, the open conversation) are signals with one owner each:
  the sibling app's plain-DOM client grew a 30-field object written from 10 of 15 files, and her UI is stateful (live
  chat, editing memory, push). Routing is `preact-iso`, with view state in the URL. Rejected: React (the same
  model at ten times the size), Svelte and Solid (each needs a compiler plugin outside esbuild), Lit (weaker
  template types, and the generated API types are why the client is TypeScript).
- **Her own look**, not a sibling app's; the owner's apps each look different.
- **Pydantic is the one source** for a model-output schema: type, validator and the JSON Schema sent to Claude.
- **pyright strict from the first commit**, since Python's types are opt-in.
- **etcd over its JSON gateway, with httpx2**: four calls, typed end to end. Rejected: `aetcd`, the asyncio gRPC
  client, which has no TLS while the referee requires client certificates. **psycopg 3 is libpq**, so
  `target_session_attrs=read-write` is native.
- **Rejected: Java** (the owner reads it fastest, but only the backend would be Java and the web app forces a second
  language anyway); **TypeScript throughout** (its wins, shared types and one schema source, the generated client
  already gives this stack; Node's etcd client is unmaintained since 2023); **Kotlin** (a niche frontend story).

## Inference sits behind an interface

GPUs are only on one site. Anything that could move to a local model (STT, the LLM) sits behind an interface where
"local GPU" and "cloud API" are interchangeable, so a site loss degrades to the cloud backend rather than
breaking her.

- **Any reachable model can answer; which one is data.** A provider is one way to reach a model: the Anthropic
  API (paid from API credits), or any OpenAI-compatible API, which covers ChatGPT,
  Gemini and a local server alike. Each task (today the conversation kinds; later a memory write or an
  orchestrator's step) has an ordered list of routes in `routes.json`; a route names a provider, a model, that
  provider's own parameters and the system prompt variant tuned for it, since one prompt and one set of parameters
  do not suit every model. The first route that answers wins. Trying another model is an edit to the file.
- **A provider that fails for availability rests** for a few minutes, so a spent credit or a down site costs one
  failed call rather than one before every good one. Which providers are resting is held in the process: losing
  it costs one more failed call, not a wrong answer.
- **A refusal is final.** The next route is never asked to answer what the first declined.
- **Replies are structured fields**, one per medium (`spoken`, `text`), sent to every provider as the Pydantic
  model's JSON Schema; OpenAI-compatible providers use Chat Completions, the one API Gemini and local servers
  also speak.
- **The spend ledger records every call**, answered or not, by task, provider and model, with tokens and cost,
  and the conversation it served where it served one (an id with no foreign key, so the ledger holds nothing said or
  known about anyone and keeps a row after its conversation is gone).
  Cost comes from `prices.json`, which names its source page and the date it was read; a model with no price
  records no cost rather than a guess.
- **Tool use is a step, and the caller owns the loop.** `Inference.step` makes one call and returns either the reply
  or the tool calls the model asked for; the caller runs them and calls again with the results. So a conversation
  turn, a sub-agent and an orchestrator share one Inference, each loop carries its own limit as data, and a loop may
  move between providers mid-way. Past the limit the caller asks once more with tool choice `none`, so she answers.
  A reply says in a field (`Reply.answers`) whether it is the answer: under structured outputs a model that opens with
  "let me check" has already written its whole reply, so a reply that is not the answer is dropped and the step asked
  again under `auto` with a note to act: neither brainstorm provider accepts a forced tool call, so no tool choice forces one.
  The field is how the loop tells.
  A step cut off at the token limit (`ProviderFailed.cut_off`, raised by the router as `InferenceCutOff`) is asked again
  once per turn the same way, with the `too_big` note: make the smallest real change now; the count is `Checkpoint.cut_off`. A second
  cut-off, or one not asked again, closes the turn plainly as too big (`unsaid.TooBig`, the `too_big_line`; on a paged
  channel the `too_big` status) and is not retried: the same work would be cut off again (`respond.cutoff`).
- **An offer of more help has a field of its own, and nothing delivers it.** `Reply.offer` ("want the rest?", "let me
  know if...") comes before `spoken` and `text` in the schema, so the model writes it first and the answer after; it
  is never spoken, written, sent or stored, and `respond.done` logs only whether it was set (`offered`). The prose rule
  against closing on an offer stays: with the field first and the rule, offers closed 0 of 24 `command` replies (Haiku)
  and 0 of 40 `chat` (gemini-3.8-flash) on two runs, against 18 and 10 on main; without the rule, 5 of 24 `command`.
  She sets the field on most replies (about 23 of 24 and 27 of 40); that costs a few tokens and reaches no one. The
  `command` kind's prompt, which cuts a long ask to two sentences, puts the offer of the rest in the field too.
  - Rejected: the field after `text`. Written after the answer, it held only partly (11 then 9 of 24 `command`,
    2 of 40 `chat`), and the offer was often written in both places.
  - Rejected: delivering the offer when code can tell a next step is real. Nothing in code can tell yet; when
    something can (an errand she owes), that field says so, not this one.
  - Rejected: the prose rule alone (the 18 and 10 above), and any scan of her words for an offer.
- **A provider's rejection of a schema keyword is checked before it ships.** A schema one provider accepts can make
  another answer 400 to every call, and the route list then falls through to the next model, so nothing looks broken.
  Gemini did this for about two hours: `remind_on_money.conditions` had `maxItems` on an array and on its array items
  beside the strict reply format (found by removing either, which made the call succeed). Bounds live in the
  parser (`reminder_conditions.parse`), not the schema. `tests/test_provider_schemas.py` collects every schema each
  chat provider is sent, through `channels.turn_tools.for_turn` and the wire modules (`openai_wire.tools`,
  `anthropic_wire.tools`, each `reply_schema`), and fails on a keyword in `tests/provider_schema_rejects.json`. An
  entry is there only with a source, a documentation URL or a recorded 400; Gemini's documentation lists no rejected
  keyword, so the list holds the one recorded, and a provider with none yet still has its schemas collected. Not
  covered: Home Assistant's own tool schemas, which arrive over its MCP server at run time.
- **A provider failing most of its chat calls is warned about.** The `inference-watch` singleton
  (`ashley.inference.watch`) reads the ledger every minute and logs the warning `inference.provider_alert` for each
  provider that failed at least half of at least five chat calls in the last ten minutes (`watch.json`). It keeps no
  state, so a failover only repeats a line. The warning is a log line because the app has no operator to push to (there
  is no admin role) and exports no metrics; Loki carries it.
  - Rejected: comparing with the provider's own earlier share. It needs history the app does not keep, and a provider
    that has always failed most calls is the case worth hearing about.
  - Rejected: a Prometheus metric, for want of an exporter in the app; a push to a person, for want of an operator.
- **A picture is another modality of the same router, and the result is an ordinary `image` piece.**
  `Inference.make_image` takes a prompt and an aspect (`square`, `wide`, `tall`) and returns encoded bytes; the `image` task
  in `routes.json` lists the providers in order (`gemini_image`, then `openai_image`), each an `ImageMaker`
  (`ashley.inference.image_provider`) over the provider's own wire (Gemini's native `generateContent`, which the
  OpenAI-compatible endpoint used for chat does not offer for these models; OpenAI's `images/generations`), so each
  has its own provider name beside the chat one. The models are the cheapest of each family that draws well, found in
  each provider's models list: `gemini-3.1-flash-lite-image` (listed at $0.0336 for a 1K picture) and
  `gpt-image-2.5-flare` at `medium` quality (about $0.013). Gemini is first for speed, not price: 3.1 s against 11.1 s
  for a 1K picture, while OpenAI's picture cost less. A route that fails falls to the next; a safety refusal (a
  Gemini `blockReason` or a safety `finishReason`, an OpenAI `moderation_blocked`) is final and is not offered to the
  other provider, as for text. When every route fails the error names each failure kind. Each call is a spend row (task
  `image`, the provider's tokens, a cost from `prices.json`); Gemini's cost counts all the candidate's tokens at the image
  rate, so it reads a little above the listed price.
  - **The tool is `bench_make_image`** (`ashley.tools.bench_image.BenchImageTools`): the picture's bytes go through
    `workshop.bench_file.add_file` like an upload or `bench_add_file`'s output, so the piece is shown, looked at,
    downloadable and Undo-able, and hers. Its log line carries the outcome, provider, model, media type and size, and the
    router's carries the aspect and bytes; neither carries the prompt.
  - **A household's pictures are capped in code**, `max_per_household` in `window_s` (`inference/image.json`, 20 in
    24 hours), counted from the spend ledger through the call's conversation (`ashley.inference.image_quota`) so both
    sites agree, and checked in `RoutedInference.make_image` before any provider is called. A capped call raises
    `ImageCapped` and the tool says so; a router with no limit wired draws nothing. A call that failed is not counted
    (it cost nothing); a refused one is. The check and the call are not atomic, so two simultaneous calls can pass the
    last slot; the cost of that is one picture. A conversation deleted takes its pictures out of the count.
  - Rejected: Gemini through the OpenAI-compatible endpoint, whose `images/generations` answers 404 for this model; a count
    kept in a new table, which would repeat what the ledger already holds per call; the cap in the tool alone, which
    leaves the router callable without it; retrying a refusal on the other provider, which sends one prompt to a second
    safety system until one lets it through.
- **The Usage room shows what the ledger holds, and a balance only where the provider documents a call for one.**
  Usage and cost are the ledger's (list prices times reported usage); a call with usage and no price is counted as
  unpriced, never as free. Of the paid providers only ElevenLabs documents a remaining quota
  (`GET /v1/user/subscription`, in characters, not money); Anthropic and OpenAI document past usage and cost behind
  admin keys the app does not hold, and Gemini's prepaid balance is readable only in AI Studio. Those read "unknown"
  with the reason. A household may set a monthly budget per paid provider in `budgets.json` (shipped empty), which
  shows "budget less this month's spend", labelled an estimate. A failed read renders "couldn't read", never 0.
- **Later, on the same data:** CLI providers (`claude -p` on the subscription, `opencode`), and routes that ask
  several models at once and compare them.
- **Rejected:** a gateway such as LiteLLM, which adds a service to run on both sites for what two SDKs and a
  list already do; falling through to the next route on a refusal; and one prompt for every provider.

## A composer never cuts what was typed

The web composers (her room, a bench's talk) are one-line textareas that grow to about eight lines; Enter sends and
Shift+Enter starts a line. The server's limit of 1 to 4000 characters stands, and the client does not enforce it by
truncating: past it the composer shows the count and how much to cut, and Send waits (`rooms/her/limit.ts`, shared with
the kiosk). Rejected: `maxLength` on the field, which silently dropped the end of a pasted brief.
