# Engineering

How the code is built and shipped. Design rules live in `decisions.md`; the method behind these rules is the
`agentic-engineering` skill.

## Deploy

Kubernetes manifests live in the cluster repo (the deployment's Kubernetes manifests, kept outside this repo),
reconciled by Flux: `kustomization/ashley-*/` are the shared bases and `<site>/ashley/` are per-site overlays. Both
clusters run the same bases; an overlay differs only in what names the site (member name, LB IPs). The etcd she fails
over by is shared with other apps: `kustomization/etcd/` there, whose README covers its witness and certificates.

CI is GitHub Actions. `.github/workflows/ci.yml` runs on every pull request and every push to main: the suite on a
`pgvector/pgvector:0.8.2-pg18` container (production's major version, with `pgvector`) and an etcd container, split
into eight shards that each take every eighth test file in name order; the pyright gate; and the client checks
(`types:check`, `typecheck`, `test`, `build`). Beside them it builds the app image (`app/Containerfile`) and the images
other pods run, each tagged by a hash of what it bakes in (`app/tools/ci_image_hash.py` with `--look`, `--media`,
`--cad` or `--bridge`) and built only when a registry lacks that tag:
- the browser image `bench_look` runs its pods in (`deploy/look/Containerfile`: Playwright's image plus the matching
  `playwright` package);
- the media image (`deploy/media/Containerfile`), which holds ffmpeg for the media pods; the `tests` job installs ffmpeg
  too, since the media runner's tests run it for real;
- the image build123d model runs use (`deploy/cad/Containerfile`: Python slim, build123d pinned, and the helper
  `deploy/cad/ashley_cad.py` with its print check `deploy/cad/ashley_print.py`). It holds build123d, which the `tests` job
  does not, so the helper's tests (`deploy/cad/test_ashley_*.py`, `unittest`) run in that image as the sandbox runs it
  (read-only root, no network, uid 65534), over real model files (`app/tests/cad_models/`, sources beside them) with the
  print settings the app ships (`app/ashley/workshop/print.json`);
- the Proton Mail Bridge image (`deploy/mail-bridge/Containerfile`), whose keeper test runs in the image against a real
  Bridge, read-only as the pod runs it.

The cluster repo pins those images' digests. A pull request builds every image and pushes none. Images go to two
registries, `docker.io/<DOCKERHUB_USERNAME>/<image>` and `ghcr.io/<owner>/<image>`; the hosts and namespaces are the
workflow's `DOCKERHUB_REPO` and `GHCR_REPO`, so nothing names a registry twice. linux/amd64 only.

**Every change reaches main through a pull request**, and branch protection requires the `ci-ok` job, which fails
unless every other job passed. On main, the app image is pushed by digest alone; once `ci-ok` is green, `release` tags
that digest `dev` and `main-<sha8>-<commit-timestamp>`, so the deploy waits for green. Publishing a GitHub release tags
the same image `<version>` and `latest` (`.github/workflows/container-release.yml`). Flux image automation on one site writes
the `main-` tag into `kustomization/ashley-app` in the cluster repo, and the deploy runs `python -m ashley.db migrate`
from the same image. The image runs as uid 1000 on a read-only root filesystem with only `/tmp` writable, and carries
the embedding model in `/opt/ashley/models`, fetched when it is built, since nothing is fetched at runtime. Commit
timestamps may not go backwards, because the tags are ordered by string; `release` refuses a commit older than its parent.

The repository needs one variable, `DOCKERHUB_USERNAME`, and one secret, `DOCKERHUB_TOKEN` (a Docker Hub access token
with write access); GHCR uses the workflow's own `GITHUB_TOKEN`.

Secrets are in the deployment's secret store, read by External Secrets; never in either repo. The object store's
endpoints, bucket and S3 key and the download-link key are the app's `FILES_*` settings (`app/ashley/settings.py`);
the endpoints are this site's NAS first, then the other site's. The etcd private keys live in the deployment's secret
store.

## The app

Python 3.13 in `app/ashley/`, the Preact client in `app/web/`. From `app/`:

| To | Run |
|---|---|
| Serve | `DATABASE_URL=... uvicorn ashley.main:create_app --factory --port 8080` (`BUILD_VERSION` is reported by `/api/health`) |
| Migrate | `DATABASE_URL=... python -m ashley.db migrate`, a separate step, never at app start. Both sites run it at once; a Postgres advisory lock makes the second wait and find nothing to do |
| Test | `ASHLEY_TEST_DATABASE_URL=<a Postgres 18 superuser URL> ASHLEY_TEST_ETCD_URL=<a plain-http etcd> ASHLEY_TEST_DEX_URL=<the issuer of a Dex running `tests/dex/config.yaml`, on port 5556> python -m pytest -q`. The server must offer the `vector` extension, which the migrations create. Each database test makes and drops its own database; each lease test uses its own key. Unset, they skip locally and fail under `CI=true`. The whole suite is CI's: eight shards take about 6 minutes there and nearly an hour on one workstation, so locally run what a change touches and the structural gates, and read the full result from the pull request's checks |
| Type-check | `python tools/pyright_gate.py`, with the app's environment first on `PATH`: pyright finds packages through the `python` on `PATH`, so any other one reports missing imports in every file |
| Contract | `python tools/export_openapi.py`, then in `app/web` `npm run types`; commit both. Tests and `npm run types:check` fail on drift |
| Client | in `app/web`: `npm ci`, `npm run typecheck`, `npm run build` (writes `app/build/`, which the app serves at `/`) |

The gates are tests in `app/tests/` and ledgers in `app/tools/held/`, all empty. A ledger may only shrink; never
rewrite one with `--write` to let something through. An entry in `ALLOWED` in `test_boundaries.py` is a design
decision, not a way to make the test pass. A suppression names its rule and a reason on its line.
`bridge/herdr/` is a separate program that imports nothing from `ashley` (a gate in `test_boundaries.py`); the size,
suppression and pyright gates cover it, and its tests are `tests/test_herdr_bridge_*.py` over answers captured from the real
`herdr` CLI (`tests/herdr_captured/`).
`test_shipped_data_household.py` fails when shipped JSON holds a Home Assistant entity id, or any shipped JSON, markdown
or html links a host outside its `PUBLIC_HOSTS` list: a household's entities and hosts live in its settings, never in the tree.
Adding a host to that list is only for a public service.
`test_household_names.py` fails when any tracked file names the household (its people, pets, network, towns, hosts);
the names are the CI secret `ASHLEY_HOUSEHOLD_NAMES`, so it skips everywhere but CI. Moving a held string to another
file moves its `KEPT` entry with it, read from CI's "stale" and "over" output (paths and counts, never the names).
`test_env_tiers.py` fails when `settings.py` reads an environment variable that is not listed with its tier, or a listed one it no longer reads: whether a value is env, a connection or a setting is decided before it is added (`decisions.md`, "Env var, file, connection or setting").
`test_unique_helpers.py` fails when two non-test modules on pytest's `sys.path` share a basename (one session imports
only the first): name a test helper `<suite>_support.py` after its suite.

Each test gets a CPU ceiling in CI (`tests/time_gate.py`, judged only where `TIME_GATE=1`, since a busy workstation's
load alone pushes fast tests over); `TIME_GATE=1 python -m pytest -q` lists the ones over 1 s locally. The ceiling is
calibrated to the CPU: a current desktop CPU ran the suite's CPU about twice as fast as an older server CPU, so 1 s on
the one is 2 s on the other. GitHub's hosted runners have not been measured against either, so `ci.yml` takes the
slower CPU's `TEST_CEILING_S=2.0` until a hosted run's durations calibrate it, and each shard runs two xdist workers
on its four vCPUs, leaving the rest to Postgres.
A test never starts another Python: a child that imports pytest and the app costs most of the ceiling. Run a nested
session in process with `pytester` instead, and pay one-time start-up in a fixture, which the gate does not time.
The garbage collector is one such cost: `tests/conftest.py` freezes what is imported at session start and sweeps after
each test, so no test is charged a full collection pass for the cycles its predecessors left.
Two suites at once on one shared runner push tests that take about 1 s past 2 s; hosted runners give each job its
own machine, so `ci.yml` needs no lock between pipelines.

## Choosing models

Which model carries which task is `app/ashley/inference/routes.json`. To change it without rebuilding the image, set
`ROUTES_FILE` to a JSON file that overlays it: each task in the file replaces that task's whole route list, a task
it leaves out keeps the shipped list, and `cooldown_s` is replaced only if given. The result is validated exactly as
the shipped file is, so a mistake stops start-up naming `ROUTES_FILE`. This sends `chat` to an OpenAI model and
`errand` to a local OpenAI-compatible server (`provider: "local"`, wired by `LOCAL_LLM_URL`):

```json
{
  "tasks": {
    "chat": [
      {"provider": "openai", "model": "gpt-6-luna", "timeout_s": 30, "params": {"max_completion_tokens": 2048}}
    ],
    "errand": [
      {"provider": "local", "model": "qwen3-32b", "timeout_s": 60, "params": {"max_completion_tokens": 2048}}
    ]
  }
}
```

A task whose entry is `{"routes": [...], "fallback": false}` (`memory_write` ships so) runs on its first route only; an
overlay that gives it a plain list gives it a fallback. A task whose entry says `"household": true` (`command`, `chat`
and `brainstorm` ship so) lets each household choose, in the Usage room, a model from the deployment's routes to try
first; an overlay that gives it a plain list takes that choice away. `action_judge` is a safety judge: pointing it at a
weaker model weakens a check, so only this file moves it, never a household.

## Patterns

The aim behind every rule: **make bugs hard to create and easy to find.** A system many places call (memory,
tools, inference, the clock) is reached through a service locator with a Null Object default; callers never
import the implementation. Every entry point wires the locator, tools and checks included. The locator is
`app/ashley/services.py`, the wiring `app/ashley/wiring.py`; the database is its first service.

**Her systems are general, and she wires them.** What she uses (rules, senses, reminders, tools) is built from
primitives she composes and changes per ask, never a classification or policy hardcoded for one case: when an ask
does not fit, she builds the fit herself instead of handing the gap back to the person. Criteria she writes can judge
any sense, and a rule may hand a match to her own judgement, which answers in a structured field. An outside
service sits behind an adapter over a neutral record, so swapping it (Sure for Actual Budget) changes the adapter
alone, never her rules.

## How code gets written

- **A rule that can be a gate is one.** Prose rules drift; gated rules hold. Each gate lands with a planted
  failure that proves it can go red.
- **Small files, each doing one thing**, grouped in subdirectories. Functions stay under 80 lines.
- **Comments only where an implementer needs them:** API surfaces carry their contract; implementation carries
  only "this looks optimizable but isn't, because...". History goes in the commit and `decisions.md`.
- **A refactor goes in byte-identical first**; a fix found on the way is its own commit, with its own test.
- **Tests come from a different agent than the code**, written blind from the interface and its contract.
- **A pull request that touches her tools, persona or routes reports `python -m ashley.evals house` before and after** (`--json` to diff the two); it measures and never gates, and no write reaches the house.

## Rules from day one

- **Every piece of state lives in Postgres**, or in object storage replicated the same way. No node-local or
  pod-local state; a pod on either site must be able to take over.
- **Static types, checked in CI.** A suppression names its rule and a reason on its line.
- **The structural gates arrive with the first code**: file size, function size, import boundaries, and a
  citation test over `systems.md`, from the skill's templates, seeded empty.
- **Logging:** one `key=value` line per event; ids, counts and durations, never conversation content, people's
  data or secrets. Each singleton logs when it takes and loses its lease.
