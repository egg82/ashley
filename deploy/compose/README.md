# Run Ashley with Docker Compose

This directory starts Ashley on one machine: Postgres, the database migration, and the app. Extra services are
compose profiles you switch on when you want them. Running her on two sites at once is the Kubernetes deployment,
described in `docs/engineering.md`; there is no etcd, Patroni or failover here.

## What runs here

Her background work (memory writing, reminders, Discord, voice satellites, web push) runs here under a Postgres
lock, so one app container or several share it safely. Handing the database back to a preferred site after a
failover needs the two-site deployment. Code running, bench screenshots, media and Proton Mail launch pods in
Kubernetes and are not available here.

## Start

You need Docker with the compose plugin, and a key for at least one model provider.

```
cp .env.example .env
```

Edit `.env`: set `CONNECTIONS_KEY` (the file shows the command) and one provider key such as `ANTHROPIC_API_KEY`.
Then:

```
docker compose up -d
```

Postgres starts first, `migrate` runs once, and `app` starts when it succeeds. The app listens on
`http://localhost:8080`; set `ASHLEY_PORT` to change that. `curl localhost:8080/api/ready` returns
`{"ready":true,"writable":true}` when she is up.

## Profiles

| Profile | Adds | Settings to fill in `.env` |
|---|---|---|
| `files` | Garage, a small S3-compatible object store, for bench files and pictures. `garage-init` creates the bucket and the app's key and exits. | the five `FILES_*` values and the two `GARAGE_*` secrets; `FILES_ENDPOINTS=http://garage:3900` |
| `search` | SearXNG with JSON output on, for her web search | `SEARXNG_URL=http://searxng:8080` and `SEARXNG_SECRET` |
| `voice` | `rhasspy/wyoming-whisper`, speech-to-text | `WYOMING_STT_URL=tcp://whisper:10300` |

Fill in the settings, then start with the profile named:

```
docker compose --profile files --profile search up -d
```

The app reads its settings at start, so `up -d` recreates it when `.env` has changed.

## First household, person and device

Run these once. Each prints the id it creates.

```
docker compose run --rm app python -m ashley.people add-household "Doe household" --timezone America/Denver
docker compose run --rm app python -m ashley.people add-person 1 Sam
docker compose run --rm app python -m ashley.channels.devices add 1 kitchen \
  --place kitchen --audience household --medium text --kind chat
```

The device command prints a token once. Keep it; it signs the device in. `--audience` is `household` or `present`,
`--medium` is `text` or `spoken`, and `--kind` is `chat`, `command` or `brainstorm`.

## Talk to her

```
curl -s localhost:8080/api/messages \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"text": "What can you do?"}'
```

The reply is JSON with a `body`. A device token is refused on a request that arrives through Cloudflare's public
tunnel (a `Cf-Connecting-IP` header), so use it from your own network.

## Sign-in for the web app

The web app at `/` signs people in through an OIDC provider. Authentik is the one it is built against. Create an
OIDC application there with the callback `<PUBLIC_URL>/api/auth/callback`, then set `PUBLIC_URL`, `OIDC_ISSUER`,
`OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET`. Someone refused at sign-in shows up in
`python -m ashley.signin unmapped`; link them to a person with
`python -m ashley.people add-account <person id> authentik <their OIDC subject>`. Without a provider the
web app cannot sign in, but devices and `curl` work.

## Upgrade

```
docker compose pull
docker compose up -d
```

`migrate` runs again on every `up` and does nothing when the database is current. Set `ASHLEY_TAG` to a release
version to stay on it; `dev` follows main.

## Stop and remove

`docker compose down` stops everything and keeps the data. `docker compose down -v` also deletes the database and
the other volumes.
