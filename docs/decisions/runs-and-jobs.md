# Code runs, bench jobs and errands

Work done outside her own turn: sandboxed script runs, bench jobs handed to workers, and errands she owes.

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
- **A Claude Code job is finished when `out/RESULT.md` exists, not when its session goes quiet.** A worker may start
  long background work, end its turn and go `idle` while it runs, so `idle` or `done` without `RESULT.md` keeps the job
  `running` and its session open. A session that stays idle for `idle_nudge_s` without one is prompted once ("wait for
  the background work, then write it"); `idle_since` and `nudged_at` on the job row make that once across pods and
  sites. With `RESULT.md` present and the session stopped, the job is collected `done`. The deadline still collects
  whatever `out/` holds and ends `timed_out`, reason `deadline` with a result and `no_result` without, which her
  watch note turns into "stopped before writing its result; its work may be in its folder", not "empty". The worker's
  footer states the contract (finished only when `RESULT.md` is written; keep the work inside the job folder), and her
  hand-off guidance tells her to write briefs that stay inside it. A tick costs nothing extra while the session works
  and one `outputs` listing while it is idle or done.
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
