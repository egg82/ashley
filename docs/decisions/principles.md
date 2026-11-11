# Principles

Product-wide decisions: the words used, what she is for, who she serves, the stack, and where a value lives.

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

## Env var, file, connection or setting

**A value lives in the tier its changer and its failure name, not where it was easiest to read.** Four tiers:

- **Env var**: what the process needs before it can reach its database, or what names this deployment. The database
  URL, `CONNECTIONS_KEY`, the sign-in client, `PUBLIC_URL`, infrastructure placement (namespaces, runtime class, images
  pinned by digest, in-cluster URLs) and etcd and site. A wrong value means she cannot start, or starts as the wrong
  deployment.
- **Shipped data file** (`routes.json`, `runs.json`), with an operator's file laid over it, its path named in env
  (`ROUTES_FILE`). Defaults are versioned with the code.
- **Connection**: the credentials and addresses of outside services, per household or for the deployment (held by the
  first household), sealed and rotated from the web. An env value may seed a first row, as the provider keys and Home
  Assistant do, and then the row wins.
- **In-app setting**: a household's own choices, edited by a person through the web route and never by her tools.

`app/tests/test_env_tiers.py` lists every variable `from_env` reads with its tier and a reason. A new read fails until it
is listed, and a listed name nothing reads fails too. A name ending `_KEY`, `_TOKEN`, `_SECRET` or `_PASSWORD` must seed a registered connection kind, be a named root secret that cannot live in the database (with its reason), or be recorded debt. The gate cannot judge a tier; it makes the question get asked. The
variables that fail the rule today are marked "to move" there and queued under open-work item 42.

- **Rejected:** a gate that forbids any new env var. Infrastructure placement is legitimately env, and a ban would push
  deployment values into connections that have no seal key yet.
- **Rejected:** a tier for "env-only, optional". It is what an outside service's address becomes when nobody decides.
