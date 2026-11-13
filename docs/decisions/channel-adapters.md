# Channel adapters

The channels beyond the web chat: web push, the hallway tablet, Discord and voice.

## Web push

Web push is a channel like any other: its thread is `push:<person id>`, and one singleton under the lease `push` takes
that prefix from the outbox and sends each reply to every browser the person subscribed in the devices room. Nothing
is pushed from a request pod. Her VAPID identity is `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` and `VAPID_SUBJECT` from
the deployment's secret store (`ashley-push`); unset or not one key pair, the push routes answer 503, the singleton does not run,
and the rest runs.

- **"It's on your phone" keys on a field.** `Reply.to_phone` means the written reply holds what doesn't work aloud (a
  link, a list, something long to keep). Code offers it per call, in one line of the prompt, only on a spoken channel
  to a known speaker with a subscribed browser, and honours it only then: `text` goes to their push thread, `spoken`
  plays as usual and says so, and `text` is stored as her turn, since it is what they will refer back to. Otherwise
  the field is ignored.
- **A notification may carry her words** (title "Ashley", the reply as plain text, cut to `push.json`'s `body_chars`, a click opening
  `/`; a link shows as its label): Web Push encrypts the payload to the browser's own keys, so the push service relays it without reading it.
- **A browser belongs to one person.** Subscribing an endpoint someone else had moves it; the devices room shows "on"
  only when the server says this browser is the signed-in person's.
- **Only the browsers' own push services are accepted as endpoints** (`push.json`), since the server POSTs to whatever
  a browser hands over, and no redirect is followed. A service answering 404 or 410 forgets that browser; any other
  failure keeps it.
- On iPhone, web push works only for the app added to the Home Screen; the devices room says so.
- **A woken turn routes itself: a sense is an input.** She works out where a thing goes by its type and urgency, and
  may decide to route it nowhere. So a turn she was woken
  for (`Inbound.unprompted`) on a thread other than the person's phone thread is offered the same `Reply.to_phone`,
  and code never pushes on its own. She is given facts, per call, in `# Now`: whether the person has a page open on any
  device (`ashley.channels.to_phone.looking`), told only when that can be read, and that a push reaches their phone.
  Both are offered only to a known speaker with a subscribed browser; with no browser the field is ignored, as on a
  spoken turn. Her choices are three, by fields: `says` none posts and pushes nothing (the turn is stored as
  her staying quiet, and what she did with her tools stands); `reply`, the reply is on the thread; `to_phone` also true,
  its `text` is queued for `push:<person id>` in the transaction that stores her turn, as for a spoken turn. A reply
  kept quiet never pushes (`unprompted.as_said`). The outcome is logged `wake.outcome` (`silent`, `thread` or `phone`)
  with the conversation id.
  Initiative decides only whether a woken reply goes out (`speaks`, from `says`); the channel and the
  moment are this field, which is the seam a scored Initiative would take over. Urgency is not a field. Presence is
  Live's per-pod fan-out and cannot say who is looking across both sites, so an open stream (`GET /api/live`) holds
  a row of `live_screens` (`ashley.live.screens.Screens`), refreshed at the stream's heartbeat and removed when it
  ends; one not refreshed within `live.json`'s `present_s` is a pod that died and counts as closed. Rejected: code
  pushing when no page is open, which decides routing for her and buzzes by rule; asking the pod's own fan-out, which is
  blind to the other site.

## The hallway tablet is her page, paired as a device

`/kiosk` is a page of her web app outside the person shell, for a screen anyone may use. It shows only what anyone in
the hallway may see, and does what anyone there may do.

- **The screen pairs once with a device token** from `python -m ashley.channels.devices add` (audience `present`, its
  place). `POST /api/kiosk/session` checks it with `Devices.by_token` and keeps it in a `__Host-ashley_kiosk` cookie
  (Secure, HttpOnly, SameSite=Strict), checked again on every request, so revoking the device unpairs the screen.
  Rejected: a table of kiosk sessions, a second credential to expire and revoke for one screen; and signing the
  tablet in through OIDC, which would make it a person.
- **The device rules hold as on `POST /api/messages`:** a request carrying `Cf-Connecting-IP` is refused with 401, so
  the screen loads her page at `PUBLIC_URL` on the home network, where the gateway serves it. A write must come from
  that origin, as JSON. The kiosk cookie is never a person's session nor a session cookie a kiosk.
- **Only what makes her act is counted against the device's rate:** messages and controls. The page's reads poll at
  fixed rates and cost no tokens, so counting them would let the page's own polling spend the budget for talking.
- **It shows its own conversation**, on the device's thread `device:<id>` (channel `web`, the device's audience and
  place, shared, so presence names the speaker). A held line and its answer are each stored as her turn and announced
  to the screen through Live (`later_by="turn"`), as on web chat, so "let me check" appears at once and stays, and the
  answer lands under it;
  it is not queued in the outbox, since the satellites singleton takes every outbox reply on a `device:` thread. The
  page holds `GET /api/kiosk/live` open, reopened with backoff: her mark follows the shared turns' state and the
  conversation is read back on a stored turn or a resync, with its slow timer only while the feed is down. **The glance**
  is the screen's own clock, written in the household's locale and clock, and the first names of the household's people who are home (the house's own knowledge, which whoever stands in the hallway can see), and calendar and
  reminders shown as not connected until a source exists; it is read on its timer whether or not the feed is up, since
  nothing announces a person coming or going.
- **The tablet's screen is a bench of the device's, laid out by her.** A device of form `other` has at most one screen
  bench (`benches.device_id`, owner null), created on its first change and seeded from `screen_seed.json`; until
  then the page shows its fixed layout, which is also what it shows whenever the layout cannot be read or is not
  well formed. Its pieces are the `screen` kinds (clock, who is home, the conversation, the controls), one of each,
  and the conversation is never removed, so the hall can always ask her to put things back. She places, moves,
  resizes and removes them through the Workshop's Commands from any channel of the household (`ScreenTools`), and
  every change is logged and undoable as on a bench. The screen announces `ScreenChanged` to the household's screens.
  Rejected: a Surfaces table and log of its own, a second decide/undo for the same arrangement; a jsonb layout on
  `devices`, which has no log or undo.
- **The touch controls are the screen's `controls` piece**, its body the button list. `GET /api/devices` says
  `takes_controls` for a device that takes them (`ashley.channels.model.Listed.takes_controls`); clients never infer it.
  A device says what it can do: `devices.capabilities` is a closed set (`ashley.channels.model.Capability`, today only
  `controls`), set when the device is registered (`add --controls`) or by a person afterwards (`controls DEVICE_ID
  [--off]`), because the server cannot tell a tablet from any other text device. A constraint keeps `controls` to a
  text device that is not a satellite, a Discord server or the house. The Devices room does not edit the capability. A
  person edits the buttons in the Devices room and she edits them when asked, both as an Edit naming the version read, so one of two concurrent edits
  is refused `stale_base` and redone on the other. Each light or scene must be in the house's catalogue, checked by
  the caller before the Command. A press still runs `house_do` by code. A light's action is turn on, turn off or toggle
  (`light.toggle`, the default for a new row). A toggle's button says whether its light is on: `GET /api/kiosk/controls`
  gives each toggle `on` from the house's state, null when the house cannot say, and the kiosk reads it again with its
  glance and after each press, so nothing is stored for it. `device_controls` holds a device's list only
  until its screen bench exists.
- **An open page follows the server's build, the person shell and the kiosk alike** (`web/src/session/update.ts`,
  `watch.ts`). It remembers the `version` `GET /api/health` gave when it booted, asks again on each live resync and every
  few minutes, and when the served build differs reloads at a quiet moment: no pointer, touch or key for a while (a page
  never touched reloads at once), and on the kiosk not while she is listening, thinking or speaking nor while a message
  is going. A build reloaded for that is still served old (a pod on the old image mid-roll) is retried after a backoff,
  then given up on. `dev` never reloads. There is no asset hash, so the version is the whole key.
- **An HA dashboard is not framed inside her page.** HA answers with `X-Frame-Options: SAMEORIGIN` (both
  through its proxy and on `:8123` directly), so a browser refuses to show it framed by her origin. Framing would mean
  turning off HA's `http: use_x_frame_options` for the whole instance, and the frame would still need its own HA
  login in partitioned storage. What she has no view of yet gets her own view.

## Discord is a bot, its Gateway a singleton

She is one Discord bot. A DM is its account's own channel; a household's Discord server is a device, as a satellite
is, mapped by the admin CLI (`python -m ashley.channels.devices discord`) with a home channel, `#ashley`, where she
will post on her own initiative. She moves between the server's channels, and each channel is its own thread, so its
own conversation. One unrevoked device holds a server, so revoking it frees the server for another. The adapter is
`app/ashley/channels/discord/`.

- **The Gateway session is a singleton under the lease `discord`.** Discord allows several sessions on one shard and
  does not say whether each gets every event, so two sessions are assumed to both answer; the lease allows one.
- **The token the session runs on is the Discord connection's** (`decisions/connections.md`, "Her Discord bot's token is
  a connection"). The lease body (`ashley.channels.discord.following.follow`) reads it every `token_poll_s` and runs on
  every pod, idle while there is none. A token replaced or removed in the room cancels the session, which closes the
  Gateway, and the next read opens one on the new token: a restart of the singleton, not a hot swap, so a change shows
  within one poll and costs one IDENTIFY. Rows that cannot be read leave the running session as it is. A session that
  ends on its own ends the body, and the lease campaigns again after its pause.
- **Each message is claimed in Postgres before she answers it** (`discord_seen`, `INSERT … ON CONFLICT DO NOTHING`),
  so a double reply is impossible even in a failover's overlap. During a demotion the claim fails on the read-only
  database and she does not answer, which is the lease rule's tolerated failed write. Claims are pruned after
  `seen_retention_days` each time she takes the lease.
- **On taking the lease she catches up**: for each server's home channel, and each channel with a claim in the last
  `catch_up_s`, the messages after the last claimed one and younger than `catch_up_s`, each handled as if just
  arrived; the claim makes repeating it safe. It also hands in again each claim in that window never settled (a
  session that died between claiming a message and the turn loop taking it), from that message on, without claiming
  it twice. That is safe because the message's person turn is stored once by its source (`discord:<message id>`) and
  a turn whose work is saved or whose answer is stored gets no second answer ("Work in flight survives its pod"). A first DM sent while no session is connected is missed, since its
  channel is not yet known; accepted.
- **A DM from an account mapped to a person is that person's**: audience `owner`, speaker the person. **A DM from an
  unmapped account gets nothing**, no reply and no model call, logged with the Discord user id for the admin to map.
  Answering it as an unknown speaker would give household facts to any member of the server, guests included, and
  spend on their messages. A person whose Discord privacy blocks DMs from the server's members cannot DM her either:
  Discord refuses the message before the Gateway sees it, so nothing is logged; they allow DMs in the server's privacy
  settings.
- **In any channel of a household's server she answers only a message that mentions her or replies to one of hers**,
  read from Discord's structured fields, never the text. The audience is the device's; the speaker is the author's
  person when they are in that household, else unknown, and presence never guesses, since Discord names the author.
- **The household servers are read for each server message**, so a server registered with the CLI is answered at
  once, with no restart; a message that arrives while they cannot be read is dropped unclaimed.
- **When the session ends on its own, the replies in flight finish first**: their messages are claimed, so no other
  session would answer them. Cancelling the body (a lost lease) cancels them.
- **A reply is split for Discord's 2000-character limit in code**, at paragraph, then line, then word breaks, into at
  most `max_messages` messages, the last ending `…` when cut. Every send parses no mentions, so her text can never
  ping `@everyone` or a role. In a channel the first message replies to the one she answers.
- **While she thinks she shows typing.** A turn that cannot be made posts a line from data (`unavailable_text`,
  `refused_text`); a failed send is logged and dropped, since a late duplicate is worse than a gap.
- **The library is hikari** (asyncio, typed, every cache off, runs in the caller's loop with no signal handlers),
  fenced in `client.py` behind the adapter's own interface; `test_boundaries.py` holds the fence. Every session start
  spends one of the token's 1000 daily IDENTIFYs, which the lease's pause after a failed body bounds.
  - Rejected: discord.py (caches guilds and channels by default, releases slower, pulls `audioop-lts`).
  - Rejected: disnake, nextcord, py-cord (cache-heavy discord.py forks with smaller teams).
  - Rejected: a hand-rolled Gateway client (heartbeat, resume, compression and rate limits to own for nothing).

## She runs her own voice pipeline

Satellites (Voice PE, ESPHome) talk to Ashley directly over the ESPHome native API (`aioesphomeapi`, the client
HA itself uses); wake word and echo cancellation stay on the device; STT and TTS sit behind the inference
interface (Wyoming for faster-whisper). The pipeline is the voice channel adapter, not a new system.

- **Speaker identification needs the audio**, and HA hands its conversation agent text. Owning the pipeline also
  gives streaming TTS, barge-in, and her own rule for when to keep listening.
- **A satellite connection is a singleton**: the active site holds it under the etcd lease, or both sites answer.
  One singleton (`satellites`) holds every household's satellites.
- **End of speech is a wait tuned as data**, not code: microVAD scores each 10 ms frame and the silence window,
  speech needed to start, and longest utterance live in `app/ashley/channels/voice/voice.json`. They are Home
  Assistant's segmenter's values: a low bar (0.2) for speech to start, tolerating gaps under a second, a higher one
  (0.5) to keep it going, then 700 ms of silence; tuned from the `voice.run` line's durations.
- **Her reply clip is text, synthesised when it is fetched.** A run stores the reply in `voice_clips` under a random
  token kept only as its SHA-256, commits it, and only then sends the URL; `GET /api/voice/clips/{token}` streams
  `Inference.speak` of it. Any pod on either site can serve the fetch, so nothing is held in the singleton's pod.
  Rejected: storing the audio (state to replicate for a file played once) and streaming it down the satellite's API
  connection (only the singleton's pod could serve it, and a room speaker needs a URL anyway).
- **The pronunciation lexicon applies to every spoken reply**, in `render`, so a spoken device on `POST /api/messages`
  gets the same spellings as a satellite.
- **The pronunciation words are the household's.** A small table beside the household (`household_lexicon`, one row per
  household and real spelling), edited by any person of it in the Household room, read by the household a reply renders for
  on every spoken render and held nowhere between renders, so an edit applies to the next reply and no household hears
  another's. A render with no household, a household with none and words that cannot be read are all an unchanged reply,
  logged `lexicon.unreadable` for the last. A new household starts with none. A word is one word-like token with a spelling, each at most 64 characters, and a household holds
  at most 200. Rejected: a TTL cache (a second household's reply must never wait on the first's edit), a connection
  setting (no service stands behind it), and a version column (rows are edited one word at a time, so there is no whole
  object to conflict over).
- **The wake word opens a conversation; she keeps the mic open within it.** After she speaks, or when she opens
  a conversation herself, the satellite listens for the reply with no wake word, then closes on silence. Flowing
  conversation without a constant stream.
- **A wake may be overheard, so her reply may decline or offer.** The voice adapter marks each wake's turn
  `Inbound.overhears`, which offers her `Reply.says` `offer` (one short question whether they want her to do what she
  heard) and `none`, told in `# Now`, and code honours them there alone (`ashley.channels.unprompted.says`). On
  `none` nothing is played, no clip is stored, the conversation is not continued (so a false wake records one
  utterance and no more), and the turn is stored as her staying quiet, as a woken turn's is. `voice.run` logs `says`;
  how often `none` is chosen on real wakes decides whether bare "Ashley" can wake her. `says` is the one field for
  every channel (a woken turn's silence too); a person's turn on any other channel is said whatever it holds.
- **Rejected: always-on listening.** Every room's audio streamed to two clusters is a privacy and bandwidth cost
  the household didn't ask for.
- **A tablet on HA Assist can stay a satellite while her own pipeline runs beside it** on an Atom Echo; the hallway
  tablet itself is her own page ("The hallway tablet is her page, paired as a device").
- **A room's ears and voice can be different devices.** A satellite can be only the microphone while her reply
  plays on that room's Nest or a better speaker; Nests are output only anyway (HA cannot reach their
  microphones). An Atom Echo cube (one mic, no echo cancellation, a tiny speaker) is cheap enough for
  this; rooms that need interrupting her mid-reply get a Voice PE.
- **Her voice reaches a satellite as streamed 16 kHz WAV** (`pcm_16000` behind a WAV header). A satellite decodes
  only what its firmware declares: the Echo's media player is built for WAV and silently played nothing from MP3.
  HA converts per device with ffmpeg; she sends the one format every satellite and Cast can play, which also leaves
  the device nothing to decode. Changing the `speak` route's format means checking each satellite's firmware first.
- **Looked at, and fine: speech tasks optional in `routes.parse`.** The shipped `routes.json` is held to having both by
  `app/tests/test_speech_routes.py`, so requiring them in the parser too would only rewrite the routes contract tests.
- **Looked at, and fine: the reply call's shape.** Measured in the pod on the real command prompt (Haiku, 10.5k tokens
  cached): first token about 0.7 s and the whole short reply about 1.0 s. Leaving out the tools saved about 70 ms,
  inside the noise, so neither a tool-using sub-agent nor tools offered on demand is a latency fix: each adds a model
  round (about 1 s) when a tool is needed. Both stay token levers (open-work, "Golf the system prompt"). Dropping the JSON schema changed nothing, nor did a
  spoken-only schema (half the output tokens, no faster). `effort: low` stays: without it a reply ran to 300 tokens and 2.4 s.
- **Rejected: HA's Assist pipeline pointed at her.** Text-only input rules out voice identification, and
  continuing a conversation hinges on HA's heuristics (a reply ending in "?").

## A voice names the speaker as a hint, never as a credential

On a satellite the speaker is unknown unless one person is home. Each wake's utterance also gets a voiceprint, a
vector of how the voice sounds, compared with the prints enrolled for the household's people. A close enough match
names the speaker.

- **Voice is not authentication.** A replay, the TV or a sibling can match. That costs little here: a satellite's
  audience is never `owner`, so private facts are filtered out whoever is named. What a name widens is the speaker's
  own non-private facts, and whose name new facts are written under. Anything acting with a person's authority
  (their Claude Code sessions, an errand that writes automations) needs a channel that names the person; a voice
  match is not enough.
- **Order of signals:** a channel that names the person, then a voice match, then presence (one person home). A
  match for someone presence knows to be away is refused.
- **A match needs a floor and a margin**: the best person's score at or above `floor`, ahead of the runner-up by
  `margin`, on at least `min_audio_ms` of audio. Each person's score is the cosine against the mean of their prints.
  The numbers are data in `voice.json`. Until `decides` is set there, matches are only logged.
- **Accuracy is measured without a person labelling anything.** When exactly one person is home, presence names the
  speaker, so each logged match says whether it agrees. That rate on real wakes sets `floor` and `margin`, and decides
  `decides`.
- **Enrolment uses the device's own wakes.** The admin CLI arms a device for a person for a number of wakes. Each of
  those wakes stores its print for that person and is answered as usual. The audio is never stored, only the
  vector. The device's own mic and room are what the prints will be compared against, which a clean recording
  elsewhere is not.
- **A print carries the model that made it**, and only prints from the current route's model are compared. Vectors
  from two models are not on one scale.
- **The model is NeMo TitaNet-small through sherpa-onnx**, in-process on CPU (about 20 ms per wake), baked into the
  image like the text embedder. On 23 LibriSpeech speakers it separated 1.5 s clips with 0% EER clean and 1.6% at
  10 dB SNR. That bounds the choice only; the Echo at two metres is measured from the logs.
  - Rejected: CAM++ (WeSpeaker and 3D-Speaker). Through sherpa-onnx 2.0.1, different speakers scored 0.78 cosine and
    EER was 25-50%. The cause was not found.
  - Rejected: WeSpeaker ResNet34 (34% EER at 10 dB) and ERes2Net (7%, about twice the CPU).
  - Rejected: SpeechBrain and pyannote, which need torch in the image.
- **Who was matched is never logged**, as presence never logs who is home: a person's id on a device's wake is a
  record of where they were. `voice.speaker` carries the outcome, the scores and whether presence agrees.
