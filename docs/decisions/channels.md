# Channels and conversations

The turn loop every channel shares, what a conversation is, and who is talking.

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
- **Channels planned:** an MCP server, so Claude Code sessions can ask her things or tell her to remember them,
  authenticated as their user. Voice satellites, Discord (where a household may already talk) and the web app with web
  push are built.
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
  so the history is a prefix that survives from one message to the next (the clock in the system block would sit
  before every message, and no history prefix could be read): on Anthropic the last block of the last user turn,
  after the tail breakpoint (a new user turn when the last turn is not a user's), labelled `MOMENT_LABEL` ("not words
  anyone said"); on Chat Completions (Gemini, ChatGPT, local) a user message after the last entry. Measured on one
  conversation's two consecutive messages (~12K-token prefix), moving the moment out of the system prompt took
  Anthropic's cache read from 8,173 to 11,944 of ~11,995 tokens, on both Sonnet and Opus, and Gemini's implicit cache
  from 0 to 8,706 of 10,553. The mid-conversation system role (prompt-caching.md) is not used: it is not available on
  every model she routes to. The tail breakpoint is what lets the next tool round of a reply read the history this
  round wrote; without it each round re-pays the whole history (a measured 4-round turn: reads stayed at the system
  prompt's size while uncached input grew by a round's content each time). Each Anthropic call logs
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
  setting (its Home Assistant connection's settings), is asked through `house_ask`. What watches for writes on read
  asks ("is the porch light on", `HassLightSet`) is the house eval's attempted writes on its `read_only` cases. The
  eval keeps its own read allow-list (`house_reads.json`) rather than reading `reads`: a guard that trusts what it
  checks cannot fail.
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
    ("And the choices note." read as a fragment of the call it rode on). The aside and a fast cascade
    step's own `holding` field are different fields; what they share is the builder of the held `Reply`,
    `aside.holding`.
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
    errand until it is told (`decisions.md`, "Errands"). An answer that outlives `stale_s` is stored on the thread and
    its push dropped.
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
  `respond` stores her turns. It is not on the wire: the page is given the runs already placed. Turns older than the
  column are placed by position only where unambiguous (held lines and at most one answer between two person turns);
  the rest are null and show no runs. The page shows each as a collapsed disclosure
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

## Most channels are shared devices, so who is talking is its own answer

Only a personal login names a person by itself: a web session, a Discord DM, a person's Claude Code. Room satellites,
the hallway tablet and a shared Discord channel are used by whoever is there. So every request carries two answers:
the channel's audience (who will hear the reply, declared by the channel) and the speaker (who is talking), which on
a shared device starts out unknown.

- **A shared device signs in as a device**, with its own account mapped to a place and an audience, never to a
  person. The hallway tablet is everyone's kiosk.
- **The speaker on a shared device comes from signals in code**: HA presence (one person home is that person) and
  voice identification, a hint (`channel-adapters.md`, "A voice names the speaker as a hint, never as a credential").
  Until one names someone, the speaker is unknown and gets shared facts only.

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

## A composer never cuts what was typed

The web composers (her room, a bench's talk) are one-line textareas that grow to about eight lines; Enter sends and
Shift+Enter starts a line. The server's limit of 1 to 4000 characters stands, and the client does not enforce it by
truncating: past it the composer shows the count and how much to cut, and Send waits (`rooms/her/limit.ts`, shared with
the kiosk). Rejected: `maxLength` on the field, which silently dropped the end of a pasted brief.
