# Senses, reminders and initiative

What wakes her, the reminders and proposals she keeps, the rules she composes, and whether what she says unprompted goes out.

## Whether she speaks unprompted is decided in code

A model call is stateless, so a prompt told to speak "when it makes sense" either always speaks or never does.
Code computes a score from measured facts, and her reply's structured `says` decides whether she has anything to
say. Weights, the threshold and the odds are data (`app/ashley/initiative/score.json`), tuned from real use; each
weight's sign is part of that data's contract, so the loader refuses a recent greeting that would raise the score.

- **Only a greeting is scored.** A wake rule says whether it greets (`greets`, false when absent); a greeting's turn is
  scored and rolled as below, and any other wake (the washer finished, a door left open) goes out on her `says` alone,
  as a notification should. Rejected: scoring every wake, which let a low score or a silent roll drop a notification.
- **The facts are gathered before the turn, and the plan is made before she is asked.** A greeting wake's turn carries
  its moment (`ashley.initiative.moment.Moment`): the event's hour in the household's zone, how many others are home,
  how long since the person last spoke to her, since her last turn on the same event about them, and since her last
  wake turn about them that went out, each measured back from when the event happened and None when unknown, which
  scores as nothing. Under the threshold the plan is silent; above it a roll seeded from the wake's id picks full,
  short or silent from the odds of the score's band, so a replay decides the same. The outcome reaches her as that
  call's instruction in the wake's note, never as a frequency word. Her reply goes out when the plan is not silent and
  `says` is not `none`; a turn with no moment (a wake that does not greet, a watch, a bench's reaction) goes out on
  `says` alone, logged `outcome=not_greeting`.
  Rejected: the facts read inside `Initiative`, which would make the decision impure and let the first runner and the
  resumer disagree; the moment rides on the turn's `Inbound`, checkpointed with it.
- **A quiet greeting is still a greeting.** Her turn kept quiet (`unprompted.QUIET`) counts as greeted for the same
  event, so a wake fired twice in a minute does not greet the second time; it does not count as having spoken.
  Time away is measured as time since she last heard from the person: Home Assistant's state gives only the current
  state's start, not when they left.

- **She never repeats herself:** what she recently said unprompted goes into the prompt as already said, so
  greetings and asides don't go same-y.
- **Asides (unprompted wit) are the lowest importance**, capped per person per day in code, and never interrupt
  that person's focus: not while they are on a call, have just been prompting a Claude Code session themselves, or
  it is late by their own quiet hours. A session merely running is not focus: a person can have sessions working almost
  all the time, overnight and while away.
- **Rejected: leaving the judgement to the prompt.** No history, so no rate.

## Home Assistant wakes her; she decides

HA detects, she decides. An automation she writes on a bench and the person installs carries a **wake action**,
a call of HA's `rest_command.ashley_wake` with structured data only: the event (a slug), HA's id for that run
(`{{ context.id }}`), and optionally who (a `person.*` entity), what (a slug) and when. Never free text: the piece check
(`ashley.workshop.wake_action`) refuses anything else as `bad_automation`, and the intake refuses it again as rendered.
The rest command is set up once in HA's configuration, posting to `/api/wakes` with the house's device token.
Her automation guidance (`bench_automation_specs.instructions`) carries the exact action and says, from the house
(`ashley.home_assistant.house.has_action`, reading the house's actions: wired, not wired, or unknown when the house
cannot be read), whether this house has the rest command; she is told to look the house's setup up with her house tools before asking the
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
- **Her rule is a wake piece on a bench** (kind `wake`): the event it answers, a short brief for that turn, the
  tools it may use, and whether it greets. A wake runs a turn only when exactly one rule on the household's open benches answers its event;
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
- **Whether it goes out is Initiative's**, from the wake's moment and her reply's `says`, a structured field
  (decisions, "Whether she speaks unprompted is decided in code"). A reply kept quiet is stored as her staying quiet, never as words she did
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
  turn's `household_id` already says. The wake's conversation stays unremembered.
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
  reply only words it. Rejected: leaving it to `says`, which could keep a reminder quiet.
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
reminder, change to the house. A new user of the pattern adds a payload kind, not a table: one store holds what
would otherwise be a table and a service per kind, each copying the same replace, expire and take-once code. Fits into:
Senses (which owns the gate `proposal_gate`), Tools (`ReminderTools`, `HouseChangeTools`).

- **One service, `ashley.senses.proposals.Proposals`** (`propose`, `pending`, `take`; table `proposals`), whose payload
  is a tagged record that code decodes, never her words (`ashley.senses.proposal_payloads`: `MoneyRule`,
  `ReminderSchedule`, `ReminderChange`, `HouseChange`, each stored as a JSON object with its `kind`). A new kind of
  thing she asks OK for is a payload record and its stored form, not a table or a service.
- **A topic is a family that replaces itself.** A person has one pending proposal per conversation *per topic*
  (`REMINDERS`, `HOUSE`): proposing in a topic replaces that topic's earlier one, and a house change and a reminder
  proposed in one conversation are agreed or refused apart. `propose` drops only its
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
- **A reminder's words go where its route says.** `phone` (the default), `quiet` (the turn runs, her answer is stored
  in the person's conversation, nothing is pushed and the reminder is never listed as undelivered; a turn that acts and
  has nothing to add is quiet), `room` or `screen`, each naming a device by its id from the household's own devices
  (`Reminder.device_id`): a satellite for a room, a text device that is not a satellite, a Discord server or the house
  for a screen (`ashley.channels.wake.reminder_device`), judged by form, never by name. A room or screen reminder's
  turn runs on that device's thread with its audience and place, so what she says is fit for whoever is there.
- **Every route's delivery is the reminder's own record**, its tries counted and timed on its row, claimed per try, so
  any pod on either site resumes them and never tries twice at once (`Wakes.undelivered`, `Wakes.claim`). A room is
  tried by the satellites singleton, which alone holds the connections (`ashley.channels.voice.reminders`); a screen
  counts as shown while a screen of that device is open on either site (`Screens.showing`). Not reached after
  `device_tries` tries, `device_retry_s` apart (`wakes.json`), it is pushed to the phone, which has its own tries; a
  device removed sends it to the phone at once. Rejected: the Outbox, which drops a reply its satellite cannot say;
  a second delivery table beside the reminder's row.
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
  their name is refused. Left unsaid, she answered "yes" by proposing again, which replaced the proposal and left nothing to
  agree; the guidance says agreeing is `arm_reminder` alone.
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
  connected) and what counts, and say that in one line in the person's words (never the tool's field names). Live runs
  armed a guess in the turn they proposed it, so confirmation is code, not prose. She is offered `arm_reminder`, and
  its guidance, only in a turn after a proposal of hers (`ReminderTools.catalogue`): always offered, she
  tried it in the turn she proposed, was refused, and worded the reply as if it had worked. A new proposal replaces her
  earlier ones in the conversation, so one agreement arms one rule (two had armed in one turn). It covers every rule,
  also one the person gave a payee or amount for, so there is one path and no field to claim "they already agreed". What it
  cannot tell is whether the later turn agreed. Rejected: arming in the same call with her description shown to the
  person afterwards; a `confirmed` argument, which she would set herself; arming by a proposal id, which she lost between messages and answered by asking for a second confirmation; reading the person's reply for "yes", which
  keys behaviour on words. A bonus has no payee or
  amount to ask for, so the rule says what is unusual instead (below). The bound is the guidance's count of lookups,
  since the tool loop caps rounds for the whole turn and nothing per tool. Rejected: asking for a payee or a minimum on
  a deposit that has never landed (it has neither, and the account's history is hers to read); arming a guessed payee
  or amount (a proposal the person confirms is not a guess armed silently); searching on until the round limit, which
  in production spent all six rounds and set nothing; asking the person for the account, which is the lookup she exists
  to do; `anyOf` in the schema, which not every provider adapter accepts.
- **The fired reminder's turn gets the transaction, not only her brief.** She gets the amount, day, payer,
  account, which predicates held and the payer's history (`ashley.channels.wake.reminder_turn`), so `what` need not carry them.
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
  `type=expense` filter on the real endpoint; the fake follows the deposit shape. Rejected: a second
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
  fired turn is not `promised`: her structured `says` decides whether it is sent, as for a wake (decisions,
  "Whether she speaks unprompted is decided in code"); a kept-quiet answer is recorded done with nothing pushed
  (`push.reminder` outcome `kept_quiet`). Code keys on that field, never on her words. Rejected: a second structured
  field (`tell`) beside `says`, which already means this.
- **The sense reads a neutral record.** It reads the Ledger (`ashley.senses.ledger_transactions`) and derives
  `Transaction` records from its entries; the sense and every predicate see nothing Sure-shaped, so Actual Budget would be
  another Ledger adapter. A rule that reads history makes the sense read `days` further back (and `judged_days` for a judged fire).
- **Rejected: a fixed "unusual deposit" classifier** with a lookback and tolerance in code: she gets a system to use,
  not a hardcoded classification. Rejected: a recursive and/or/not tree in the schema, which not every provider
  adapter accepts; alternatives of conjunctions say the same thing in flat arrays.
- **Unverified:** that the cadence measure (median gap, tolerance in days) suits a payer on a twice-monthly or irregular
  schedule beyond the cases tested; the defaults are data to tune.
