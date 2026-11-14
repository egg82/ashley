# CLAUDE.md

Read `README.md`, then the decisions index `docs/decisions.md` and the files in `docs/decisions/` for the systems
a change touches, before designing anything. The queue is the repo's issues, in priority order on [the Ashley: Work board](https://github.com/users/egg82/projects/3).
How code is built and shipped: `docs/engineering.md`. The inventory of systems: `docs/systems.md`.
**Load the `agentic-engineering` skill before changing anything here**, and name it in every writer's brief.

**An ask that adds a new kind of thing (a system, new data, a new schedule) starts with a fit pass, not a design:**
what is it an instance of, which system in `docs/systems.md` already does that kind of thing, and which known
pattern solves it (GoF, Nystrom's *Game Programming Patterns*)? Extend that system or combine the two; build a new
one only when none fits, and say why. Its issue carries a "Fits into:" line. Tweaks need no fit pass.

**Never raise a held count to get a change through; split, reduce or report instead.** The gates and their
ledgers are in `docs/engineering.md`.

Rules that must hold even if nothing else was read:

- **She runs on two sites at once.** No state on a node or in a pod; anything she does on her own initiative
  holds the etcd lease first (`decisions.md`, "Singletons hold an etcd lease"). Work in flight is checkpointed
  and resumable by any pod on either site, so a rollout or failover loses nothing (`decisions.md`, "Work in flight
  survives its pod").
- **Failover never needs a person.** No design whose failover is an MR, a kubectl edit or a manual promotion
  (`decisions.md`, "Failover is automatic").
- **Kubernetes changes go in the cluster repo** (the deployment's Kubernetes manifests, kept outside this repo), in
  a worktree off a fresh `origin/main`, following that repo's own rules; both sites get the change through the
  shared base.
- **A new env var is for what the process needs before it reaches its database, or what names this deployment.** Outside services' credentials are connections, a household's choices are settings (`decisions.md`, "Env var, file, connection or setting"; gated by `test_env_tiers.py`).
- **Behaviour keys on fields, never on words in natural-language text.** Model output carries structured fields.
- **Logs carry ids and counts, never conversation content, people's data or secrets.**
- **Nothing household-specific in shipped code or data.** Entity ids, scripts, device and room names, pet names and hosts go in a connection's settings or the household's own data, edited by a person in the room; a new household starts with them empty. Settings that decide taint or judging are written only by a person through the web route, never by her tools.
- **Never commit key material.** Certificates and keys live in the deployment's secret store.
