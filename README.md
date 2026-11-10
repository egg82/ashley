# Ashley

A household assistant in the Jarvis mould, built as its own service. Home Assistant is one of the tools she
calls, not the place she lives. She began as HA's voice pipeline with an OpenAI conversation agent; this repo is
her replacement, so she can grow features HA's model can't hold: long-term memory, initiative, and tools beyond
the house.

## What runs where

She runs on two Kubernetes clusters at once and survives losing either, with no human in the loop:

| Site | Cluster | Role |
|---|---|---|
| Site A | cluster A | Preferred primary; the house, HA and the voice satellites are here |
| Site B | cluster B | Hot standby; promoted automatically |
| Witness site | none | etcd witness on a NAS: votes, holds no data |

Every Ashley pod in both clusters serves requests. Exactly one site holds the writable database and runs
anything she does on her own initiative; a 3-member etcd decides which. Why it is shaped this way, and what was
rejected: `docs/decisions.md`.

## What exists today

- The failover referee: a 3-site etcd (members in both clusters and a witness on the witness site's NAS), shared
  with other apps that run on both sites. It, its witness and its certificate tools live in the cluster repo (the
  deployment's Kubernetes manifests, kept outside this repo: `kustomization/etcd`).
- Postgres under Patroni on both clusters (`kustomization/ashley-postgres`), site A primary and site B
  streaming; site B promotes on its own when site A goes, and the fail-back singleton hands the primary back once
  site A has streamed caught up for a while.
- The app skeleton in `app/`: a FastAPI service with `/api/health` and `/api/ready`, a Postgres schema, a Preact
  client, and the gates in `docs/engineering.md`, running on both sites (each green `main` pipeline deploys itself).
- Conversations (`app/ashley/conversations/`): people in households, conversations with their participants, turns
  and kind, their open, idle or closed state, and which conversation each channel thread is carrying.
- Inference (`app/ashley/inference/`): one structured reply, or the tool calls the model asks for, from the first model
  on a task's route list that answers (Anthropic, or any OpenAI-compatible API: ChatGPT, Gemini, a local server), with
  a spend row per call; and speech, words from audio (Wyoming faster-whisper, then OpenAI) and audio from words
  (ElevenLabs). A provider is wired when its key is set (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`,
  `LOCAL_LLM_URL`, `WYOMING_STT_URL`, `ELEVENLABS_API_KEY`).
- Channels (`app/ashley/channels/`): the turn loop every channel shares (who is talking, which conversation, her
  persona, tool calls until she answers), and the first adapter, `POST /api/messages`, for devices signed in with a
  token (`python -m ashley.channels.devices add`). The voice adapter (`app/ashley/channels/voice/`) holds each
  satellite (an ESPHome device, `python -m ashley.channels.devices satellite`) over the native API and answers each
  wake word with her reply played on the device or a room speaker (`VOICE_CLIP_BASE_URL`, `ESPHOME_NOISE_PSK`); a
  person's voice is enrolled from a satellite's own next wakes (`python -m ashley.channels.devices voice-enrol`). The
  Discord adapter (`app/ashley/channels/discord/`) answers DMs from mapped accounts and, in any channel of a
  household's server (`python -m ashley.channels.devices discord`), messages that mention her or reply to her (`DISCORD_BOT_TOKEN`).
- Home Assistant as tool and sense: each household connects its own HA in the connections room; her house tools use its
  REST and WebSocket APIs to see and change anything in it (what only reads or is easy to undo she does; a delete needs a person's OK), and presence comes from its `person` entities. People, households and the accounts that map them
  are added with `python -m ashley.people`.

The queue is `docs/open-work.md`.
