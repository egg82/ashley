# Outside words

What a turn that has read words from outside may do without asking, and how a person agrees to what it held.

## A turn that has read outside words asks before it does anything consequential the person did not ask for

**The parts**: the taint (`Inbound.taint`, `ToolSpec.outside` and `ToolResult.outside`, `Checkpoint.tainted` with `Steps.tainted`, the `outside` mark in `kinds.json`, the classification gate), holding and agreeing (`Outside`, `HeldCalls`, `carry_out`, the receipts on her turn), the tiers, the action judge, `outside_actions` and the evals. Mail and a browser
let a stranger put words into her turn, and a turn's tool calls follow its words. So a turn that has read
text written outside the household, or that was started by something outside, is **tainted**. A tainted turn reads
and speaks, and each change it would make goes by its **tier** (below): a low-stakes change runs, and a consequential
one goes to the action judge, which runs it or holds it as a proposal for the person to agree to in a later turn of
their own. A change that is held is held whatever `irreversible.json` says, which is about untainted turns. The agreed
calls then run with the arguments that were stored, and the model does not write them again. A new tool taints by default.

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
marked as the app's. A woken turn that held a call goes out even when `says` is none, because a held change
nobody sees is lost without anyone knowing; one that stays quiet after a judged change sends its receipts alone to
the speaker's phone, as a voice turn does.

**Receipts are a snapshot, not a join.** `turns.receipts` is written in the turn's transaction, because
proposals are deleted when taken or replaced, `outside_actions` is pruned at 90 days, and a judged change whose record
could not be written (`Outside._unrecorded`) must still be shown. `outside_actions` stays the audit store and the source
at closing; it keeps the headline a change was shown under (`label`). `outbox.receipts` carries them to a queued reply.
A turn stored before receipts keeps the blocks in its `text` and is read unchanged: stripping them would key behaviour
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

**The migration** is an index on `proposals (made_by, topic, id)` for the person-scoped lookup. No column is
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
  mail; a refusal loses it.
- **Rejected: holding every change in a tainted turn.** A sort's labelling, a light and a reminder would each cost a
  "yes", friction on changes whose worst case is small and visible.
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
  But the stored call would have to run outside any turn, and the tool sources are built per turn from its `Inbound` (bench, audience, speaker). The person-turn path
  reuses the store, the gate and the confirm pattern that every proposal already uses. Built since, as a person turn
  that is a command (`A tap agrees to what was held`).

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
Once the calls are done, `Turn.agreed` (`ashley.receipts.AgreedOutcome`, `turns.agreed`, only on a
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
(`outbox.receipts`), and its notification carries
`Notification.agree`, read from `Receipts.proposal_id`; the service worker offers an Agree action that POSTs it from the notification. A refused tap says why in place.

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
