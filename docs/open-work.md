# Open work

The queue, top first. Delete an item when it ships; design rules live in `decisions.md`.

The first version worth switching to adds two things to what runs today: her own voice pipeline past the first Echo,
and the arrival greeting (the web app's first cut is built). The rest build on the pieces those land.


42. **Others run her, with their own keys.** Anyone can stand her up from the published image and change what a
    household would want to change from the web; env vars stay for the basics (database, `CONNECTIONS_KEY`, sign-in,
    public URL). The single-machine lease, `ROUTES_FILE`, `deploy/compose`, generic OIDC naming, the household
    panel, model provider keys as connections, any OpenAI-compatible provider and a household's model choice are built; what is left, by how soon a
    new household meets it:
    - **Other OIDC providers** (Entra, …) added through an OIDC library when asked. Fits into: Sign-in.
    - **Env values that belong in a connection or a setting** (`decisions.md`, "Env var, file, connection or setting"; the
      `TO_MOVE` set in `app/tests/test_env_tiers.py`, which fails if one is not named here). To connections, each seeding
      its first row: `WYOMING_STT_URL` and `SEARXNG_URL` (outside services' addresses), `DISCORD_BOT_TOKEN`, and the
      `FILES_ENDPOINTS`, `FILES_BUCKET`, `FILES_ACCESS_KEY` and `FILES_SECRET_KEY` of the S3-compatible store.
      `ESPHOME_NOISE_PSK` is the household's own devices' key, so it moves to the household's settings. `FILES_LINK_KEY`,
      `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY` are deployment secrets that could be generated on first start into a
      sealed deployment row. Fits into: Connections.
    - **What is left of the model catalogue:** an override that defines a provider, an admin page over
      `/api/catalogue`, and a price for `gpt-image-2.5-flare`, which models.dev does not list. Fits into: Inference.
    - Held on purpose until the cluster repo moves with them: the pod label prefix, `failback.json`'s preferred
      site, and the room names in `app/ashley/evals/house_cases.json`.

48. **A device says what it can do.** `takes_controls` is derived from `form` `other` with medium `text`, the only
    fact the server holds (`ashley.channels.model.Listed.takes_controls`); the devices table gets an explicit capability
    set when a device is registered, and the rule goes. Fits into: Devices.

43. **The suite's remaining real waits and fixed costs.** A pull request's checks take about 6 minutes; what is left
    of that, largest first:
    - **A lease takeover timed out once in CI**: `tests/test_watch_session_lease.py::test_of_two_sites_one_checks_and_the_other_takes_over_from_the_stored_state`
      waited 8.2 s with no takeover on a 2 s TTL (run 43391109530, the first run of the test image; green on rerun and
      in the 25 runs before). It runs on the real etcd; reproduce it under load before blaming the image.

1. **Her own voice pipeline, past the first Echo.** One wake on the first Echo (an M5Stack Atom Echo) reaches
   her through her own pipeline: faster-whisper on each site, the turn loop, ElevenLabs, played on the
   Echo. What is left, in order:
   - **A room speaker she reaches directly.** An ESPHome speaker-only satellite (an ESP32 with an I2S amplifier,
     printed), told to play the clip URL over the native API connection she already holds, so no HA hop and no Cast
     session. A device's room speaker then names another device; an HA `media_player` stays the fallback. A Nest Hub
     is that fallback today: Cast plays a connection chime and starts slower.
   - **Clean the audio before STT.** The Echo asks for noise suppression level 2 and auto gain 31 dBFS; HA applies
     them server-side (pyspeex-noise) and her pipeline drops them. Whisper got the one captured wake right without
     them; measure on quiet and far speech before adding a stage.
   - **Latency, judged against `voice.run`.** The first live wakes took about 3.8 s from end of speech to her
     voice's first byte. Measured since, on the active site: the 700 ms end-of-speech wait, STT 0.5 s after speech
     (whisper `base` int8 on CPU), the reply call about 1.0 s (the rest of a turn is under 50 ms), and TTS first byte
     120-150 ms, its connection opened while she thinks (290-550 ms cold). The
     call's parameters are settled (`decisions.md`, "Looked at, and fine: the reply call's shape"); what is left, by size:
     - The end-of-speech silence (`voice.json`): every 100 ms off it is 100 ms off every wake; tune on real speech.
     - Streaming the `spoken` field into TTS saves the reply's tail, about 0.3 s on a short reply; the clip is served by
       any pod, so the stream cannot live in the singleton's.
     - Fixed asks (the time, the date) answered by code. Something has to say an ask is fixed, and matching the
       transcript's words is ruled out, so it is a cheap classifier call run beside the reply call, whose `ask` field
       lets code answer and cancel the reply. It saves the reply call less the classifier's, on those wakes only:
       count how often fixed asks happen first, as an `ask` field on `Reply` logged as a count.
   - **The open-mic window after she speaks, barge-in, then speech streamed to TTS sentence by sentence.**
   - **"Hey Ashley" on the device:** `deploy/esphome/wake-words/hey_ashley` is the first Echo's only wake word and
     wakes on "hey/okay Ashley" in a real voice. Count its false wakes over a week of household use and tune its
     cutoff from them. A second model where bare "Ashley" wakes too scored 0 per hour on household audio and about 2
     on general audio; it waits for the two items below and needs retraining on the `hey_ashley` architecture.
   - **Audio from before the wake word.** A mention ("did you ask Ashley to turn off the lights?") reaches her as
     "to turn off the lights", which reads as a command; the words that make it a mention come before the wake.
     ESPHome (2026.10.0) streams from the wake only, so this is our own component: a rolling buffer of the last
     seconds of mic audio, sent ahead of the live stream on a wake. The server needs no change. The Echo has no
     PSRAM and each second of 16 kHz audio is 32 KB, so measure its free heap (`debug:`) before choosing the length;
     a Voice PE has room for several seconds. The buffer never leaves the device unless she wakes.
   - **A voice reply can decline or offer.** The reply's structured field, as in her Discord home: `reply`, `offer`
     (one short question when she overheard something she could do, "did you want me to?") or `none` (stay silent).
     After `none` the follow-up window stays shut, so a false wake records one utterance and no more. Log the field as
     a count; how often `none` is chosen on real wakes decides whether bare "Ashley" can wake her.
   - **Flash the remaining cubes** (M5Stack's factory Bluetooth-speaker firmware today) from
     `deploy/esphome/m5stack-atom-echo.yaml`: Wi-Fi, the API key and the OTA password from the deployment's secret
     store, decrypted into the build directory only for the build (`docker.io/esphome/esphome:2026.10.0 compile`). A first
     flash is serial (`esptool write_flash --erase-all 0x0 firmware.factory.bin`, 115200 baud, read in retried chunks,
     the factory image backed up first); later ones go over the air. Then a Voice PE per room that
     needs two-way.
   - Fits into: Channels (voice adapter) over the inference interface.
2. **Turn voice identification on** (`decisions.md`, "A voice names the speaker as a hint"). It runs in shadow:
   every wake logs `voice.speaker` and names no one. Memory gets little from satellites until it decides, because a
   wake has no speaker unless exactly one person is home.
   - Two household members are enrolled on the first Echo (six wakes each). Read a week of `voice.speaker`: the `best` and
     `second` scores, and `presence` agreement on wakes where one person was home. Set `floor` and `margin` in
     `voice.json` from those, and set `decides` once agreement holds.
   - Prints in the memory room, so a person sees and forgets their own; today a forget is the admin CLI's
     `voice-forget`.
   - Fits into: Channels (the voice adapter) and Memory's room (`app/ashley/api/memory.py`).
4. **The arrival greeting.** Its trigger is a wake (`decisions.md`, "Home Assistant wakes her; she decides"): an
   arrival automation's wake action and a wake rule for it. Left: the initiative score in code with its weights as
   data, replacing `WorthSaying` behind `Initiative`; greeting history as "already said" (her wake turns, a quiet one
   stored as `unprompted.QUIET`); a seeded roll between full, short and silent; and where she says it (a room's
   satellite or the hallway tablet rather than only the phone).
   - Fits into: **Initiative** (should she speak now, to whom, on which channels), over the wake adapter's turn.
5. **Web app, what is left.** Its rooms are built: sign-in, chat, memory (the facts she holds and where each was learned; a line
   dragged out of chat is input only, never shown back on the line), Devices (linked accounts, Discord linking,
   notifications, the household's devices) and the kiosk, with open screens kept current by Live. Left:
   - **Her mark shows where she is working when the page is not there**: a bench she changes from another channel (the
     satellite at the real bench) while the person's page is in chat. When she moves the page herself, her mark already
     goes with it, or waits on the bearing (`decisions.md`, "She moves the person's page herself").
   - **What we're working on**, beside her room's history: the person's open errands (item 7) and benches (item 11),
     each with its state (running, waiting on you, done), filled in as those items land. A quick question stays in
     the history; asking her to do or make something gets a place that outlasts the conversation.
   - **The page reads as talking to someone, not as one conversation's context.** The copy follows `app/web/voice.md`;
     what is left of that is her room's own strings, and the history shows what was said to her on every channel.
   - **The other settings rooms past tables.** Usage and Connections had their design pass (three clean-room
     designers, `ui-craft`: each sees only the room's real payloads, its API schema and its purpose, takes a different
     lens, and the best layers are mixed). Household and Devices get the same, and so does the admin settings page
     when the admin role lands. Connections' settings are still edited on their own page rather than in the opened row.
   - Fits into: Channels and Live.
6. **Choose models by measurement, and let several work together.** Search per task over model, params and prompt
   variant, `model-golf` style, across every wired provider; the spend ledger already has cost and outcome per task,
   provider and model. Params are reasoning effort, `max_tokens` and temperature where the provider has them, and
   the chosen values are kept as data in `app/ashley/inference/routes.json` beside the model. They matter: Gemini's
   chat route had to move to low reasoning effort because thinking consumed the 2048-token limit and cut replies off.
   The instrument is the house eval (`python -m ashley.evals house`); real conversations once she is live (the parity
   item) are a second pass, not a precondition. Item 8's prompt cuts land first, so the search runs on the trimmed
   prompt; item 8 stays its own item (ablation of the one shared prompt, where this picks per task). Add CLI providers:
   `claude -p` on the subscription (its OAuth token is in the deployment's secret store, but the image
   has no `claude` binary yet) and `opencode`. Then routes that ask several models at once and keep the best answer,
   and an orchestrator that picks a model per step for agentic work. Planning on a bench already goes to a slower,
   more capable model than chat's (`brainstorm`, Opus).
   OpenAI's tool use needs the Responses API: Chat
   Completions refuses tools with `reasoning_effort` (and `gpt-6.1-sol` refuses `none`), so only `gpt-6-luna` routes, at `none`, until an
   `OpenAIResponsesProvider` exists.
   The speech tasks get the same pass once her voice pipeline is live, research first: read what people report about
   ElevenLabs' v4 models (latency, quality, which voices and settings carry over) and the STT options before
   choosing what to golf, then measure first-audio latency and how she sounds on real replies.
   The first real `chat` case, run once the continuous history (item 15) carries earlier turns: a person asked her to
   add an item to the shopping list while the house was unreachable, and she couldn't. Hours later they said the house
   was back up, and she answered with no tool call, though the item was recalled and the shopping-list tools were
   offered. Pass: she adds it, or offers to, unprompted.
   The first real bench case: a household's arrival automations worked through with her on a bench (item 23). Read
   those bench talks as they happen (a review of her own conversations) and judge her planning, tool use and code;
   tune model, params or prompt for the bench's kind where she falls short, measured as above.
   - Fits into: Inference (new providers are Strategies; a multi-model route is a new method beside `generate`).
7. **Errands: an open-ended ask she carries out over time.** The one-shot errand is built (`decisions.md`, "What she
   could not do for want of a source, she does once it answers, and says so next time"); the rest is not designed. "See what you can do to help me wake up in the morning":
   she reads the phone's next alarm and sleep sensors, tries the lights or music near the alarm, keeps checking until the
   person is up, and may write a script or HA automation instead. A plan and its next check live in Postgres; a
   singleton under `Lease` runs due errands, so a failover mid-errand continues rather than restarts. She writes HA
   automations and scripts; the person who asked sees each one before it is enabled,
   and the errand carries on while one waits (cf-os's Gatekeepers queue an action for approval the same way).
   The HA-based assistant she replaces deliberately cannot, so this is a Tools provider of her own.
   A long bench job handed to a worker and told once its group settles is built (`decisions.md`, "She hands a bench job to
   workers and stays with the person").
   An errand can also be a slow ask answered at once and finished later ("look into X" gets "on it", then the
   research, a long tool call, anything). Its result comes back as a by-the-way ("I found something on
   that"): held on its errand, untold until her next reply to the asker carries it (as the designed slice
   does); Initiative may raise it unprompted, through the outbox. What lasts in it reaches Memory through the turn she
   tells it in. The answer after "let me check" that outlives the outbox's `stale_s` is stored on the thread today and
   logged `outbox.stale_dropped`; it is told at the next chance here.
   - **Standing errands: workers behind her, never beside her.** The aim is a team of bots on the backend, the way
     Rakazo has an inbox manager, a chief of staff and so on, but with her as the only face: nobody talks to a bot.
     A standing errand is an errand that never finishes: a method (a Skill document, one kind per job), what wakes it
     (a repeating reminder's rule, a house wake, a watch from item 35), the tools its turn may use (as
     `Reminder.tools` already names) and where what it finds goes (as `Reminder.route`). What it finds reaches a
     person the same way an errand's result does: held until her next reply to them, or raised through Initiative.
     A reminder whose turn acts is already the smallest one, so this extends Reminders and Skills rather than adding
     a bot store. Rejected: bots messaging each other (Rakazo's `message_bot`, with a hop counter against loops),
     until two standing errands actually need to; a sub-agent inside one turn (`look_up`'s pattern) covers handing off
     work.
   - Fits into: Initiative (when to act) over the orchestrator loop (`Inference.step` with its own task), Senses for
     checks, Tools for actions. A new kind of thing: durable plans with due times.
35. **Watches: a wake when what a read returns changes.** The first slice is built (`decisions.md`, "Watches wake her
    when what a read returns changes, until a condition or a time"): one kind, a Claude Code session. Its next slices,
    in order, are listed at the end of that section: a polled read-only tool, a Home Assistant subscription, the ledger.
    She can be woken by something changing that has no event
    to send her: a new email, a calendar event added or moved, a price, a page, a list. A watch is a read-only tool
    (`ToolSpec.reads`) with fixed arguments and an interval, run by the `wakes` singleton with no model in the check.
    It keeps a hash of the result, or of only the `track` fields of each item when the result is a list (the first
    field is the item's identity). The first check is a baseline and wakes nothing. A changed check wakes her turn
    with which items are new, changed or gone, and a failed check pauses the watch and says why. This is how Rakazo
    does "when something changes" (`packages/adapters/src/routine-watch.ts`), and it suits her better than it suits
    them: the deposit sense is already one particular watch over the Ledger, and becomes an instance of this. A
    calendar watch is a watch over `house_ask` `calendar.get_events`, which also gives the kiosk's glance its
    calendar source. **She arms one herself, mid-conversation**, as Claude Code arms a Monitor: "tell me when the
    dryer's done", "keep an eye on that package". A watch she arms carries an `until` (a structured condition over
    its tracked fields, never prose) and an expiry, and disarms itself once either is met. Each wake carries what
    changed since the last one, so the turn reads as part of a series. Arming one is a read, so it needs no OK, but
    what its turns may do beyond reading and speaking is agreed as a reminder's tools are (`arm_reminder`). For the
    house, a watch subscribes through HA's WebSocket (`subscribe_trigger`) instead of polling, held by the singleton,
    so she needs no automation installed to watch an entity. The session sense was the first to convert, and the one wanted
    first: a session is watched only after her own `claude_start` or `claude_prompt`, so a session the person
    nudged themselves finishes again unseen. With her tools, she arms it on any of the
    person's sessions ("keep an eye on that one"), and it stays armed past `done` until its `until` or expiry. Its
    end is a time, never "every shell has returned": a shell that hangs can keep a session alive for days, while
    Claude Code's Monitors expire on their own. Each
    finish or block is still her turn, which may act (`claude_read`, `claude_prompt`) or stay quiet.
    - Fits into: a new system, Watches, since it meets all four tests in `systems.md` (many callers; one question,
      "wake her when what this returns changes, until X"; polling and HA's subscription as two implementations behind
      a Null Object; it owns each watch's baseline and last hash). Its kinds are Type Objects (a read-only tool polled,
      a house entity subscribed, a herdr session, the ledger). `ashley.senses.deposits` is
      a copy of it today and folds in, deleted. It hands its wakes to the `wakes` queue (Senses), arms
      and disarms beside her reminder tools (Tools), and wakes item 7's standing errands.
36. **Mail.** She reads, searches, drafts, labels and sends a person's Gmail and Proton mail, and a standing watch
    over their inbox sorts it and tells them what matters. Designed in `decisions.md`, "Her mail is a port with two
    adapters, and Proton's runs as a leased Bridge". Every mail change goes through `Outside`. The parts, in
    order, each one MR with its own blind suite:
    1. OAuth secrets: built (the Google kind, its connect flow in the connections room, renewal by
       compare-and-set, `needs`). Trying it live needs the Google OAuth client in the deployment's secret store.
    2. The mail port and Gmail's read tools (`mail_boxes`, `mail_labels`, `mail_search`, `mail_read`): built, offered
       by the resource gate (part 3).
    3. Holders and resources: built (a connection handed to the household or taken back, each mailbox shared or kept,
       the gate by resource, the connections room's hand-over and sharing).
    4. Proton Bridge as a leased singleton: built (the record, the epoch fence, the singleton, the pod and its keeper, the
       room's login, sync state). Turning it on needs the cluster repo's part (`decisions.md`, "What the app needs from the
       cluster repo") and a digest for `MAIL_BRIDGE_IMAGE`.
    5. Proton's mailbox over IMAP and SMTP behind the same tools: built (`ImapMailbox` behind `RoutedMailbox`).
    6. Changes to mail: `mail_draft`, `mail_label`, `mail_send`: built on both adapters. Existing Google
       connections reconnect once for `gmail.modify`.
    7. The `mail_inbox` watch kind: built, with the `Later` check.
    8. The sort: built (`brief` and `standing` on watches, armed with `watch` and agreed with `arm_reminder`).
    - Fits into: Connections (holders, resources, OAuth), a new system Mail (the port and its adapters), Tools (a
      source), Watches (a kind), Channels' errands (the sort, as a standing watch).
38. **A browser of her own.** For the services with no API, a Chromium she drives in a gVisor pod: a session of
    minutes with egress, unlike a code run's seconds with none. She acts on the page's accessibility tree with
    element references checked again against a fresh snapshot before each action (Rakazo's `browser_snapshot` and
    `browser_act` over CDP), not by screen coordinates; passwords and card numbers are typed into the page by code
    over CDP and never shown to her. The browser's profile (logins, cookies) cannot live in the pod: it goes to the
    object store between sessions, so either site can resume. A person can take over the page from the web app.
    Rejected: recording a demonstration as a replayable skill (Rakazo's Teach is pixel coordinates plus the final
    window's title); her method stays a skill document she edits. Fits into: Code runs (a third pod kind beside
    code and media), Object store, Tools.
39. **Readers she sends out, several at once.** Asked for something that reads many sources ("a digest of my mail,
    calendar and the house every weekday at 9"), she builds it from what she has rather than from a feature made for
    it: a repeating reminder (`ashley.senses.wakes.Reminder`, with its `tools`) starts the turn, and that turn sends
    a reader per source. A reader is `look_up` made general: a sub-agent with its own context, given a brief she
    writes and a subset of her read tools, that returns a result cut to length in code. One call can send several,
    and they run at once, so the loop still sees one tool round (the concurrency `decisions.md` rejected was reads
    beside a change in one round; readers only read). The gain is context: each reader sees one inbox or one week of
    calendar, and she sees their pages. A reader's result is `outside` when any of its reads were (`decisions.md`, "A turn that has read outside words asks before it does anything consequential the person did not ask for"), so a
    change she then makes is an ask. Rejected: readers that message each other, or a leader they negotiate with;
    each hop re-reads its whole context, and work that does not split into independent reads is better done by one
    turn holding all of it. Fits into: Tools (`ashley.tools.look_up.LookUpTools` generalised, over `Only` and
    `Reading`), Inference (the step loop each reader runs); item 36 first.
P3. **The action judge, what is left.** The judge is built (`decisions.md`, "A turn that has read outside words asks before it
    does anything consequential the person did not ask for"). Left: (1) a move to trash or spam goes to the judge only when
    every target carries the provider's own spam or promotions label, which the adapter reads; (2) a page listing
    `outside_actions`, "what she did on her own and why"; (3) a live `python -m ashley.evals action-judge` run and the
    model-golf pick of the final route. Fits into: Mail (the adapter's labels), Channels (`Outside`), Inference.
8. **Golf the system prompt.** Count tokens per section first (Anthropic's `count_tokens`), then cut by ablation
   against the eval battery, keeping a cut only when nothing regresses (`model-golf`). Most of it is Home Assistant's:
   its tool definitions (4,315 tokens before her own house tools replaced them; measure again) and the device list in her tool instructions (about 1,080 tokens, the entities exposed to Assist). Levers: offer tool groups by kind, channel and place rather than all of them; household facts retrieved per message from memory
   (standing facts and recall) instead of the whole profile; format rules checked on `Reply` in code instead of carried as prose; and the
   persona's examples ablated one at a time (she repeats the presidents example nearly word for word). Latency too:
   the parity run had her at a median 2.8 s against HA's 1.9 s, two model steps for most house questions. The size
   costs tokens, not time: all 25 tools cost about 70 ms of first token, so the latency is in the steps.
   Attempted writes on the house eval's `read_only` cases are a metric of each cut: a cut that makes her reach for a
   change on a read ask regresses.
   Closing on an offer of help is now a field, `Reply.offer`, that nothing delivers (`decisions.md`, "An offer of
   more help has a field of its own"); the prose rule still carries part of it, so it stays. Naming the conversation
   kind needs no work (1 of 24 `command` replies, 0 of 40 `chat`). Both were measured through her real `respond`
   with live tools (12 long asks under `command` on Haiku and 20 under `chat` on gemini-3.8-flash, two replies each,
   Haiku judge with a structured field per tic). A probe without the live tools and HA guidance measures another prompt.
   She also invents household facts: asked to order food with nothing in memory, she added an unfounded remark about a
   household member's appetite (1 of 6 replies, Haiku on `command`). Measure how often first; a check in code needs a
   structured
   field on `Reply` (who the reply says something about), never a scan of its words.
   Wit is a metric of every cut, not only pass/fail: the owner senses less of her dry, Jarvis-like wit. A blind comparison
   (20 asks, 2 samples, a Haiku judge scoring within each ask) found no fade from `640fa65` to main (3.28 and 3.44 of
   5; plain-task controls 1.0-1.75), and carried history lowering it by about 0.3 on both trees that carry it. The
   earliest tree before that cannot be driven, so her Home Assistant era is not compared. The harness drives each
   tree's own `respond`.
   - Fits into: Channels (the turn loop builds the prompt) and Tools (what is offered).
10. **The hallway tablet, what is left.** Her page for it is built (`/kiosk`, decisions, "The hallway tablet is her
    page, paired as a device"): pairing, its conversation, who is home, touch controls as data, and her arrangement of the
    screen as a Workshop screen bench. Left:
    - **The device side:** the tablet opens `/kiosk` and is paired. Check that its browser keeps the screen on with
      motion and relaunches on a crash.
    - **Her voice and pictures through the page:** the page can play sound and video, so the tablet is one of her
      outputs in its own right, not through HA (its old HA satellite entity is unavailable for
      good, yet `HassBroadcast` still answers ok when nothing hears it: hide it from her or drop the entity). Her
      spoken reply and the outbox's announcements for the hallway play there, and she can put a picture on it when
      she judges it needed, with slight motion as things arrive and leave (none under reduced motion). The first case:
      the doorbell rings, she says "someone's at the front door" and slides the door camera's live feed onto
      the display; a swipe sends it away, and it leaves on its own once the door is answered or quiet. It goes where
      people are: the tablet when someone is home, and the open web page of someone who is away but using it (at
      work), the same line and feed. Presence already says who is home; what is missing is a record every pod on both
      sites can read of whose screens are open and in the foreground, since Live's viewers live only in the pod each
      screen reached (a row per screen with a short lease, the page reporting when it is visible).
      - Fits into: Channels (the kiosk adapter as an output, beside the satellites' `Announcer`), the outbox, Live,
        and Initiative over Senses for when a picture is worth showing unasked.
    - **She decides what the whole screen shows:** the kiosk is the first surface of item 20, in its glanceable skin;
      its fixed layout today becomes that item's fallback.
    - **Ears:** the tablet's own microphone, through the page: tap to talk is built; next a wake word run in the page
      (openWakeWord in WASM), which streams nothing until it fires. Talking through HA Assist on the tablet is her
      own pipeline lost.
    - **Glance sources:** calendar (HA's calendars, all shared) and a shared list of the household's, each through Senses
      or Tools, with their visibility as data; until then the page says not connected. A person's reminders are never
      one (decisions, "Reminders are wakes she sets for herself").
    - Fits into: Channels (the kiosk adapter) and Live.
11. **The workshop, what is left.** Benches where she and a person make something together, as Tony Stark's workbench
    does: either side changes a piece while the other watches it change, several benches at once, each kept until
    closed. The Workshop system is built (`decisions.md`, "The workshop"): benches, stored pieces, Commands with undo,
    the bench's talk on its own thread, Live, and her tools on a bench and for opening one from web chat; so is the client's room (`app/web/src/rooms/workshop/`), with the
    bench list, pieces laid out by order and size and animated by piece id, editing with conflicts, and the talk. A bench is not tied to the screen: the same project carries on at the
    real workbench (an Arduino, the bench camera, the room satellite) and back, so moving between chat, a bench and the
    physical bench is one continuous motion in the app, never a page swap, and the transitions are smooth. The world
    breaks in without breaking the bench: something she brings in on her own (a news item on
    the living-room TV, the doorbell) is talked about beside the work, and the bench is where it was afterwards. That
    arrival is Initiative's call over a sense, shown on whatever screen is in the room.
    - **The room, what is left**: a bench's screen becomes a surface of item 20, in a skin for making things (its layout
      and interruptions are that item's; its pieces stay this item's records, each shown through a component).
    - **Live kinds**: the first `live` entry in `kinds.json` (a camera, a print job), its body a source reference the
      client renders.
    - **Large pieces' streaming**: files beyond `max_bytes` (25 MiB, read whole into memory, so a range is cut from it), which a longer video or 3D may need.
      Fits into: Object store.
    - **Model inputs past `input_bytes`**: a model run's file pieces reach the pod in the job spec, at most 768 KiB in
      all (`runs.json`), so two ordinary STLs (about 600 KB each) cannot go to one run; the run is refused
      `bad_inputs`. The pod should get them from the object store with its script still offline (e.g. a fetching init
      container). Fits into: Runs (Sandbox), Object store.
    - **Simulations for model benches**: four ways to test a model beyond overlaps, each a model run with extra work
      whose results come back as report fields and ordinary checks. Built: parts carry a `role` from the closed list in
      `app/ashley/workshop/print.json`, and every model run's geometric print check (`deploy/cad/ashley_print.py`:
      overhang islands, the gap under each by downward ray casts, failed `print_gap` and `print_trapped_support` checks,
      support area and bed contact per part). Left, each shipping alone:
      1. `bench_simulate` with a tolerance fit (each check re-run at the corners of the ranges it rests on) and a motion
         sweep (a script's `moves()` stepped through, pairwise overlap per step), in the CAD image. It brings `sims.json`
         (each tool's profile, place and the roles it suits, refusing `mismatch` when none of the parts' known roles
         suits it unless asked again), `Run.sims`, and latest-run and prune keyed on (piece, purpose) so a sim run never
         replaces the design run on the card. Tolerance waits for the `bound` source being confirmed at both ends.
      2. A slice run (PrusaSlicer's CLI) in a new `ashley-sim` image: time, filament, support and bridge lengths, and
         the household's printer as a setting (its bed then feeds the print check's bed fit, skipped as `no_bed` until
         then). Starts with a spike: does it run under gVisor as uid 65534 on a read-only root.
      3. FEA (gmsh and CalculiX) as a bench job with worker `run`, `study()` declarations, `materials.json` with cited
         values, and the sandbox quota raised against node headroom.
      Fits into: Code runs (a sim is a run of the model piece, same runner, record and artifacts), Workshop (the `Run`
      command and the report's sections), Bench jobs (the `run` worker), Tools (`bench_simulate` beside `bench_run`).
    - **Choices beside measurements, what is left**: a measurements row may be a choice (what kind of thing something
      is, `decisions.md`, "Measurements are structured data"), a `reference` part names its form, and a fit against it
      rests on that row. Left, each shipping alone:
      1. **Each choice she sets is shown to the person once, by code**, beside her reply and never in it, whatever its
         source (a wrong form she set can be recorded as the person's): `Receipts.facts`, a non-piece Command
         `Surfaced(piece_id, rows)` read back from the log as `Point` is (a row is shown when some `Surfaced` names its
         current name and value), and a card line with the row's options as buttons, a tap being the person's Edit
         (`PUT /api/benches/{id}/pieces/{piece_id}/choices/{name}`, 422 off the options). `open_rows` skips a piece a
         tainted turn wrote, so such a bench's open list is empty: an outside piece gets an ids-only line in the moment
         layer (piece id, count of unconfirmed rows). The choice prose goes: "ask once, set asked" for choices leaves
         `3d.md` and `bench_specs`, and `bench_lead`'s "state each in a line" becomes "record each choice as a choice
         row, guessed, with its options".
      2. **Guessed numbers on the same path**: a guessed number a check of this turn's run is unconfirmed on is shown
         the same way; a migration turns each stored `asked: true` into a `Surfaced`, and the `asked` field and its
         prose go.
      3. **The kind renamed `facts`**: a data migration of the piece kind, and `measurements.json` becomes `facts.json`
         in the CAD helper; behaviour byte-identical.
      The replay measures with them: `form_declared` (her first model run's report names a form on every reference
      part), `facts_surfaced` (`Surfaced` rows per ask, by row kind), and `form_before_model` also true on a `Surfaced`
      of a reference part's form before her first model change.
      Fits into: Workshop (the measurements kind's row union, one non-piece Command), Code runs (`ashley_cad`),
      Conversations (receipts beside a turn).
    - **The bench order**, after bench polish, each its own change:
      1. **The herdr bridge** (item 12), on her own VM first.
      2. **3D**: she models in code with build123d, run server-side in Runs; a 3D view piece shows it, STL and 3MF
         leave through downloads, and she photographs the view with `bench_look` so the person can point out issues.
         Built: the CAD image and its `ashley_cad` helper (`deploy/cad/`), build123d as a Sandbox language with its own
         profile in `runs.json` `languages` (`CAD_IMAGE` and its quota are set on both sites), and the measurements
         kind (`decisions.md`, "Measurements are structured data"), and a run's GLB, STL and 3MF kept in the object
         store with download links and its report judged against the measurements, and the `model` kind, its 3D view
         and the four-view sheet a look photographs, and her method (the `3d` skill and the bench guidance naming the
         `model` and `measurements` kinds; the judgement of a fit is the bench turn's own), changing an existing model
         (an uploaded STL, 3MF or STEP file piece is handed to a model run, `existing(piece_id)` in `ashley_cad`), and
         finding an existing design on Printables and putting its file on the bench (`decisions.md`, "Printables is a
         look-up source"). Left: a dev run end to end on a real object, and what it finds; designs from Thingiverse
         (its API key is in the deployment's secret store) and MakerWorld, whose pages answer plain requests
         with a Cloudflare challenge.
      Fits into: Workshop (kinds, Commands), Conversations (the reaction's turn), Tools
      (`bench_look`).
    - **Possible later: a cooperative 3D editor** in the style of TinkerCAD, where the person drags shapes while she
      edits the same model, each edit a bench Command. No embeddable open-source editor was
      found; building one is a JSON tree of primitives evaluated in
      a Worker, est. 1.5-2.5k lines of TypeScript. TinkerCAD is more than basic shapes (solids and holes, groups,
      transforms), so it is large. Fits into: Workshop.
    - **Undo a whole turn**: Commands carry the turn that made them, and "undo that" undoes the turn's commands
      together, each still refused `changed_since` (Kanwas tags undo entries with an operation id).
    - **What a bench is for, beyond making**: redesigning something that already exists (an app from her codebase VM,
      item 21, put back on a bench), and taking apart anything a person is stuck on, so the two of them go through it
      together: an OSS project, a Wikipedia page (graph theory, say).
    - **Pointing**: she points at part of a piece while she talks about it. A pointer is a piece id plus a location in
      that piece's own terms (a line range in a `code` piece, a region of an image, a time in a video), so each piece
      kind defines its locations and shows its own indicator; her avatar may float over the bench to the place too. Built
      for a reader piece's passages (`decisions.md`, "The workshop"); the other kinds' locations are not.
    - Fits into: Conversations (a bench's talk is a conversation whose thread is the bench) and Tools (her edits are a
      tool provider, offered only on a bench). The pieces are the Workshop system.
12. **herdr bridge, remaining slices** (item 11's bench order, step 1). The bridge program is built (`bridge/herdr/`,
    its README sets it up) and registered to one person; one writer per slice:
    - **Last typed**: the bridge's transcript reader and sent-prompt ledger, for item 14's aside policy.
    - **A session as a live piece** on a bench (item 11's first `live` kind).
    - **A second machine of the owner's**: following the README, no code.
    - Fits into: Senses and Channels.
13. **MCP channel for Claude Code.** Sessions ask her things or tell her to remember them, as their user.
    - Fits into: Channels.
14. **Asides.** Unprompted wit through Initiative: daily cap in code, never during focus, no repeated lines. A remark
    in a Discord channel she was not pinged in is one of these.
15. **Her home on Discord.** `#ashley` in the household's server is hers to keep as she likes, a place of her own to
    decorate: its topic, pins and what she posts there. Tools that change the channel are scoped to her home channel
    and offered only on her own initiative, never in a reply, so a mention elsewhere cannot rewrite her channel. The server's
    owner grants Manage Channel and Manage Messages on `#ashley` alone, as a channel permission override.
    The same provider reads a channel: asked "what's up in this channel?", she sees only messages addressed to her, so
    a tool returning the channel's recent messages, offered when the message came from a Discord channel, lets her
    answer.
    How much she reads and when she speaks differ by channel:

    | | `#ashley` | Every other channel |
    |---|---|---|
    | Reads | every person's message, as turns (memory takes note) | when pinged; the read-channel tool for context |
    | Speaks | per message, a structured field on her reply: `reply`, `react` (an emoji) or `none`, erring to reply when asked anything | when pinged; unprompted only as an aside (Asides) |

    The field joins `Reply` for every channel; voice always takes `reply`. Rejected: reading every channel and replying
    when she has something to say, which is a model call per message and a rate a stateless call cannot keep, and would
    have memory distil every channel.
    - Fits into: Tools (a Discord tool provider beside Home Assistant's) and Initiative (when she tends it: a seeded
      roll and a score in code, never "now and then" in a prompt); her posts go through the outbox (`ashley.channels.outbox.Outbox`).
16. **Bench camera** as a sense, on request first.
17. **Split the API from the web client**, as sibling apps in the cluster repo do: the same
    image runs a second Deployment, `web`, that serves only the page's files, and both ingress paths (HTTPRoute and the
    tunnel) send the server paths to `app` and everything else to `web`. Each scales on its own, and the page still
    loads while the app or Postgres is down.
18. **Move the witness to its permanent machine at the witness site** when that arrives: copy the data directory, start it
    there, `etcdctl member update <witness member> --peer-urls=https://<new-ip>:2380`, and issue a cert for the new IP.
19. **Retire the `households.profile` column into standing facts**, once real standing facts exist to check the
    result against: who lives there, pronouns and pets become facts people can see and correct, written once
    through `Memory.apply` from the column's text; then the column, `set-profile` and the household panel's profile
    field go.
    - Fits into: Memory.
20. **Surfaces she composes.** She decides what a surface shows, setting the whole page by what she
    thinks matters most, placing building blocks as Homarr does with its widgets and integrations,
    only she places them rather than a person dragging. An integration is a source she already has (Senses and Tools:
    HA, Mealie, a camera); a component is a kind that is data with its own options (title, size, which integration,
    what to show of it: clock, who is home, calendar, controls, the conversation, a camera feed, a list…); a layout is
    component instances on a grid with that configuration, returned as structured output that code renders. She never
    writes markup. One catalogue and one layout model serve every surface, each in its own skin and for its own
    audience: the hallway kiosk (glanceable, shared; item 10), a person's web shell, and a workshop bench (item 11).
    A surface is what she lays out; a device is where it is shown. The kiosk is both at once, while a bench is a
    thread any device can open (the web, the physical workbench, the kiosk). Today the kiosk's layout is a Workshop screen
    bench (decisions, "The tablet's screen is a bench of the device's, laid out by her") that Surfaces takes over whole.
    The workshop holds several surfaces, one bench per project running, and a person moves between them; the kiosk
    is one surface that never switches, only updated in place, with interruptions over it.
    - **Interruptions, anywhere:** over every surface is a popup layer for something that interrupts (the doorbell's
      feed): a component covering part or all of the screen, tied to the event that raised it, sent to the surfaces
      where the people it concerns are (the shared record of open screens in item 10's doorbell case). She closes it
      herself once the event is over, or a person swipes it away or moves it sooner; a person's dismissal is recorded
      as an event her next plan reads.
    - **When a screen changes:** she re-plans on a period kept in code, by one singleton under the lease; an
      interruption takes over for a while and hands back; a minimum hold keeps it from churning. Each surface's fixed
      layout today stays as the Null Object for when her model cannot answer.
    - Fits into: Initiative (when a screen changes, period and events) and Live (a layout pushed to the screens),
      with component kinds as a Type Object in a data file and integrations being Senses and Tools. Itself a new
      system, **Surfaces** (what each surface shows now, and why), since nothing owns layout. Waits on Initiative
      (item 4).
21. **She runs code.** Two sizes, two places.
    - **Snippets**: `run_code` runs a script in a gVisor pod per run, recorded against the turn ("She runs a script in
      a gVisor pod of its own"). Waiting: the app's Deployment in the cluster repo mounting the projected token and CA
      (`SANDBOX_TOKEN_FILE`, `SANDBOX_CA_FILE`); until then she runs no code.
    - **Codebases**: a VM of her own running herdr, which she controls: she starts, prompts and closes its
      Claude Code sessions for background work and work needing more finesse (the owner's other apps), through item 12's
      bridge with her as the sessions' owner. The owner can step into any session at any time, but the VM is hers.
      Its Claude Code setup is synced from the owner's machines, so its sessions load the same skills, memory and
      CLAUDE.md as theirs. She works on any of the owner's projects, the cluster repo and her own, as Claude Code does
      with them: branches and MRs on the code host, main MR-only, CI's gates, never a force-push. She merges when the
      person working with her says
      so; whether she merges on her own initiative is an open question (below). A session's output is a live piece on
      the bench (item 11). The escapes that matter go through something trusted acting on what an agent wrote (CI
      and Flux), not through the sandbox, so what a merge may do is the boundary, and the MR is where a person sees it.
      Rejected: Managed Agents, billed per API token rather than the subscription and not watchable in herdr.
    - **Downloads of a repo beyond a snapshot** (a person's code host connection puts a snapshot on a bench) come through the
      Codebases VM.
    - Fits into: Tools (`run_code` is a provider, the sandbox its Strategy) and the Workshop (runs and their output
      are Commands and pieces); the VM's sessions are item 12's Senses and Channels.
23. **Her automations, the other two homes and the shadow view** (`decisions.md`, "The workshop"). Home Assistant as
    the home is built end to end: an automation piece, her read of the house's automations, her proposal and the
    person's Install and its Undo. Left: the first real use, an arrival routine the household already runs as a
    few HA automations, worked through with a person on a bench; HA's event stream as a
    sense (item 4), for a shadow view of when a piece would have fired beside what HA did; her own rule runner, a
    singleton under the lease whose rules survive a pod (decisions, "Work in flight survives its pod"), with an
    install to it as a second home for the same Install command; and an app of its own, through item 21's codebase VM.
    - Fits into: Initiative and Senses (triggers), the Workshop (the piece, the Install command and its carry-out,
      which a second home extends rather than copies), Home Assistant automations (the port), and errands' singleton
      runner (item 7), which the rule runner shares rather than duplicates.
24. **Home Assistant wakes her, the first real use** (`decisions.md`, "Home Assistant wakes her; she decides"). The
    slice is built end to end: the wake action, `/api/wakes`, the wake rule piece, the `wakes` singleton and her
    unprompted turn, which goes to the person's phone when `Initiative` lets it. Left, in order:
    - Set up the house, with the owner: a device for HA (`python -m ashley.channels.devices add`, then `house`), its
      token in HA's `secrets.yaml`, and `rest_command.ashley_wake` in HA's configuration posting `event_id`, `event`,
      `who`, `what` and `when` to `/api/wakes` on the LAN address. Then an arrival routine worked through on a bench: its automation
      with a wake action, installed, and its wake rule.
    - Only a phone hears her; a satellite, the tablet or Discord is item 4's choice of channel.
    - **The wake turn speaks on a named speaker**, next after bench polish: a wake rule piece names a speaker, and the
      turn's output plays through the household's HA media player for it. Then item 7 (errands) and item 6's cascade.
    - A wake rule is live once it is on an open bench, hers included; no person step stands between it and a turn
      (an automation's Install has one). A rule may need the person's approval as an install does.
    - Any household member's open bench supplies the rule, so another member's rule runs with your memory when the
      wake is about you: household trust, decided once a second person writes rules.
    - The rule names its event; nothing yet shows on the bench which installed automation sends it, or warns of an
      automation whose event has no rule.
    - Fits into: Initiative, the wake adapter (`app/ashley/channels/wake/`), the Workshop, and errands' singleton
      runner (item 7), which the `wakes` singleton should become one kind of when errands are built.
25. **The household's finances, past reading** (`decisions.md`, "A household connects its own services"). She reads
    Sure through the household's connection; what is left:
    - **Changes as approved Commands**: recategorising, a note on a transaction, a budget line, each one shown and
      approved by the person before it reaches Sure, never by her alone.
    - **Sure's MCP server** (`/mcp`, OAuth with scope `read_write`) in place of the REST reads, once writes are wanted
      and the connection can hold an OAuth grant instead of a key.
    - **Rotating `CONNECTIONS_KEY`**: a second version in the sealer and a pass that seals every row again under it.
    - Fits into: Tools (the money source) over Connections; writes through the Commands pattern the Workshop uses.
26. **Home Assistant from connections alone** (`decisions.md`, "A household connects its own services"). Every house
    consumer reads its household's `home_assistant` connection; the env's HA is seeded as household 1's at start.
    Left:
    - **Remove `HA_URL` and `HA_TOKEN`** once `homes.seed outcome=kept` shows on both sites' pods: the settings, the
      seed (`ashley.home_assistant.seed`), the fallback in `ConnectedHomes`, and the `app-home-assistant`
      ExternalSecret in the cluster repo's `kustomization/ashley-app/`, in that repo's own MR. That also ends a removed
      household 1 connection coming back at the next pod start. The house eval (`python -m ashley.evals house`) then
      seeds its scratch household's connection instead of taking the env.
    - Fits into: Connections and Homes; the settings and the cluster repo's ExternalSecret.

27. **When a house entity last changed.** `house_state` and the entity reads show a state with no time, so "the door
    is open" cannot be told from "has been open since morning". `ashley.home_assistant.house.State.changed` carries HA's `last_changed`; carry it through
    `ashley.tools.house_render` as an `ashley.stamp.stamp` (`decisions.md`, "Every time she is shown is a
    household-local stamp"), in the zone from `ashley.people.zone.zone_of`. Fits into: Tools and Homes.
28. **The unreachable line follows a turn to its bench.** When her thinking is out of reach after the held line, the
    line saying so (`ashley.channels.settled`) is stored in the conversation the turn began in, even when the page
    moved the turn to a bench's talk; it belongs where the answer will land. Fits into: Channels (the in-flight work
    already knows where a carried turn lands).

The next three make existing systems general (`engineering.md`, "Her systems are general, and she wires them"), in
this order.

30. **The ledger written to, and its events.** She may categorise through the Ledger (`ashley.ledger.ledger.Ledger`
    reads only today), and "balance below" and "bill due" become events her rules can match. Fits into: Ledger and
    Senses.
32. **Wake rules matched by who and what.** A wake rule matches on the event alone, and two for one event run no turn
    (`ashley.channels.wake.rule.rule_for`); an optional who/what match lets her keep rules per person or situation,
    the most specific winning. Fits into: Senses (wakes) and Workshop (the wake piece).
33. **A reminder said in a room.** A reminder's route can name a satellite's room or the kiosk, not only the phone or
    quiet (`decisions.md`, "Reminders she shapes"). A satellite's reply goes through the Outbox, which drops it when the
    satellite is not connected, so a room route first needs the reminder's own tries and its undelivered state, as the
    push has. Fits into: Channels (the voice adapter's `later.drain`, the reminder delivery record).
34. **Music on the house's speakers.** She plays, pauses, skips, sets the volume of, and searches music from the
    household's services (Spotify, Apple Music, YouTube Music and the like) on its speakers, by room or group: "play
    something mellow in the kitchen", "what's playing upstairs", "pause everything". Playback state is a read anyone
    may ask; what is searched and played comes from the asker's own account where the service is per person.
    - Fits into: Home Assistant (playback is a `media_player` service call, beside room speakers
      `ashley.home_assistant.media_player.play_for` and the general HA primitives of the `ha-general` work) and
      Connections (a service account is a person's own connection, as the code hosts are, read through a neutral
      music port with one adapter per service, so search results and now-playing are one record whatever the source).
      Check first whether the house's HA runs Music Assistant: it already holds Spotify, Apple Music and YouTube Music
      providers and plays to Cast, AirPlay, Sonos and ESPHome speakers, so one adapter over it may stand in for the
      per-service ones, leaving her own port with a single implementation until a service it lacks is wanted.
41. **Drop `outbox.agree` and `Outbound.agree`.** Receipts carry the proposal (`Receipts.proposal_id`); the column and the
    field stay for one release so a pod on the previous image can still send its Agree action. Drop both once both sites
    run the image that reads `outbox.receipts`. Fits into: Channels (the outbox).

## Open questions

- **Starting Claude Code sessions** from her (blocked today), and an in-cluster `claude -p` route as other
  apps use.
- **Merging on her own initiative** (an errand's MR, with no person working with her): decided once her codebase
  sessions (item 21) are in use and how they get used shows which way.
- **Other households** (a second household on the same deployment): channels, satellites and what crosses households.
  Each connects its own Home Assistant and Sure in the connections room (`decisions.md`, "A household connects its own
  services"), and each person links their own accounts (Discord); what each person may connect for themselves beyond
  that is open.

29. **The Workshop's install and the House port are one.** `ashley.home_assistant.automations.Automations` (list, read, write,
    delete, enable an automation, used by the Workshop's install, her bench automation tools and `automations_of`) is the
    House's `configs("automation")` and `write_config` with an enable switch. Move those callers onto `Home.house`, give the
    port the enable/disable and the entity-appeared wait, delete `Automations`, `RestAutomations`, `NullAutomations` and
    `automations.json`, and the second copy of the REST config paths with them. Fits into: Homes and the Workshop's carry-out.
