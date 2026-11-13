# Memory

Who may know a fact, where knowledge lives, how facts are written and recalled, and what a person can do with them.

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
  profile's tool hints (the thermostat setpoints sensor, how to phrase Locate Person) belong in those scripts and
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
  conversation with facts said in passing it missed them (on a twelve-turn workbench brainstorm 0 of 3 runs wrote all four
  facts at `effort` low; on a production brainstorm of the same shape 0 of 3 at low and 0 of 3 at high), where Sonnet
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
  the interface, which would cause problems later.
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
  `writer.md` alone, which did not hold the owner.
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
