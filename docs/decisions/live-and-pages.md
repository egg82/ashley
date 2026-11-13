# Live and the person's page

How open screens learn what changed, and how her turn moves and follows the person's page.

## Open screens learn what changed through Live

Every open screen holds one Server-Sent Events stream, `GET /api/live`, fed by the Live service: Postgres LISTEN/NOTIFY,
since every pod on both sites already reaches the one writable primary, so a NOTIFY from any pod reaches every pod's
listener, and a failover is the listener reconnecting to the new primary. Each process holds one listening connection
and fans out to its own streams; nothing about a screen is kept beyond its open connection.

- **It carries ids and states, never text:** her state in a turn (`listening`, `thinking`, `speaking`, `idle`, named by a random
  turn token; a satellite's wake publishes `listening` until the transcript and `speaking` from handing over the reply
  to the room until an estimate of its playing, `voice.json`'s `playback`, since neither a satellite nor a room speaker
  reports its end), "this thread of yours got a turn", "a turn on this thread of yours ended with no reply", "this bench of yours changed" and "she moved your page to this
  room or bench". A page refetches what it shows; the feed is a nudge, not the data.
- **Who sees it is the channel's audience.** A turn on an `owner` channel (a DM, the person's web chat) is shown to that
  person only; one on a shared channel (satellites, a shared Discord channel, devices) to everyone signed in to the
  household. Neither says which room or who is talking. A shared channel's stored turns are announced only to the
  screen of a device that has one (the kiosk, `GET /api/kiosk/live`), never to a person's.
- **A device is a viewer of its own kind.** A person's screen is shown the household's shared events and their own,
  never a device's; a device's screen is shown the shared events and its own thread's turns, never an event of any
  person's channel. Both cookies stay strictly apart, so the feed has one route for each.
- **Losing an event costs a refetch, never a turn.** Publishing never waits; a stream that falls behind drops what is
  waiting for one `resync`, as does every stream when its pod's listener reconnects. A state carries `at_most_s`, since
  the `idle` can die with the pod that ran the turn. A stream ends after `stream_s` and the page reconnects, which
  checks its session again. Heartbeats every `heartbeat_s` (20 s) keep Cloudflare from closing it: its proxy read
  timeout is 125 s.
- **`speaking` is an estimate, from a satellite's wake alone.** No channel has a real playback signal: a satellite's wake sends it as an estimate (above), and no other channel does. A satellite plays the clip URL it is handed and
  does not report when it starts or stops; the clip route streams faster than real time, so its end is not the end of
  playback. No other channel sends `speaking`.
- **Which screens are open, and in the foreground, is a row per screen, in Postgres.** A stream records itself in
  `live_screens` (the `Screens` service, a Null Object that raises) and refreshes the row at its heartbeat; a row not
  refreshed within `present_s` counts as closed, and an opening prunes its household's rows older than a day, left by
  pods that died. A page makes a random token at load, opens its feed under it (`?screen=`) and reports whether it is
  in the foreground (the Page Visibility API) against it, on every change and every 30 s while the feed is up
  (`POST /api/screens/visibility`; the kiosk's `POST /api/kiosk/screen`). `Screens.open_screens` lists a household's
  screens with the last report, `visible` None until there is one, so any pod of either site can say which screens are
  being looked at. This extends Screens, which Live's streams already feed, rather than adding a presence record:
  Presence (who is home) and this (which screens are open) answer different questions and stay apart. A report names
  the reporter's own screen only: the person or device comes from the session, never from the body.
- **Rejected: polling per room.** Every open screen would ask every few seconds whether anything happened, mostly to
  hear no, and a screen would learn of a kitchen question only at its next poll.
- **Rejected: Redis pub/sub or an etcd watch.** Redis is a new stateful service on both sites with its own failover to
  get right, for what the database we already fail over does. The etcd is the referee's, sized and tuned for three
  members' votes across a high-latency link, and every pod would hold a watch on it; a user-facing feed has no business on
  the quorum that decides failover.
- **Rejected: the outbox.** It is a queue whose items are claimed once; a screen's events go to every screen.

## She moves the person's page herself

Where the channel is a page of the speaker's own (their web chat, a bench's talk: `Inbound.on_page`), she can take it
to another room, as going to the workbench and back to chat, rather than asking the person to go.

- **A tool, offered only there** (`ashley.tools.move_page.MovePageTools`, through `channels.turn_tools.for_turn`):
  `move_page` with `to` one of `chat`, `workshop`, `bench`, `memory`, `devices`, and `bench_id` for a bench, which must
  be one of the speaker's open benches, else a tool error and nothing moves.
- **A Live event of ids only**, `PageMoved` (the room, and the bench when there is one), shown to that person's own
  screens alone: never another person's, never a device's. Every open tab of theirs hears it and decides for itself.
- **Never move the page under the person.** A page follows at once with the shell's own flight (a fade under reduced
  motion), unless the person is in the middle of something: a text field they are in holds text, something is being
  carried, or a piece of the bench shown has an edit open (`app/web/src/shell/her/follow.ts`). Then her mark waits on
  the destination's bearing with an offer to follow or stay; going anywhere themselves ends the offer.
- **Her work at a bench the page is not on shows the same way** (`workingAway`, `benchChangedBy`). `BenchChanged` carries
  `by` (`her`, `person`, or none for a measurement), set where the command is announced from `By.person_id`, never
  inferred. A page not on that bench, told `her`, puts the same offer at the workshop bearing, naming the bench
  ("Ashley is working on …", the title read from the open benches); a tap flies there. The page never moves. The person
  going anywhere ends it, a newer change replaces it, and it never displaces a waiting offer to follow a move. A page on
  the bench shows her change on the piece instead (`Away.tsx`). Her `set_work` and an install's second event carry no `by`.
- **Her links to the rooms' own paths open in place** (a room, or `/workshop/<id>`), with the same flight; every other
  same-site path is still only its label.
- **Logs:** each move is one `tools.call` line with the room and bench id. Whether a screen followed or waited is the
  screen's own business and is not logged.
- **Rejected: moving without the waiting rule.** It yanks the page away mid-sentence or mid-drag.
- **Rejected: a link in her text as the only way.** It needs the person's tap, and she cannot follow up on it in the
  same turn.
- **Main chat knows the open benches** (`Catalogue.now` of move_page): a message about one of them moves the page
  there, and the work goes on in the same turn. Telling the person to go there is the defect.

## Her reply follows the page

A turn that takes the speaker's page to a bench is that bench's turn from the next model step on, and her reply is said
there, so the person is not left on an empty bench while her answer sits in chat.

- **The rest of the turn is the bench's.** `Inbound.moved_to` is the bench the turn has moved the page to
  (`ashley.tools.arrival.Arrival`, told by `open_bench` and `move_page` as they succeed). `ashley.channels.landing.Landing`
  is the turn's tool source: after a round that moved the page it rebuilds `turn_tools.for_turn` for the bench (its tools,
  its automation tools, `bench_run`; the same owner and open-bench checks as `move_page`), appends the bench's guidance to
  the system prompt's `moment` (the cached `stable` part is untouched), and switches the turn to the `brainstorm` limits.
  `moved_to` is saved with the checkpoint the moment the call that moved the page returns, before its result is, so a
  pod that resumes the turn is already there; it guides the saved system prompt again before its first step.
- **Where the reply goes.** With `Inbound.lands_on` set (the page is on a bench other than the thread's own), the bench's
  talk (`bench:<id>`, a `brainstorm` conversation) is given the person's ask as its first person turn, linked to the chat
  turn by `turns.carried_from` (unique, so a turn finished twice carries it once), then her reply answering it. The
  chat thread keeps the ask and gets, instead of her reply, a turn of hers with `turns.continued_on` = the bench id; its
  text (the bench's title; the page words the link as a quiet line, never as her words) labels the link the client draws (`ChatTurn.continued_on` on the wire, a link to
  `/workshop/<id>` that opens in place). Both talks are announced to the person's screens. If the bench cannot be read or
  the talk refuses the turn, the reply stays in chat (`respond.continue_failed`).
- **The bench shows her working from the moment the page lands.** The ask is carried into the bench's talk before the
  first step after the move (`continued.carried`, from `_Turn.arrive`), so the open bench reads the person's line owed an
  answer and her thinking dots under it, not an empty talk. A held line she says after the move is said in the
  bench's talk, answering the carried ask (`continued.held_on_bench`; `Work.say` renews the claim for a conversation
  other than the claim's); one said before the move stays in the thread the turn began on. So is the line that her thinking is out of reach (`ashley.channels.settled`), and the Live event names that talk. Before a step she is
  announced as thinking again once half of `thinking_at_most_s` has passed (`Showing.still_working`), so a longer turn is not
  shown idle while it works.
- **A cue drives a video piece's player and is no change to the bench** (`ashley.workshop.commands.Cue`, tool
  `bench_cue`). It is a Command so `decide` judges it like the rest: refused `not_video` on a piece whose kind's format is
  not `video`, `clip` or `audio`, `bad_cue` for a seek without `seconds` or outside 0 to `embed.MAX_START`, or a play or pause with
  `seconds`; accepted, it logs a `Cued` effect that changes no piece, not its version or `changed_by`, so a piece's last
  change and a bench's never move on a cue. It is never undone (`nothing_to_undo`) and the undo walk passes over it, as it
  does a Run: it stored nothing to put back. It is hers alone (the person's own controls drive the player directly and emit
  nothing), and not a person's change, so nothing that reads the person's commands to react to them sees one. It reaches
  the owner's open screens as `BenchCued` on Live, not `BenchChanged`, so no screen reads the bench back for it; Live
  keeps nothing for a screen that opens later, so an old cue is never replayed. The client drives a YouTube player by
  `postMessage` (its embed asks for `enablejsapi=1`), Vimeo's the same with its own messages, and a direct file's
  `<video>` directly; an embed that has not loaded drops the cue, and a browser that refuses `play()` before any touch
  leaves the video paused. Rejected: an undoable cue, which would put "undo" on something that changed nothing and make
  the walk name it; a stored playhead position on the piece, which a cue-and-seek would write on every command and a person's own scrubbing
  would contradict; reusing `BenchChanged` with a flag, which makes every screen read the bench back for a moment and
  makes "the person's change" depend on a flag each reader must remember.
- **A site or video piece is put up by a search result's number, or by a URL someone else supplied.** Her search shows
  no URLs, so a URL she typed for a reference was composed from memory. `bench_add` and `bench_edit` of a site or video
  piece take `result` (and, for a video, `start`) in place of a body, and the server writes the URL from the turn's
  `Results` (`ashley.tools.bench_reference`); the kind checks then run on that body as on any. An unknown number is
  refused `unknown_result`. A URL she gives as a body is accepted only if it appears, by exact string, in a person's turn
  of the conversation or in a site or video piece already on the bench (shelf included), else `unlisted_url`, which
  names the result path; a document's text is not checked and is not a source, or a link she wrote there would vouch for
  the next. `bench_replace` is refused on these kinds (their body is one URL, and a replace would skip the check); a change is a `bench_edit`. The numbers live in the turn's `Landing`, so a runner that resumes a turn has none, and her number is
  refused `unknown_result` until she looks it up again. Rejected: guidance alone (a prompt rule against writing URLs she
  was not given did not stop her); accepting any URL and checking it fetches (a composed URL that
  resolves is still not one she was given, and the fetch is the request forgery `read_page` avoids); matching URLs in
  her prose with a regex (the bench's body is the field the check reads).
- **A code or document piece can be a page's text, put up by the same result number.** look_up hands her at most
  `answer_chars` of a page, too little to put a long script on the bench.
  `bench_add` and `bench_edit` of a `code` or `document` piece take `result` in place of a body exactly as a reader
  piece does (the page must have been read this turn, `unread_page` otherwise), and the server writes the body:
  `Source: <url>`, then the page's text as `read_page` kept it, line ends made `\n`; a document has a blank line after
  the first line. The address sits in the body because these kinds have no field for it, so the piece's line N is the
  page's line N-1. A page longer than the kind's `max_chars` is refused `page_too_long`, and one longer than
  `page_bytes`, whose text ends early, `page_cut`; neither is stored cut. `read_page` reads a Pastebin paste
  (`pastebin.com/<id>`) and a GitHub file view (`github.com/<owner>/<repo>/blob/<ref>/<path>`) at their plain-text
  address (`ashley.tools.raw_source`, judged on the parsed URL's host and path), since their pages stripped to text
  lose the code's indentation and blank lines and carry the site's chrome (measured on a 371-line paste: 329 lines,
  none indented); the fetch is still `page_fetch`'s, public https only. No other host is mapped. Rejected: a new tool
  beside the reader mode, which is the same act on the same turn store; a reader piece for code, which shows text as
  paragraphs; a rule for every paste site and for gists (a gist's address names one file of possibly several, so a
  mapping would pick for her); mapping by regex over the page's text.
- **A reader piece is a page's text as she read it, and a point highlights a passage of it** (kind `reader`, format
  `reader`, family `stored`; `ashley.workshop.reader`). Its body is one JSON object of exactly `url` (https), `title`
  (the page's own, which may be empty) and `text`, lines separated by `\n`; `decide` refuses any other non-empty body
  `bad_reader`. It is `stored` because the text is the content: the piece keeps what she read when the page changes or
  goes. The server serves it as `BenchPiece.reader` (url, title, paragraphs) so the client derives nothing, and shows
  readable text with the original linked in a new tab (`rel="noopener noreferrer"`); the page offers a person neither
  adding nor editing one, since its text is the page as read.
  - **She makes one only from a page read this turn, by its result number.** `read_page`, and `bench_read_piece` on a
    site or video piece (`bench_page`, under a number of its own), keep the page's title and
    whole extracted text in the turn's `Results` (`results.Results.keep`), while its answer to the model stays cut to
    `page_chars`, and `bench_add` or `bench_edit` of a reader piece take
    `result` in place of a body, the server writing the body from that page (`bench_reference`). A result whose page
    was not read is refused `unread_page`, a body she typed `bad_arguments`, and `bench_replace` is refused. The piece holds the whole text up to its kind's `max_chars` (`kinds.json`), cut at the end past that, so a long page
    is read with her through `bench_read_piece` windows, not a fixed cap she cannot get past. The reading
    is look_up's, so she asks look_up for the page and to read it in one question. `read_page` still takes only a result
    number. Rejected: a new `bench_read_page` tool, which would be a second page reader beside the one that holds the
    request-forgery boundary; her pasting the text as a body, which would let a reader piece carry text and an address
    that never met.
  - **A location is a passage in the piece's own terms**: a paragraph (one line of `text`) and a range of characters in
    it, counted in code points (`reader.Passage`). Lines are stored, so a passage means the same words however a screen
    wraps the page. She names the words, not the numbers: `bench_point` takes an exact `quote` that must occur once in
    the text inside one paragraph, and the server resolves it (`reader.locate`), so a miscount can never highlight the
    wrong words. Rejected: offsets she counts, for the reason `bench_replace` rejects a line or offset range; an offset
    into the whole text, which the client would have to map to lines.
  - **A point is a recorded Command, not a Live event like a cue** (`commands.Point`, effect `Pointed`). A cue is a
    moment (play now) that is meaningless to a screen opened later; a highlight is a place the person must still see
    after a reload or on their phone, and Live keeps nothing for a screen that opens later. So it is logged and
    announced as an ordinary `BenchChanged`, and a read serves the latest accepted one of each piece
    (`BenchView.pointers`, from the log, never stored twice) as `BenchPiece.pointer` while the piece is still at the
    version it was made against (`Point.base_version`, refused `stale_base` otherwise), so a highlight never sits on
    words that moved. It changes no piece (not its text, version, place or `changed_by`), so the bench's last change does
    not move; it is never undone (`nothing_to_undo`) and the undo walk passes over it, as it does a cue. `Point` with no
    passage takes the highlight away: hers with an empty quote, the person's with `clear_point` from the page's
    "Clear highlight" (their Point, so it counts for no reaction of hers). Refusals: `no_such_piece`, `unknown_kind`, `not_reader`, `stale_base`,
    `bad_passage`. One passage per piece. Rejected: a Live-only event like a cue, which a reload loses; storing the
    highlight in the piece's body, which would make each point an Edit of the whole page's text, bump its version and
    be undone by Undo; an undoable Point; several highlights per piece, which nothing asks for yet.
  - **The client brings the highlight into view once for each new one**: inside the text's own scroll box, smoothly
    unless motion is reduced, and again when the piece first shows after a reload. Her mark lands on the piece
    ("pointed at this") and, scrolled out of view, the line at the foot of the pieces takes the person there, as for
    any change of hers. Other kinds (a line range of code, a region) will need a location of their own beside
    `Passage`; none is built.
- **A recipe the work uses is a recipe piece: the page's own recipe data, scaled to the bench's headcount in code**
  (kind `recipe`, format `recipe`, family `stored`, outside; `ashley.workshop.recipe`). A recipe page publishes its
  recipe as schema.org JSON-LD (name, yield, ingredient lines, steps, ISO 8601 times), a structured field, so nothing
  reads the page's prose for it: `page_fetch.page_of` keeps it on the page (`ashley.tools.recipe_ld`) before the
  scripts are stripped, `read_page` keeps it in the turn's `Results` and gives it to the look-up first, and `bench_add`
  of a recipe piece takes `result` and `serves` in place of a body, the server writing the body from that page as for
  a reader piece (`ashley.tools.bench_recipe_ref`); a page with none is refused `no_recipe`, and an edit changes
  `serves` alone or puts up another read page. The body is the page's lines as written plus `serves`; the amounts are
  derived on read: `ashley.workshop.quantity` reads the amount a line starts with (whole, decimal, fraction, mixed,
  vulgar, a number word, or a range of two, then a unit from `recipe.json` by whole-word alias, then a bracketed
  metric equivalent, which scales with it) and writes it back multiplied by `serves` over the yield's first number.
  A line with no amount, or whose number is a size joined by a hyphen (`15-ounce can`), is shown as written and marked;
  steps keep the page's numbers and say for how many. Her read of the piece (`bench_view`) and `BenchPiece.recipe`
  carry the same code-rendered numbers, drawn by `RecipeView.tsx`. A site piece already on the bench needs no second
  search: its read keeps the page as `read_page` does and gives the number. Every source on the bench is read when the
  turn's work reaches what it is for, and its amounts, steps and times carried into the plan, each number a measurements row with its source
  (`datasheet`, ref naming the piece), under the bench guidance. Rejected: the model scaling amounts or parsing
  ingredients; recipe data on the site frame record, which is per address and cannot hold a headcount; a field on the
  reader piece, whose body is text for pointing at; a person-side add, since a recipe is a page she read.
- **What is still open on a bench reaches every later turn.** The moment layer (`ashley.tools.bench_now.open_rows`)
  lists each guessed row of the bench's household-written measurements pieces, asked or not, however far into its
  piece, so a fresh bench turn starts from what is still to settle. A row marked asked is not asked again while the
  work goes on around it; when the step at hand depends on it, she says once that it is open and what she assumed, and
  goes on with the guess shown unconfirmed. A guessed choice row is listed too, by its label and value. Rejected: a new
  store of open questions, while unconfirmed rows and `asked` carry them.
- **Code on a bench is a piece.** A bench turn (the thread's own bench, or one the page moved to) is offered `bench_run`,
  which runs a code piece and records the run on the bench and the piece, and not the loose `run_code`, whose runs show
  nowhere on a bench. Rejected: offering both; she used the general one four times in a row and the bench stayed empty.
- **A fresh bench is led with the world's references too.** Beyond what the household already has, on a topic the world
  already knows she asks `look_up` for the best one or two references and puts them on the bench as site or video pieces by
  result number beside her draft, or none when no result is the thing itself (`bench_lead.LEAD`).
- **A message on a bench steers the running turn.** A bench talk runs one turn at a time (`Inbound.steers`, set by the
  bench's message route). A message is stored at once as any is; if another turn of that talk has work in flight
  (`InFlight.working`, the lock, so across pods), it starts no turn: its request answers pending and the running turn is
  handed it before its next model step, and before it would return its answer, as `<name> just said: <text>`
  (`channels.steering`, through `Steps.steer`). The turn's checkpoint records the handed turn ids with the entries they
  join (`Progress.steered`), so a runner that resumes it gets a message not yet handed once and one already handed not
  again. One final reply is stored, answering the first message. A message after the turn's work is gone starts its own
  turn. Every message is answered exactly once: her final answer carries the ids it was handed (`NewTurn.handed`) and
  is stored only while no other person turn follows the one it answers, checked under the conversation's row lock,
  which a person turn's store takes too; a message stored after the last hand refuses the answer (`Unhanded`) and the
  turn is handed it after her draft and goes on (`channels.answering`), and one stored after her answer sees no work
  and starts its own turn. A turn whose work is dropped with no answer (the model refused, a store failed) leaves its
  messages to a turn of their own: in the transaction that drops it, under the same lock, the oldest message after it
  gets work whose checkpoint says nothing is built yet (`Checkpoint.left`), claimable at once, so any pod's sweep
  answers it from the start and the rest are handed to that turn. A turn that began in chat and landed on a bench is
  that bench's running turn once its ask is carried there (`Checkpoint.carried`): `InFlight.working` counts the carried
  ask while the turn's work is unanswered in the talk, and the turn is handed the talk's messages after it.
  - Rejected: closing the window by handing again just before the store; any check outside the store's transaction
    leaves a smaller window, and two pods make it real.
  - Rejected: parallel turns on a bench (two turns contradicted each other: one said the code looked sound, the
    other that it had fixed real bugs). Chat keeps parallel turns.
- **Other destinations.** Only a bench has a talk of its own. A move to chat, memory, devices or the workshop list leaves
  her reply in the thread the turn began on; a bench-talk turn that moves to its own bench stays there; moving to a bench
  and then away again ends where the page is.
- **A bench she just opened is led, not asked about.** When the bench was opened in the same turn (`Arrival.fresh`) its
  instructions carry `ashley.tools.bench_lead.lead`: bring what exists onto the bench, draft, decide what can be
  decided and state it in a line, ask at most one or two questions that are genuinely the person's. Every bench talk's
  instructions say the work lives in pieces and that a change to something on the bench is an edit, not a near-copy
  added beside it.
- **A bench opens quiet**: a bench that opens full of pieces is too much at once. The turn that opens a bench adds at most
  `lead_adds` pieces (`bench_tools.json`, 2): `BenchTools` counts the accepted adds of a lead instance and refuses the
  next `ask_first`, a tool error telling her to say what else she would add and ask. Edits, moves and every other
  turn are not capped, and the count is of the turn, so a runner that resumes it starts it again. Rejected: a cap on
  the bench's pieces, which a person may fill as they like.
- **Her reply on a bench is two or three sentences, held in code.** `brainstorm`'s `reply_chars` (`turns.json`, 500)
  is the longest `Reply.text` the tool loop takes: a longer one is kept in the turn as her draft, followed by a note
  of the limit, and the model is stepped again, `tool_loop.RESHORTENED` times at most (`respond.reply_long`, ids and
  lengths), after which the reply goes out as it is; the forced answer after the last tool round is asked again the same way, still under tool choice `none`. A kind without the key has no limit. Guidance says the same
  (`bench_specs.INSTRUCTIONS`, `persona/kinds/brainstorm.md`) but is not what holds it. Rejected: `max_tokens` on the
  step, which also bounds a step that writes a piece and cuts the structured reply mid-JSON, which the provider
  reports as invalid output and fails over to the next route. Measured on the brainstorm route's model with a
  ten-sessions ask: caps of 150, 300 and 600 tokens cut off 3 of 3 replies, 1200 cut off 1 of 3, and the whole ones
  were 880 and 942 characters, so a cap low enough to bind fails the turn and one high enough to pass does not bind.
  Rejected: a hard cut of the text, which ends mid-sentence.
- **A bench talk has room to work.** The `brainstorm` entry of `turns.json` gives 24 tool rounds and a 300 s deadline,
  where Opus steps take 8 to 30 s and 8 rounds in 40 s ended turns before the work was done. After the held line she
  keeps working, each Command shown live as it lands, then a short reply. The turn is checkpointed and resumable as
  any other (`Work in flight survives its pod`), the final reply stored as her turn and announced as a `LiveTurn`.
- **Chat closes on its own clock.** A chat conversation closes 30 minutes after its last turn (`policy.json`), and the
  chat room then reads empty until the next message; time spent on a bench does not keep it open. The continuation is
  in that closed conversation, listed under Earlier.
- **Logs:** `respond.continued` (chat conversation, bench, talk) and `respond.continue_failed` (bench, reason); ids only.
- Rejected: the held line in chat after the page left it. The person is on the bench and sees nothing there.
- Rejected: storing the reply in both places. The person would read it twice, and the bench's talk is where the work is.
- Rejected: leaving the reply in chat and only linking to the bench. The page has already moved; the person arrives at a
  bench with no conversation and the answer is elsewhere.
- Rejected: copying the ask and matching it by text. The link is the `carried_from` field, so nothing reads words.
- Rejected: a faster model for bench talks. The bench route is already the largest model; the limit was the turn budget.
