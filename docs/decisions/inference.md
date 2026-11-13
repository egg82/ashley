# Inference

Which model carries a task, and how a household chooses its chat model.

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
  Cost comes from the model catalogue (below); a call it cannot price records no cost rather than a guess.
- **Prices and capabilities come from models.dev, in three layers, the later winning** (`ashley.inference.catalogue`).
  A snapshot of models.dev's `api.json` is fetched when the image is built (`app/ashley/inference/catalogue_snapshot.py`,
  run by `app/Containerfile`), so a new deployment prices calls before it has fetched anything; the build fails if the
  list cannot be fetched or read. The last good fetch is kept in Postgres, refreshed by the lease singleton
  `model-catalogue` (`ashley.inference.catalogue_refresh`) every `refresh_s` in `catalogue.json`; once there is one it
  replaces the snapshot whole, and a failed fetch keeps it and tries again after `retry_s`. A person's overrides,
  deployment-wide and admin-only, are edited through `/api/catalogue` alone and store only the fields changed
  (`decisions.md`, "An override stores only what a person changed"). Each pod reads the stored layers again on the
  first call once the last read is 30 seconds old (`ashley.inference.stored_catalogue`).
  - **Unknown is never $0.** A model with no price is `unpriced`; one models.dev lists at 0 for input and output is
    `listed_zero` and also records no cost until an admin marks it `free`; a call using a part of the price the model
    does not list (cache tokens, audio, characters) records no cost. Providers `providers.json` marks `local` cost 0.
    Every price names its layer (`snapshot`, `fetch`, `override`).
  - **A task that offers tools refuses a model listed without tool calls**: the router skips that route
    (`inference.route_skipped`, reason `no_tool_calls`). A model the catalogue does not list is not refused.
  - **Route provider names map to catalogue providers** in `catalogue.json` where they differ (`gemini` is Google's).
    models.dev's prices are the current ones, and each call's cost is fixed in its ledger row when it is made, so
    there are no dated price periods.
  - **A price override is flat**: a person's price on any price field replaces upstream's prompt-length tiers.
  - Rejected: committing the snapshot. The list is several megabytes and changes weekly; a build already fetches the
    embedding model, so the image carries the list the same way.
  - Rejected: keeping a shipped price table beside models.dev for the models it lacks. That is two homes for one
    fact; a model models.dev does not list is unpriced until an admin sets its prices.
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
  and 0 of 40 `chat` (gemini-3.8-flash), against 18 and 10 with the prose rule alone; with the field and no rule, 5 of 24 `command`.
  She sets the field on most replies; that costs a few tokens and reaches no one. The
  `command` kind's prompt, which cuts a long ask to two sentences, puts the offer of the rest in the field too.
  - Rejected: the field after `text`. Written after the answer, it held only partly (11 then 9 of 24 `command`,
    2 of 40 `chat`), and the offer was often written in both places.
  - Rejected: delivering the offer when code can tell a next step is real. Nothing in code can tell yet; when
    something can (an errand she owes), that field says so, not this one.
  - Rejected: the prose rule alone (the 18 and 10 above), and any scan of her words for an offer.
- **A provider's rejection of a schema keyword is checked before it ships.** A schema one provider accepts can make
  another answer 400 to every call, and the route list then falls through to the next model, so nothing looks broken.
  Gemini did this once: `remind_on_money.conditions` had `maxItems` on an array and on its array items
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
  state, so a failover only repeats a line. The warning is a log line because the app pushes nothing to its admins and
  exports no metrics; Loki carries it.
  - Rejected: comparing with the provider's own earlier share. It needs history the app does not keep, and a provider
    that has always failed most calls is the case worth hearing about.
  - Rejected: a Prometheus metric, for want of an exporter in the app; a push to an admin, for want of a channel that
    reaches one.
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
  `image`, the provider's tokens, a cost from the catalogue); Gemini's cost counts all the candidate's tokens at the image
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

## A household chooses the model for its chat

A household picks which model carries its chat-facing tasks from the Usage room. It is a third layer of the routes,
over the shipped `routes.json` and the operator's `ROUTES_FILE`, not a store of its own: the household's entries are
laid over the deployment's routes data and checked by the same `routes.overlay` and `routes.parse`
(`ashley.inference.route_layers`), so a household can never make a route the loader would refuse.

- **Which tasks is a field in the routes data.** A task whose entry is `{"household": true, "routes": [...]}` is a
  household's (`routes.Routes.households`): `command`, `chat` and `brainstorm` ship so, and `escalated` follows
  `brainstorm` through its `like`. An operator turns a task off by giving it a plain list in `ROUTES_FILE`.
  `wrap_up` is not one: it recovers from a refusal on another provider than chat's, which a household's choice could
  undo.
- **`action_judge` is never a household's, only shown.** It is the check a turn that has read outside words passes
  before a consequential change, and a weaker model there weakens the check that guards the household itself, while any
  person of a household can choose, including one persuaded by those outside words to.
  `routes.NEVER_HOUSEHOLD` refuses the flag on it even from `ROUTES_FILE`; the room shows its routes read-only. Only
  the operator moves it, as before.
- **The household comes from the call's conversation.** Every chat-facing call already carries `conversation_id` to the
  router for the spend ledger, and a conversation's household never changes, so `RoutedInference` asks
  `HouseholdRoutes.for_call(conversation_id)` (`ashley.inference.layered_routes.LayeredRoutes`) for the routes to walk.
  A call serving no conversation walks the deployment's routes.
- **A household chooses among the deployment's routes, never writes one.** A task's options are its own routes, then
  those of the other household tasks with a provider and model not yet listed, each with its timeout and params, and
  only those whose provider is wired now. What is stored is the provider and model (`household_routes`, one row per
  household and task); the route is resolved from the deployment's routes when they are read, so the operator's tuning
  reaches everyone who chose that model.
- **The chosen route goes first and the deployment's follow it.** So a chosen provider whose key is removed is skipped
  as unwired, one that fails falls through, and a refusal is still final. A stored choice the operator no longer offers
  is not applied (`inference.choice_dropped`); one whose provider is unwired stays applied and is logged
  `inference.choice_unwired` at each refresh while it lasts.
- **Each pod caches every household's layered routes** and reads the choices again on the first call once the last read
  is 30 seconds old (`layered_routes.REFRESH_S`), so a choice made on any pod reaches every pod on both sites within
  that bound. A conversation's household is read once and remembered. A read that fails keeps what was built; before
  any succeeds every call walks the deployment's routes, which is also what a household with no choices gets, exactly.
- **Only a person chooses.** The writer is its own service (`ashley.inference.route_choice_write`), imported only by
  `app/ashley/api/spend_routes.py` and the wiring (`tests/test_settings_boundary.py`); the router reads through
  `ashley.inference.route_choices.RouteChoiceReads`, which cannot write.
- **Spend needs nothing new.** Each call's ledger row names the route that answered and is priced from the catalogue,
  so a household that moves chat to a costlier model shows in the Usage room under that provider at its price; the row
  carries the conversation, so a household's share can be counted as the picture cap counts it.
- Rejected: a `household_id` argument on `generate` and `step`. The turn loop hands its step to five helpers and
  threads `conversation_id` through every one; a second id beside it would say the same thing twice, and a turn resumed
  on another pod would still have to read the household from the conversation.
- Rejected: a context variable set per turn. Ambient state that a background task or a resumed turn silently lacks, and
  that the router would read without any caller saying so.
- Rejected: free-form routes per household. A household is not the operator: timeouts and token limits are the
  operator's tuning and bill, and a household's own route would need validating against a provider's parameters it
  cannot see.
- Rejected: choosing the tasks by name in code, and overriding `action_judge` behind a confirmation. A confirmation
  is a tap the person being persuaded would give.
