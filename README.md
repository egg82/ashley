# Ashley

A household assistant you host yourself. People in the house talk to her by voice, text, Discord or a web app.
She remembers what they tell her, runs the house through Home Assistant, looks things up, and works with them on
longer jobs at a shared "bench". She is her own service, and Home Assistant is one of the tools she calls.

She was built for one household and is published so others can run her for theirs. The author runs her across
two Kubernetes clusters, and she keeps running if either one goes down. One machine with Postgres and a model API
key runs everything except the pieces that launch Kubernetes pods (code sandbox, screenshots, media, Proton
Bridge). [Running your own](#running-your-own) shows how, and what each extra setting turns on; a compose file
for it is in [`deploy/compose`](deploy/compose).

## What she does

- **Talks wherever people are.** A web app, with a kiosk mode for a shared tablet. Voice satellites (ESPHome
  devices, config in [`deploy/esphome`](deploy/esphome)) with speech-to-text and ElevenLabs voices; she can tell
  household members apart by voice. Discord DMs and servers, web push, and a small HTTP API for any device you
  sign in.
- **Remembers.** Facts per person and per household, with visibility rules, recalled by full text and by meaning
  (pgvector). Each person can see, correct and delete what she keeps about them.
- **Speaks up on her own.** Reminders (one-off, repeating, or waiting on a bank deposit), Home Assistant events,
  watched mail inboxes and long jobs finishing. She judges each one before interrupting anybody, and stays quiet
  when it isn't worth saying.
- **Uses tools.** Home Assistant (each household connects its own, and anything irreversible needs a person's
  OK), web search through SearXNG, place search, reading pages and videos, read-only mail (Gmail, and Proton
  through Proton Bridge), read-only money (Sure), read-only GitLab and GitHub, image generation, and Claude Code
  sessions on your own machine through [`bridge/herdr`](bridge/herdr).
- **Works at a bench.** A bench is a project workspace: a set of documents, code, diagrams, recipes, 3D models,
  files and jobs that she and a person edit together, with undo. She can run code in a gVisor sandbox, check a build123d
  model before printing, screenshot pages in a headless browser, and make frame sheets and transcripts of video.
- **Picks a model per task.** Each task (chat, writing memories, judging an action and so on) has an ordered list
  of providers in [`app/ashley/inference/routes.json`](app/ashley/inference/routes.json): Anthropic, OpenAI,
  Gemini, Wyoming faster-whisper and ElevenLabs. She uses the first one that is configured and answering, and
  records what each call cost. A household can choose, in the Usage room, which of those models answers its chat.

## Running your own

**What a single machine gets.** Everything but the Kubernetes-only pieces. Her background work (writing
memories, reminders, Discord, voice satellites, web push, watches, bench jobs) must run in exactly one process;
without etcd each job holds a Postgres advisory lock, so one app container or several share it safely. The
docker-compose setup in [`deploy/compose`](deploy/compose) is the quickest start; the commands below are the same
steps by hand.

### You need

- **Postgres 18 with the `vector` extension.** CI tests against the `pgvector/pgvector:0.8.2-pg18` image.
- **At least one model key.** `ANTHROPIC_API_KEY` alone covers every text task. `GEMINI_API_KEY` alone covers
  every text task except writing memories, which waits for Anthropic instead of falling back. `OPENAI_API_KEY`
  alone does not cover chat.
- **An OIDC provider for the web app.** Sign-in is plain OpenID Connect, tested with Authentik so far, and there
  are no passwords. Without
  a provider, sign-in answers 503: you can still talk to her through the device API below, but connections such as
  Home Assistant are added in the web app.
- Docker or Podman. The image is `ghcr.io/egg82/ashley` (or `egg82/ashley` on Docker Hub), linux/amd64. The `dev`
  tag is the latest green `main`.

### Start her

```sh
docker network create ashley
docker run -d --name ashley-db --network ashley -e POSTGRES_PASSWORD=change-me \
  -v ashley-db:/var/lib/postgresql pgvector/pgvector:0.8.2-pg18

DB=postgresql://postgres:change-me@ashley-db/postgres
run() { docker run --rm --network ashley -e DATABASE_URL=$DB ghcr.io/egg82/ashley:dev "$@"; }

run python -m ashley.db migrate                                           # creates the schema
run python -m ashley.people add-household Home --timezone America/Denver  # prints the household id
run python -m ashley.people add-person 1 Sam                              # prints the person id
run python -m ashley.channels.devices add 1 laptop \
  --place office --audience household --medium text --kind chat           # prints a device token, once

docker run -d --name ashley --network ashley -p 8080:8080 \
  -e DATABASE_URL=$DB -e ANTHROPIC_API_KEY=... ghcr.io/egg82/ashley:dev
```

The `1`s are the ids those commands print; use yours. Then send her a message as that device, with the token
`devices add` printed:

```sh
curl -s localhost:8080/api/messages -H "Authorization: Bearer <token>" \
  -H 'Content-Type: application/json' -d '{"text": "Hi Ashley, what can you do?"}'
```

The app never migrates on start-up. To upgrade, run `migrate` with the new image, then start it. `/api/health`
reports the running build, and `/api/ready` answers 200 once she can serve.

### Turning features on

Each feature stays off until its settings are present, and the app starts without it. Settings are environment
variables, read in [`app/ashley/settings.py`](app/ashley/settings.py). Settings that only work together stop the
app at start-up when one of them is missing.

| Feature | Settings |
|---|---|
| Web app sign-in | `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `PUBLIC_URL`. Map each user to a person with `python -m ashley.people add-account <person> oidc <sub>`; `python -m ashley.signin unmapped` lists who was turned away |
| Model providers | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`; with `CONNECTIONS_KEY` they become the first household's connections, added and rotated in the web app, which win over the env from then on |
| Connections, added in the web app: Home Assistant, Sure, GitLab, GitHub, herdr, Google | `CONNECTIONS_KEY`, 32 random bytes in base64, which seals their secrets in the database |
| Web search | `SEARXNG_URL` |
| Files on benches | `FILES_ENDPOINTS`, `FILES_BUCKET`, `FILES_ACCESS_KEY`, `FILES_SECRET_KEY` (any S3-compatible store; they seed its connection); with `CONNECTIONS_KEY` the key that signs file links is generated once, or seeded from `FILES_LINK_KEY` |
| Voice | `WYOMING_STT_URL` or `OPENAI_API_KEY` to hear, `ELEVENLABS_API_KEY` (or the first household's ElevenLabs connection) to speak, `VOICE_CLIP_BASE_URL` for satellites, and their key (`ESPHOME_NOISE_PSK` seeds it once; then it is a connection) |
| Discord | `DISCORD_BOT_TOKEN`; `DISCORD_OAUTH_CLIENT_ID`, `DISCORD_OAUTH_CLIENT_SECRET` and `PUBLIC_URL` to link accounts |
| Gmail | `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `PUBLIC_URL`, `CONNECTIONS_KEY` |
| Web push | `VAPID_SUBJECT`; with `CONNECTIONS_KEY` the key pair is generated once, or seeded from `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY` |
| Privacy and terms pages | `OPERATOR_NAME`, `OPERATOR_CONTACT` |
| Log detail | `LOG_LEVEL` (default `info`); logs are one `key=value` line per event |
| Two sites | `ETCD_URL` (with `ETCD_CA_FILE`, `ETCD_CERT_FILE`, `ETCD_KEY_FILE`), `SITE`, `PATRONI_RESTAPI_PASSWORD`; `ACTIVE_SITE_LEADER_PATH`, `ACTIVE_SITE_MEMBER` (where the referee keeps the leader, and the value naming this site; default Patroni's key and `SITE`), `FAILBACK=off` |
| Code sandbox, screenshots, media, Proton Bridge (Kubernetes only) | `SANDBOX_*`, `CAD_IMAGE`, `LOOK_*`, `MEDIA_*`, `MAIL_BRIDGE_*` |
| Code sandbox with podman instead (see below) | `SANDBOX_PODMAN=trusted` |

**Running code without Kubernetes.** `SANDBOX_PODMAN=trusted` runs each script she writes in a podman container on
the machine she runs on, with no network, a read-only root and the profile's limits. Podman has no gVisor, so the
script shares the machine's kernel: set it only if you trust every script as much as your own. It cannot be set with
`SANDBOX_TOKEN_FILE`, and it logs a `runs.sandbox_podman` warning at every start. Only code runs move: build123d
(`CAD_IMAGE`), screenshots (`LOOK_*`), media (`MEDIA_*`) and Proton Bridge stay Kubernetes-only. The app calls the
`podman` command, so it needs podman on its `PATH`. The published image does not have it; on a host install, that
is enough. In a container, build your own image that adds podman, mount your rootless podman socket and set
`CONTAINER_HOST=unix://<socket path>`; a mounted socket lets the app start containers as that user.

## How she is built

A message from any channel becomes one turn. The turn works out who is speaking and which conversation it
belongs to, builds her persona with what she remembers about them, then calls the model and its tools until she
has an answer. It saves its progress as it goes, so another process can finish the turn if this one stops.
Postgres holds nearly everything, including the vectors, the queues and live updates (LISTEN/NOTIFY). Bench files
go to an S3-compatible store.

In the author's deployment every pod on both sites serves requests. Postgres runs under Patroni with one primary,
and a three-member etcd (one member per site, plus a witness on a NAS) decides which site leads. Anything she
does on her own initiative holds a lease there, so it runs once, on the leading site, and moves to the other site
by itself when the leader goes down. The Kubernetes manifests live in a separate repository.

```
app/        the service: ashley/ (Python 3.13, FastAPI), web/ (Preact client), tests/, Containerfile
bridge/     herdr/: a small HTTPS service you run on your own machine so she can drive Claude Code there
deploy/     images her sandbox pods run (cad, look, media, mail-bridge) and the ESPHome satellite config
docs/       design and engineering docs, listed below
```

## Docs

- [`docs/systems.md`](docs/systems.md): each system, the question it answers, where it lives and who calls it.
- [`docs/decisions.md`](docs/decisions.md): the index of the design decisions, which live in `docs/decisions/`, one
  file per system, with what was rejected and why.
- [`docs/engineering.md`](docs/engineering.md): building, testing and shipping, and the gates CI enforces.
- [`docs/open-work.md`](docs/open-work.md): what is planned and not built yet.

## Contributing

Changes reach `main` through pull requests, and the `ci-ok` check must pass. It covers the test suite (which
needs Postgres 18 with pgvector and an etcd; [`docs/engineering.md`](docs/engineering.md) has the commands),
pyright, the client checks and the image builds. Much of the code is written with Claude Code, so CI also holds its shape: limits on
function and file size, an allow-list of which packages may import which, and a time limit per test.

## License

AGPL-3.0 (see [`LICENSE`](LICENSE)). Run it, change it and share it; anyone who distributes or serves a modified copy
publishes its source under the same licence, with the copyright notices kept.
