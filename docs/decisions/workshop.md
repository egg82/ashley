# Workshop

Benches, the Commands that change them, her reaction to a person's change, and the check on her text.

## The workshop: benches of pieces, changed only by Commands

A bench is where she and a person make something together (open-work, "The workshop"). It belongs to its household and
the person who opened it (audience `owner`). Closing it puts the project away: it is kept as it was, takes no command,
and is listed among the person's closed benches (`GET /api/benches/closed`, most recently closed first), from where it
is reopened (`POST /api/benches/{id}/reopen`) as it was. Close and reopen are bench-level operations beside the
Commands, not Commands: they change no piece and are not undone. Rejected: a Close command in the log, which would
make Undo reach a closed bench's opening and closing.
The Workshop service (`app/ashley/workshop/`) answers one question: what is on this bench, and who changed what. Every
call names the owner asking, and anyone else's bench is the same 404 as one that does not exist.

A bench is a project, and may be months or years of work. What runs on it is for prototyping, testing and debugging
(a short trial or a shadow run, typically only while working on it), never for running things for real: nothing on a
bench is relied on. What a bench makes that is meant to last (an automation, a script she runs on a schedule) leaves
the bench for the system that owns that kind of thing, and the bench stays for the work that goes on.

An automation finished on a bench goes to one of three homes, which she proposes and the person approves: **Home
Assistant**, when it is simple enough to be reliable there (she reads and writes HA automations); **her own rule
runner**, when it needs more than HA can express, with HA for its triggers and its actions; or **an app of its own
in the cluster**, built through her herdr VM, when it is bigger than a rule. All three stay open to her, and she
chooses after planning it with the person on the bench. Home Assistant is built end to end (below); the rule runner and
the app path are open-work item 23.

- **A piece is work product with a kind**, and kinds are data (Type Object, `app/ashley/workshop/kinds.json`): a label,
  the longest body, a family, and a body format. `stored`: the body is the content, in Postgres (`document`, `note`).
  `live`: the body is a reference to a source the client renders (`site` and `video`, below). The format is `markdown`, `plain`
  (shown as typed) or `code` (source, with a `language`; only a code kind has one), and the client renders a body by
  it: a document is Markdown, a note is plain because it is a jotting, so a stray `*` or `#` stays as typed. The kinds and the bench's limits
  (`app/ashley/workshop/workshop.json`) are served at `GET /api/workshop/kinds`, so the client hard-codes neither.
  Rejected: a class per kind, which turns each new kind into code and a migration.
- **A bench's list entry and a piece carry what the Commands say, derived on read.** A bench summary has `piece_count`
  and `last_changed_at` (its last accepted command), and each piece of a read has `changed_at`, `changed_author` and
  `changed_person_id` from the command in its `changed_by`, however old, so who changed a piece never depends on
  `recent`. None of it is stored twice. Rejected: a counter or timestamp column on the bench, which a command could
  forget to keep.
- **Every change is a Command** (`ashley.workshop.commands`): add, remove, move, edit, run, propose, install, archive,
  restore, undo, rename, cue and point,
  frozen records in one
  closed union, each naming who made it, the person or her. One pure function, `ashley.workshop.decide.decide`, judges a
  command against the bench into an accepted change and its effect, or a typed refusal. Every command gets the bench's
  next `seq` and one row in the log, refusals included, so the log replayed from empty through `decide` reproduces the
  bench and every outcome; a piece's id is the `seq` of the add that made it. Her edits go through the same
  `decide` as a person's, so hers are as visible and as undoable.
- **An edit replaces the piece's title and body and names the version it was based on**; a stale base is refused
  `stale_base` and nothing is merged. The client reads the bench again and redoes the edit. Rejected for now: CRDT or
  OT merging. One writer at a time per piece is enough until two people (or a person and her) editing one piece at
  once is real, and a merge is then a new `decide` rule rather than a new store.
- **Undo is a command too, and walks back through the bench's commands.** An Undo names an earlier command and applies
  the inverse of its effect while the piece it changed is as that command left it: every later command on the piece
  was itself taken back by a later Undo (or is such an Undo), else it is refused `changed_since`. That also refuses a
  command already undone. The next press names the newest accepted command that is not an Undo and not yet undone
  (`ashley.workshop.undo_walk.next_undo` over the bench's last `undo_window` commands, served as `BenchDetail.undo_next` and in her
  `bench_read`), so pressing Undo again undoes the next-older command, and stops at one that cannot be undone, with
  its refusal (`changed_since`, or `full` when a removed piece has no room on the bench to come back), rather than
  reaching past it. Anyone's command can be undone by anyone: the person's Undo reaches
  her commands and hers reaches theirs. There is no redo: an Undo cannot be undone (`nothing_to_undo`), and the
  client's button never offers one. Rejected: a stored undo pointer or per-screen stack, which drifts when her changes
  or another tab's arrive; a redo stack, which nothing here needs yet; skipping past a command that cannot be undone
  to an older one, which would undo work the person has not seen unwound.
  - **Undo reaches back over a window, not the whole log**, so its cost and reach stop growing with a bench's age. The window is the last `undo_window` commands by `seq` (`workshop.json`, 200), refusals,
    Runs and Undos counted, because a press of Undo is itself a command and spends a slot: a long walk back reaches
    about half the window in changes. `decide` refuses an Undo naming a command with `seq < next_seq - undo_window`
    `nothing_to_undo`, and the read walks only those commands, fetched with a bounded query (`LIMIT`), so both agree on
    where the window starts. Older changes stay in the log and the replay; they can no longer be undone. It has its own
    number, not `recent_commands` (50, what a read shows): that is a display budget, and sharing it would cap a walk
    back at about 25 changes. Rejected: a window counted in accepted changes only, which needs the whole log read to
    find its start. Rejected: a new refusal reason; to her tools and the person an Undo too far back is the same as one
    naming a command that is not an undoable change (`nothing_to_undo` and its hint).
- **What is not on the layout now but may be wanted again goes on the bench's shelf** (a bench lasts as long as its
  project, so what it holds outgrows `max_pieces`). `Archive` takes a piece off the layout onto the shelf, the pieces
  after it moving up; it no longer counts toward `max_pieces`, keeps its text, version and runs, and takes no edit,
  move, run or remove (`no_such_piece`). `Restore` brings it back last on the layout at the size it had, refused `full`
  when there is no room. Each is undone by the other through the ordinary undo rules: undoing an archive puts the piece
  back at its old order (or last), refused `full` with no room; undoing a restore archives it again; a change before
  either is `changed_since` until the archive or restore is itself undone. The shelf is served most recently archived
  first (`BenchDetail.shelf`, the bench-tools' `bench_shelf`), and a shelved piece is a `bench_pieces` row marked
  `shelved`. Remove stays for what is not wanted at all. Rejected: a Restore naming its order and size, which a Move
  after it already does, as its own undoable step; removing straight off the shelf, which would need a Remove whose
  undo returns to the shelf; nothing asks for it yet, so a shelved piece is restored, then removed.
- **Layout is an order plus a size class** (`ashley.workshop.model.Place`): the pieces hold orders 0 to n-1, and each
  has `small`, `medium`, `large` or `full`, a share of the row the client maps to its grid. A move names the new order
  and size and the others shift, so every screen computes the same arrangement and animates from the old one by piece
  id. Rejected: grid cells, which make every move a collision problem across screen widths that order-plus-size
  leaves to the client. The place is its own small value so that Surfaces (open-work item 20) can own layout later. A
  device's screen is laid out with the same Place.
- **One transaction per command.** It locks the bench's row, decides against the stored pieces (and, for an undo, the
  stored effect it names), writes the log row and the changed pieces, so commands racing on one bench from any pod of
  either site are decided one after the other. Tables `benches`, `bench_pieces` (the bench as it stands) and
  `bench_commands` (the log, the command and its effect as JSON); every row carries `household_id`.
- **Live says a bench changed, by ids only.** After an accepted command commits, a `BenchChanged` (bench id and `seq`)
  goes to the owner's screens alone; a page showing the bench reads it back. A refusal changes nothing and says nothing.
- **A bench's talk is a conversation whose thread is the bench**, `bench:<id>`: a `brainstorm` conversation through the
  shared turn loop, as web chat is, owner the speaker and its only audience, held answers stored as her turn and
  announced as a `LiveTurn` for that thread. Any channel that can name the thread can carry it later.
- **A bench shows its whole talk, not only the open conversation.** A conversation records the thread it started on
  (`conversations.thread`, written by `for_thread`), so `GET /api/benches/{id}/conversations` pages every conversation on `bench:<id>` through the same
  `history_page` her room's history uses, and the page shows them above the open one under the same dividers
  (`Earlier`). Only the bench's owner reads it, anyone else's id is 404, and a conversation reads by its id under the
  taking-part key. A closed talk is not an empty one: a bench lives for days, longer than a brainstorm stays open.
  What she carries on the bench's next turn is unchanged: the owner's latest turns across conversations, this bench's
  closed talk included, since each was private to the owner. Rejected: a second history route for benches, and
  never closing a bench's conversation.
- **Large pieces live in S3 on both sites' NAS** (family `large`, kinds `image` and `file`; `ashley.files`; each
  site's NAS S3 endpoint, the ones WAL-G writes to). The piece's body is a JSON
  descriptor of its bytes (`ashley.workshop.stored_file`: `sha256`, `size`, `media_type`, `name`), capped by the kind's
  `max_chars`; the bytes are one object, `bench/<household id>/<sha256>`, in one bucket. A write goes to every endpoint
  of the file storage connection's address at once (this site's first) and counts when one took it; a read takes the first endpoint that has
  it; a singleton under the lease (`ashley.files.repair`, every `repair_interval_s`) copies what one site holds and the
  other lacks under the bench and look prefixes, and does nothing while a site cannot be listed. So both sites reach the bytes with no shared mount, and
  an upload made while a site is down is whole on both within an hour of its return. The Postgres row is the index and
  the log; there is no table of copies. Keys carry the household, so the same file in two households is two objects and a
  link to one reaches only its own. The store is a service behind the locator (`ashley.files.store.ObjectStore`, a Null
  Object that raises `StoreUnavailable`, `ashley.files.s3.S3Store` over one endpoint, `ashley.files.mirror.MirroredStore`
  over several, `ashley.files.memory.MemoryStore` for tests), so swapping the store changes only the adapter.
  - **Bytes no piece names are swept** (`ashley.files.sweep`, a singleton under the lease of its own, every
    `sweep_interval_s`): the repair's listing, extended to carry when each key was last written, is compared with what
    benches name (`ashley.workshop.file_references`: large pieces on any bench, shelved included, and those in the last
    `undo_window` commands of a bench's log, since undoing a Remove needs the bytes). A key is deleted from every site
    only when it is unreferenced, younger than `sweep_grace_s` on no site (an upload in flight has bytes before its
    piece), and found so by the pass before too; those findings are the rows of `file_orphans`, not pod memory, so the
    next pass may run anywhere. A refused or failed upload and a removed piece's bytes both end there. A site that
    cannot be listed or deleted from is skipped for the pass; the others go on, and a copy left on a down site is
    deleted once it is back (repair may copy it across first, which only costs one more pass). The references are read
    after the listing, so a piece committed during a pass is seen; what remains is the seconds between that read and
    the delete, which the grace and the second pass make a retry of old bytes' problem alone. Rejected: a second lister
    (the sweep goes through `ObjectStore.listing`, which `keys` is defined by); candidates held in memory, which a
    failover or rollout loses; deleting on first sight, which a put racing the pass would lose.
  - Rejected: an NFS PVC per site. It is two unreplicated filesystems, and mounting both sites' exports from each means
    `hard` mounts that hang a surviving site's pods in D state when the other site goes, or `soft` mounts that trade the
    hang for corruption. Rejected: MinIO bucket replication as the mechanism, whose lag shows only when a site is read
    (as WAL-G's record says). Rejected: refusing an upload unless both sites took it, which stops uploads exactly when
    a site is down; the repair closes the gap. Rejected: Postgres `bytea` or large objects, which put files through
    WAL and both sites' replication. Rejected: a table of which site holds which object, which the listings answer.
- **Her tools on a bench are the person's Commands, made by her** (`ashley.tools.bench_tools.BenchTools`, offered only
  on the bench's talk): `bench_read` (every piece with its id, kind, title, version and place, its body cut to
  `read_body_chars` with `body_cut` saying so, and the latest commands by seq), `bench_read_piece` (one piece, a
  window of at most `piece_chars` from an `offset`), `bench_add`, `bench_edit` (with the version she read),
  `bench_replace`, `bench_move`, `bench_remove`, `bench_archive`, `bench_shelf` (the shelf's ids, kinds, titles and
  versions; `bench_read` says how many it holds as `shelved`), `bench_restore` and `bench_undo`.
  She arranges what she adds in the turn she adds it (order by how a reader takes the pieces, size by what each is),
  tidies a bench that has grown untidy once, and leaves a tidy one alone. `bench_read` gives each piece
  `last_changed_by` (`you` or `person`, from the command it last changed by), and her guidance has her fit her pieces
  around a person's and never move or resize one. The guidance is instruction data (`bench_specs.INSTRUCTIONS`). Rejected:
  a refusal in `decide` for her moving a person's piece, which would make the Workshop judge whose layout it is.
  Each builds the Command a person's route builds, `by` her, through `Workshop.apply`; a refusal comes back as a tool
  error naming the reason (`stale_base`: read again and redo). An edit replaces the whole body, so she may edit only a
  version she read or wrote whole in the same turn; anything else is refused `unread` before the Workshop sees it, and
  a piece longer than `piece_chars` she changes with `bench_replace`: an exact `old` snippet that must occur once in
  the whole body, and a `new` in its place, on a version she has read any window of. It builds an ordinary `Edit`
  from the current body, so the version check, log, undo and replay are the Edit's and there is no new Command. A
  snippet found nowhere or more than once is `bad_arguments` and changes nothing. Rejected: a line or offset range,
  which names a place and silently edits the wrong text when the body shifted or she miscounted, while a snippet
  names the text itself. Rejected: scanning her prose for fenced code to make pieces, since behaviour keys on fields;
  code she writes for the bench goes in through `bench_add` with kind `code` (`kinds.json`, format `code`), her
  choice, and the instructions tell her so. A code kind carries one `language` (`text`); a language per piece would
  need a field on every piece and is not built. Tunables: `app/ashley/tools/bench_tools.json`.
- **A code piece is run by a Run command** (`ashley.workshop.commands.Run`): the piece, the version the runner saw and
  a language the sandbox runs. The person's Run button (`POST /api/benches/{id}/runs`) and her `bench_run`
  (`ashley.tools.bench_run.BenchRunTools`, on a bench's talk while a sandbox is wired) both go through
  `ashley.workshop.run_piece.run_piece`: `decide` judges the Run (`no_such_piece`, `unknown_kind`, `not_runnable` for
  a kind whose format is not `code`, `stale_base`) and it is logged, then the body runs once through the one runner,
  `ashley.runs.once.run_once`, recorded in `code_runs` against that command (and her turn, for hers), and the owner's
  screens are told again when it has ended. A run the sandbox cannot take (a language it does not run, a blank piece,
  a body over `max_script_chars`) is refused before anything is logged, since `decide` does not know the sandbox.
  - **What it gave is shown on the code piece**: each piece of a read carries its latest run (`BenchPiece.last_run`),
    read from `code_runs`, never stored twice; `bench_last_run` gives her the same. Rejected: an output piece added
    by the run, which takes a slot on the bench, is editable text posing as a result, needs an undo of its own, and
    on the next run must either pile up or overwrite a piece someone may have changed.
  - **The files go back in, and no pod keeps them.** A run starts with the files left by the piece's latest run that
    ran to its end (outcome `ran`, any exit code); one stopped, killed or lost part way may have left them half
    written, so it passes nothing on and the one before it still does. They are already within the runs' file limits.
  - **A run is never undone.** Its effect, `Ran`, changes no piece (not its version, place or `changed_by`); Undo never
    names it (the walk passes over it as over a refusal), an Undo naming one is `nothing_to_undo`, and it never makes
    the change before it `changed_since`. Undoing an edit leaves the last run, and the files it left, as they are.
    Rejected: refusing the Undo of a run, which would stop the walk there and strand every change before it.
  - **A piece keeps two runs, and a run goes when a newer one replaces it.** Recording a bench run's result deletes,
    in the same transaction, that piece's finished runs but for its latest run, its latest that ran to its end (the
    one its next run's files come from) and the one just recorded, and logs `runs.pruned` with the bench, piece and count. So a bench's runs stay
    at about two a piece however long it lives, and a removed piece's last two stay with the bench. A run with no result yet is work in flight and is never
    pruned, so two runs pressed close together both keep their results; the one just recorded waits for the next
    finish to go. A run lost with its pod never gets a result and stays, as the "No result recorded" row it is.
    A run asked for by a chat turn is never pruned: it is shown in its conversation and carried in history, and goes
    with its turn (`ON DELETE CASCADE`); nothing deletes a conversation or a bench today. Rejected: a retention job on
    a timer, a second thing to keep running; an age limit, which would drop the files a long-idle piece's next run needs.
  - **It survives its pod as any change does**: the command is logged before anything runs and the run recorded
    before it starts, so a pod that stops part way leaves an accepted Run with no run (it never started) or a run with
    no result (shown as "No result recorded"); neither is run again, and her `bench_run` is a change to the tool loop.
- **A site or video piece is a reference the page frames, its body checked by the server** (kinds `site` and `video`,
  family `live`, `ashley.workshop.embed`). A site's body is one https URL that is not a YouTube or Vimeo page, which is a
  video piece, hers or the person's (no credentials, at most 2000 characters; whitespace
  inside it refuses it, whitespace around it is trimmed and the body is stored trimmed, a whitespace-only body being the
  empty one; a video's `url` field is trimmed the same way, in the stored JSON); a video's is a JSON object `{"url", "start"}`, `start` whole seconds, the field a pointer into the video
  will name; a `start` in the URL (YouTube `t=` or `start=`, Vimeo `#t=`, as seconds or `1h2m3s`) is the start when the
  body gives none, and the body's `start` wins. An Add or Edit of anything else is refused `bad_site` or `bad_video`; an empty body is a draft. The video's
  URL is a YouTube or Vimeo page, shown through the provider's privacy embed (`youtube-nocookie.com`,
  `player.vimeo.com`, an unlisted video keeping its hash) derived from the parsed host and path, or a direct media file by its path suffix; the server
  serves the result as `BenchPiece.video` (`provider`, `url`, `embed_url`, `start`) so the client derives nothing, and
  nothing autoplays. A site is an iframe with `referrerpolicy="no-referrer"` and a sandbox of `allow-scripts
  allow-forms allow-popups`, never `allow-same-origin` and never `allow-popups-to-escape-sandbox`, so a framed
  site cannot reach the page's cookies or storage and a window it opens stays sandboxed too; the cost is that a site reading its own cookies loses them. A provider's player gets
  `allow-same-origin` too (its own origin, a fixed host) and `strict-origin-when-cross-origin`, which YouTube requires.
  Many sites refuse framing and the page cannot detect it, so "Open in a new tab" is always shown. The app sets no
  CSP, so no `frame-src` changed.
  **The server decides whether a site frames, from its headers, and the page shows a card when it does not.** A site
  piece is served as `BenchPiece.site` (`frameable`, `title`); `frameable` is a measured true or false, or null for
  unknown. The first read of an open bench that finds a site address with no measure asks the site once in the
  background through the `FrameProbe` service (`ashley.workshop.frame_probe`, implemented by `ashley.tools.site_probe` over
  the page reader's request, the same request-forgery checks, so the workshop and the API make no request themselves), decides
  from the final answer's status and headers alone (`ashley.tools.frame_policy`: a non-2xx status, `X-Frame-Options` `DENY` or
  `SAMEORIGIN`, or a `frame-ancestors` that names neither our origin (`public_url`), `*` nor `https:`; a
  `frame-ancestors` overrides `X-Frame-Options`, as in a browser), records it in `bench_site_frames` by bench and address,
  and tells the person's screens the bench changed (`BenchChanged` with `seq` 0). An address that gets no answer is
  recorded unknown and not asked again until it leaves the bench and returns; the record is dropped once no piece holds
  the address. Only `false` makes the client show a card (host, the page's title, "Open in a new tab") in place of the
  frame; unknown renders as ever, the frame and the link. Logged as `bench.frame` with bench, piece and outcome. Rejected: reading the
  page's text to guess, or a client probe (a refused frame cannot be told from a slow one); a column on the piece (the
  fact belongs to the address, and the piece's versions would churn); measuring on every read. She makes them with the ordinary piece tools; a person adds one from the Add card with an
  address (and, for a video, a start as seconds or `m:ss`), which the page shapes into the body and the server judges. Rejected: regex over a pasted URL in prose to pick a provider; a `provider` field she
  would have to get right, which the host already says.
- **An automation piece is Home Assistant's own automation config, as JSON the code checks** (kind `automation`,
  format `automation`, `ashley.workshop.automation_config`): one object of HA's field names (`alias`, `description`,
  `triggers`, `conditions`, `actions`, `mode`, and `max`, `max_exceeded`, `variables`, `trigger_variables`), each of
  its type, every trigger, condition and action an object, with no `id` (the install owns it). An Add or Edit of
  anything else is refused `bad_automation`; an empty body is a draft. What a trigger or action means is HA's to judge
  when it is written. The room reads it as When, Only if and Then, one line per item, with the JSON folded under it,
  and edits the JSON in the ordinary editor. Rejected: YAML text, which code cannot check without HA's schema and
  which turns every edit into a parse; a form, which nothing needs yet.
- **Installing is her Propose and the person's Install, both Commands** (`ashley.workshop.commands.Propose`,
  `Install`). She proposes a piece at the version she read (`bench_propose_install`), with whether it is enabled and
  an old automation to turn off; `decide` refuses `not_installable`, `stale_base` or `incomplete` (no alias, trigger or
  action), and a Propose changes no piece and is never undone, as a Run. The room shows her proposal on the piece
  (`BenchView.proposals`, read from the log) with an Install button; the person's `install` command names it, and is
  refused `no_proposal` (not this piece's, or installed already) or `stale_base` (the piece changed since). Only a
  person installs and only a person undoes an install: hers are refused `needs_person`, so every write to the house,
  either way, is the person's. Her tools write nothing outside the bench.
- **An accepted Install is carried out on the house after it is logged** (`ashley.workshop.install_piece.carry_out`,
  called by the commands route, which answers once it has ended), recorded in `bench_installs` before its first
  write and again when it ends (`ashley.workshop.installs.Installs`): it reads what HA holds under the piece's id and
  whether the old automation is on, records that, writes the config, turns it on or off as proposed, then turns the
  old one off. A pod that stops part way leaves an accepted Install with no record (nothing was written) or a record
  with no ending (shown as such: check the house); neither is carried out again, and a second carry-out of one command
  writes nothing. HA refusing the config ends it `refused` with HA's own message; HA out of reach before anything was
  written ends it `failed`, touching nothing. A new automation is on for the moment between its write and its turning
  off; rejected: HA's `initial_state`, which forces its state at every HA restart.
- **A piece is installed under one id, `ashley_bench_<bench>_piece_<piece>`**, so its first install is fresh and every
  later one an update of the same automation. An install never writes over an automation under that id that no
  earlier install of the piece wrote (`failed`, nothing written), since a test database's bench shares the id with
  production's. Rejected: a random id kept on the piece, which a later install would have to look up and a race could
  fork.
- **Undoing an install takes it back from that record**, as an `Uninstalled` effect carried out the same way: a fresh
  install is deleted (nothing of it is left behind); an update has the config and on/off state HA had before written
  back; the old automation is turned on again only if the install found it on. An install that wrote nothing has
  nothing to take back. Rejected: disabling instead of deleting a fresh install, which leaves dead automations in
  HA's list for every trial.
- **She opens a bench from the person's own web chat** (`ashley.tools.open_bench.OpenBenchTools`, offered only there,
  the speaker known): `open_bench` with a title of hers, returning the bench's id and the room's path,
  `/workshop/<id>`, which her reply links to; the link opens the bench in place, and she can take the page there
  herself ("She moves the person's page herself").
- **A person opens a bench from the list by asking** (a field that asks "What are we making?" implies she answers what is asked). `POST /api/benches` takes an `ask` (the talk's 1 to 4000
  characters), a `title`, or both. An ask is the person's first message in the bench's talk, whole, and she answers it
  in a bench turn that leads, as on a bench she opened herself: the route builds the talk's `Inbound` with `lead`
  (`ashley.api.bench_opening`), which `channels.turn_tools` reads as it reads a fresh `Arrival`, so there is one lead
  and one turn path. The turn runs on its own after the route answers, and the bench's id is its `source`, so a bench
  is one turn. A title alone opens a bench and starts no turn.
- **A bench is named by a Command.** `Rename` (`ashley.workshop.commands.Rename`, her `bench_rename`) sets the bench's
  title, refused `bad_title` when empty or past `title_max_chars`; its effect `Renamed` changes no piece, and Undo
  names the title back (`changed_since` once a later rename stands). A bench opened with only an ask is titled from it
  (`ashley.workshop.provisional.provisional_title`, cut at a word with an ellipsis) until the lead has her rename it
  in her first turn. The person's own rename has no route. Rejected: asking the model for the title in the
  open request, which would make opening wait on a model call; a title column she writes outside the log, which
  would be neither undoable nor on Live.
- **Logs** carry bench, command and piece ids, the command's type, the kind, the author (`person` or `ashley`) and the
  outcome (`workshop.opened`, `workshop.closed`, `workshop.reopened`, `workshop.command`, an install's
  `workshop.install_started`, `workshop.install_finished` and `workshop.install` with its automation id, and her
  tools' `tools.call`); never a title, a body or an automation's config.
- **The bench is in her prompt.** Each turn's moment carries the bench as it stood (`Catalogue.now`). An
  outside-kind piece shows only id, kind and version, so the view never taints. Rejected: bench_read every turn
  (a model step of about 4 s, and a taint whenever a file is on the bench); the view in `stable` (cache churn).

## She reacts to a person's bench change

When a person's commands on a bench stop for a pause, she gets one turn on that bench and may say something or stay
silent (as tldraw's agent is handed the user's changes since its last request). Fits into: Initiative (whether it
goes out), the `wakes` singleton's lease and the shared turn loop (the turn, its inflight row and resume), and the
Workshop's log (what changed); it adds no singleton and no turn path. Rejected: a wake row per reaction, which would
store a debounce the command log already is; a timer per bench in a pod, which a rollout loses.

- **The trigger is derived, not stored.** `Workshop.unseen` finds the open benches where a person's accepted commands
  came after the last she has seen and the newest is at least `pause_s` old (`bench_react.json`). Her own commands, a
  refusal and a closed bench never count. The `wakes` sweep (under the `wakes` lease) reacts to up to `batch` of them,
  so any pod on either site does it, and a killed one loses nothing: the next sweep finds the same state.
- **The last command she has seen is the newest `bench_reactions` record's `to_seq`**, not a column the bench keeps,
  because the same rows bound how often she reacts. It is written once the turn is handed to the loop. Her next
  reaction is handed only the person's commands after it, as `#seq type kind piece` (ids and kinds, at most `listed`,
  with a count of the earlier ones), in the stored household turn; nothing is handed twice.
- **A reaction handed in twice is one turn.** Its `source` is the bench and the last command handed
  (`bench_react:<bench>:<to_seq>`); the turn loop's inflight row makes a killed runner's turn finish on any pod
  ("Work in flight survives its pod"). The turn is `unprompted` on the bench's thread with the owner as speaker and
  `author` `household`; what she is told to do reaches her only as the turn's `note`.
- **A reaction holds like a person's turn**, from the explicit `Inbound.watched` its adapter sets, since the person is on
  the bench's page by construction and watched the work start. Her aside goes out as a held line past `hold_after_s`
  and stays her turn on the talk; the answer is stored after it and, with `says` none, as her staying quiet,
  which hides only that turn and the household turn it answers, never the aside. It is stored (`later_by` `turn`), so
  nothing is queued. Other wakes keep never holding.
- **Reply or none is `Reply.says`**, decided by Initiative, never read from her text. None stores her staying
  quiet, and a page leaves that turn and the household turn it answers out (`ashley.conversations.quiet.shown`), and the
  list of conversations counts only what a page shows, so a conversation holding nothing else is not listed and
  nothing appears in the talk. A reply is an ordinary turn on the bench's talk.
- **At most `max_reactions` per bench in `window_s`**, in code (`bench_reacts.wait_s`) over the records in the window; a
  capped bench waits, its changes unseen, and is reacted to once one record leaves the window. Records older than
  `keep_s` are deleted when the next is written, the newest always kept.
- **Logs** `bench_reacts.done` with the bench id, how many commands were handed, `reply`, `none` or `pending`, and the
  duration; `bench_reacts.capped` once per wait; `bench_reacts.deferred`, `bench_reacts.refused`; never a piece or a
  message.

## Her bench's text is checked for what editing left stale

Her notes rot: each whole-body edit kept the old text and bolted the update on (one note grew from 1.3k to 4k characters
over nine edits), a header was pasted in front of the list it introduced, and two pieces went on saying a thing was
still not found after another piece had found it. She had the text in context each time, so the cause is method, not
memory. Two changes, neither of which decides anything for her. Fits into: the Workshop (the
text it holds), Inference (a new task, as `memory_judge` is), and the reactions' shape (a trigger derived from state,
the last-seen recorded); it adds no singleton and no Command. Rejected: a model that rewrites or deletes the text
itself, since she is the judge and the checker is cheap and sometimes wrong; a rule that caps a note's growth, which
treats the symptom.

- **The guidance says it once** (`ashley.tools.bench_specs.INSTRUCTIONS`): a note holds the current state, and an update
  rewrites the section it changes and drops or moves what it supersedes.
- **A cheap model points at passages** (`ashley.tidy`, task `bench_tidy`, flash-lite first with haiku as the fallback: on one bench's notes flash-lite flagged the stale "not found" lines in every run and haiku in none). It reads the
  bench's text pieces (`tidy.json` `kinds`: note, document, code, model, measurements; never a page she is reading, a
  site, a video or a file) and replies in structured fields, `{piece_id, kind, quote, by_piece_id, why}` with `kind` one
  of `superseded`, `contradicts`, `debris`, `duplicate`. Code keeps a finding only when its piece was sent, the quote is
  in the body the model saw and within the bounds, and it is not a repeat; invented quotes are dropped and counted.
  The prompt is bounded by `max_piece_chars` per piece and `max_total_chars`, most recently changed first.
- **When it runs:** after a turn on a bench, apart from the reply (`ashley.channels.bench_after.tidy`, a background task like the memory
  act, never awaited). It asks the model only when a text piece's version differs from what the last finished pass
  recorded (`bench_tidy.versions`), so a move, a resize, a site piece or an unchanged bench costs no call; a person's edit
  counts at the end of the next turn. One pass holds a bench at a time (`Tidy.begin`, `lock_s`, across pods and sites); the
  versions are recorded only when a pass finishes, so a pass lost to a restart, a model out of reach or a pass already running
  is simply made up by the next turn's end. Rejected: a sweep singleton, because the end of the turn already marks the moment
  and a bench nobody talks on gains nothing from being checked; running before her reply, which would delay it.
- **Findings are durable** (`bench_findings`, keyed to the bench) and wait for a next turn that may be days away. A finished
  pass replaces the bench's open findings; a dismissed one stays, unseen, so the same passage is not pointed at again while
  it stands. Findings older than `keep_s` are deleted when the next pass writes.
- **She is offered them at the start of her work, in `bench_read`** as `to_check` (at most `shown`, oldest first, each with
  `id`, `piece_id`, `kind`, the exact `quote`, `other_piece_id` and a short `why`), with one line of tool guidance: check
  each against the pieces, fix the right ones with an ordinary edit (undoable and logged like any), and `bench_dismiss`
  the rest. A finding whose quote is no longer in its piece is deleted at the next read, so an edit by her or by the person
  clears it; a dismissal marks it. Rejected: putting them in the system prompt, which would change it under a cached prefix
  and go stale mid-turn as she fixes them.
- **Logs** `tidy.pass` with the bench id, outcome (`unchanged`, `busy`, `ok`, `unavailable`, `refused`, `bench_gone`),
  pieces sent, findings kept per kind, findings dropped and duration; the tool call lines carry the finding id. Never a
  quote, a reason or a piece's text.
