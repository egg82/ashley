# Two sites and failover

How she runs on two sites as one assistant: one writer, the failover referee, the database, singletons and work in flight.

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
- **`FAILBACK=off` turns fail-back off** (default `on`), for a Postgres whose own operator decides the preferred site;
  every other singleton still runs under the lease.
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

- **The leader key and the member it must equal are deployment settings** (`ACTIVE_SITE_LEADER_PATH`, `ACTIVE_SITE_MEMBER`),
  defaulting to Patroni's key (`/service/postgres/leader`) and `SITE`, so another operator's etcd layout needs no code.
- **A site campaigns only while its own Patroni member leads**, read from Patroni's leader key in the same etcd. The
  claim transaction compares that key too, and every keepalive re-reads it, so when the primary moves the old holder
  cancels its singletons and releases within a few seconds, and the new site takes them.
- **"Leads" means holds the leader key, which outlives a demotion by up to Patroni's leader TTL.** A primary cut
  off from etcd demotes itself first, so for those seconds the old site still runs singletons against a read-only
  database. A singleton that writes must tolerate a failed write; it is never run on two sites at once.
- **Rejected: deciding the active site from the database** (`pg_is_in_recovery()` on the local member). It answers
  per site, so two sites could each see themselves writable during a split; the leader key is one answer for both.
