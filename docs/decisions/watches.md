# Watches

## Watches wake her when what a read returns changes, until a condition or a time

Some changes send no event: a Claude Code session the person nudged themselves finishing, a calendar event moved, a
list edited. A watch is a read she repeats on a schedule with no model in the check; when what it returns changes,
she is woken with what changed. A kind says what is read (`docs/systems.md` lists them); this file's worked kind is a
Claude Code session. She can watch any of the person's sessions ("keep an eye on that one"), not only those she handed
work to, and every watch ends at its `until` or its expiry.

- Fits into: a new system, Watches. It meets the four tests in `docs/systems.md`: many callers, one question ("wake
  her when what this returns changes, until X"), several implementations, and it owns each watch's baseline. Its kinds
  are a Type Object: code reads the source, and data holds the defaults. An unknown kind gets a Null kind whose every
  read fails, so a stale row pauses instead of breaking the tick. Changes go into the `wakes` queue (Senses), and the
  wakes runner runs the turn. Arming sits beside the reminder tools (Tools), and agreement goes through `Proposals`.

**A watch is one row: what it reads, which changes wake her, and when it ends.** A watch reads one target of one kind
for one person (for `claude_session`, a session id on that person's bridge). From each read the kind
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

**`when` defaults to the kind's.** For `claude_session` (in the settings file, below) the default is
`[[one_of status [blocked, done], changed seq], [equals status idle, changed seq, not (equals status done, of
before)]]`. A stop or a block wakes her. `working` does not. `done` becoming `idle` is only someone looking at the
finish, and wakes nothing. Her tool never sets `when`; each kind's data does.

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
started in `ashley.wiring_singletons.singletons`. Each tick (`tick_s`):

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
Initiative decides from `says` whether it goes out. It runs on the talk of the bench that armed the watch
while that bench is open, otherwise on the person's phone thread, with the person as the one it is with. The stored
message is the household's turn, written by the kind from fields alone (for a session: its label and status, never
its screen). Her brief arrives only as the turn's `note`: the kind's note for the change (the `claude_session` kind's done and blocked
notes), which wake in the series this is and since when, and whether the watch
has now ended. Its tools follow `Reminder.tools`: none named means only the tools that read
(`ashley.tools.reading.Reading`), and named tools go through `ashley.tools.only.Only`. One exception: a hand-off
watch's turn has the thread's tools. The person handed that session work, and "For code and the cluster
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

`claude_start` and `claude_prompt` arm through `ashley.tools.claude_watching.watching`: `Watches.arm` with `armed_by`
`handoff`, the kind's `handoff_until` and `handoff_hours`, and the session's state as the baseline. Their result says
`watched`.

**The `tool` kind watches one of her read-only tools.** Its target is canonical JSON (`ashley.watches.tool_target`): the
tool, its fixed `arguments`, the fields to `track` and, for an answer that holds a list, the `path` of keys down to it.
The same read in another key order is the same target, so one watch. A read runs through
`ashley.watches.tool_reads.ToolReads`, whose implementation (`ashley.channels.watch_reads.ChannelToolReads`) offers the
person's own tools as an unprompted turn for them would and narrows them to `ToolSpec.reads` with
`ashley.tools.reading.Reading`, so a tool that changes anything is refused (`refused`) and never run. With a `path` each
list entry is an item keyed by its first tracked field (equal names get `#2`, `#3` by order) and holding the tracked
fields; without one the whole answer is one item, `result`, holding the hash of its canonical JSON. An answer that is an
error, not JSON, or lacks the path fails `bad_result`; one past `max_items` fails `too_many_items`; neither is every item
gone. Her `watch` takes `read` (tool, arguments, path, track) in place of `target`, and a `when` over the tracked
fields, since this kind has no default that knows what matters: left out, any change wakes her. The woken turn's note
lists each change with its tracked values, as text from outside. The kind is `outside`: a tool's marking is per result and
a wake has no result, so a watch is never taken as inside. A calendar watch is `house_ask` with `calendar.get_events` and
the path `response`, the calendar's id, `events`.

**Settings are data**, `app/ashley/watches/watches.json`: `tick_s`, `batch`, `read_timeout_s`, `fail_after`,
`retry_s`, `wake_max_age_s`, `keep_s`, `max_live`, `max_items`, `max_value_chars`, `max_alternatives`,
`max_predicates`, and `kinds`, one entry per kind. The `claude_session` entry holds `interval_s` (15, as `poll_s`
was), `hours` (24), `max_hours` (168), `handoff_hours` (72), `track` (`status`, `seq`), `when`, `handoff_until` and `outside` (false).

**The tables:**

- `watches`: id, `household_id`, `person_id` (a foreign key to `people (id, household_id)`, cascading), `kind`
  (a slug), `target` (1 to 500 characters), `label` (1 to 100), `bench_id` (nullable), `armed_by` (`ashley`,
  `handoff`), `track` (text array of 1 to 8), `when_clauses` (a JSON array), `until_clauses` (a JSON array or null),
  `tools` (text array or null), `interval_s` (positive), `expires_at`, `state` (`armed`, `paused`, `ended`), `reason`
  (null exactly when armed; for ended, `until`, `expired` or `disarmed`; for paused, a failure slug), `failures`,
  `version` and `series` (each at least 0), `baseline` (a JSON object, null until the first check), `next_check_at`,
  `armed_at`, `last_woke_at` and `ended_at`. It has a unique index on `(person_id, kind, target)` where not ended,
  and an index on `next_check_at` where not ended.
- `wakes`: the kind check gains `watch`. New columns: `watch_id` (references `watches`, cascading) and `changes` (a
  JSON object). A check requires that `watch_id` is set exactly for kind `watch`, and that a watch wake has
  `changes` and `person_id` and no device. There is an index on `watch_id` where unsettled.
- `herdr_watched`, the earlier session sense's table, is migrated into `claude_session` watches (handoff, its status
  and `seq` as the baseline, the kind's defaults) and dropped (`app/tests/test_herdr_watched_migration.py`).

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
  then a planted-mutant run. They cover: arming the same target twice, `record` at a stale version,
  a second `Woke` at one version storing one wake, `due` skipping a watch with an unsettled wake, pausing at
  `fail_after` and resuming, and expiry pruning only watches with no unsettled wake.
- Property tests of the pure parts. `diff(a, a)` is empty. `diff(b, a)` is `diff(a, b)` with new and gone swapped.
  A predicate on a missing side is false. `negate` flips. An alternative holds only when all its predicates hold.
- The session cases (`app/tests/test_watch_session.py`, `app/tests/test_watch_session_lease.py`) run against the
  `claude_session` kind under its default `when`: a second finish wakes, `done` to `idle` does not,
  `working` does not, `blocked` does, a session first seen replays nothing, a closed hand-off session ends silently,
  and a holder killed between read and record loses and repeats nothing. A herdr restart that resets `seq` with the
  status unchanged wakes her (`changed seq`); the turn stays quiet when there is nothing to say. The baseline moves
  only on a wake, so after a finish she was told, a later `working` then `idle` reads as the person looking at that
  finish and wakes nothing.
- An eval, `python -m ashley.evals` over cases in data, measuring and never gating. "Keep an eye on that one" arms
  `watch` on the session named, with no `until`. "Tell me when it's closed" gives `until` `[[gone]]`. "Stop watching
  it" calls `unwatch`. "Tell me when the dryer's done" arms nothing, since no kind reads the house.

**Not built yet** (queued in `docs/open-work.md`; each is data plus one `Kind` implementation and no rework):

1. A house entity, subscribed through Home Assistant's WebSocket (`subscribe_trigger`) by the job instead of polled.
   That needs a held connection, which `ashley.home_assistant.ha_socket` does not have (one command per connection).
2. The ledger: the armed money reminder becomes a watch whose items are `ashley.criteria.record.Transaction`s, its
   rule judged by the money predicates. `ashley.senses.deposit_sense` and its `deposit_reads` cursor are then deleted.

- **Rejected: running the checks inside the `wakes` sweep.** That would keep one singleton, but a turn takes minutes
  and runs in that sweep, so checks would wait behind it, and a read hanging on a bridge would delay due reminders.
- **Rejected: starting the turn from the check** (hand off, then record): two steps, held together only by the
  turn's `source`. A `wakes` row commits with the baseline,
  and the queue's retry and expiry already exist.
- **Rejected: a hash of the result in place of its fields.** A hash says that something changed, not what. The wake
  must name new, changed and gone items with their values, and `of` `before` must read the earlier one.
- **Rejected: moving the baseline on every change.** Changes that wake nothing (`working`, a finish someone already
  saw) would disappear between wakes, and the next wake could not say what changed since the last one.
- **Rejected: a watch with no expiry.** A session kept alive by a hung shell would cost a turn on every stop for days.
  Claude Code's own Monitors expire on their own.
- **Rejected: `until` as prose** ("until the build passes"). It would need a model in every check, or matching on
  words, and could not be shown back to the person as what the watch waits for. A condition she cannot express in the
  predicates is a question to the person.
- **Rejected: adding item kinds to `ashley.criteria.predicates.Predicate`.** It judges a transaction and its payer's
  history. Item predicates judge a before and after of named fields, so they share the clause shape and the package,
  not the record.
- **Rejected: pausing on the first failed read.** A laptop that sleeps would pause every watch on its bridge within a
  poll, and the watches would stay paused after it woke. `fail_after` absorbs blips, and a paused watch resumes when
  its source answers.
- **Rejected for this slice: polling Home Assistant for house entities.** They will come by subscription (item 1 above). Polling every entity a person watches every few seconds costs a REST call each, and
  misses a change that flips and flips back between polls (a door opened and closed). A subscription is told of
  each change.
