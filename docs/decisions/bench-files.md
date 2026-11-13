# Bench files

Files, photographs and 3D on a bench: the object store, uploads, looks and model runs.

## Benches carry files, photographs and 3D

- **Uploads and downloads are large pieces**: `image` and `file` kinds (above); a person uploads from the bench page and
  downloads any file piece. A PDF or a zip is a `file` piece; `document` stays Markdown in Postgres.
  - **An upload is the request's raw bytes** (`POST /api/benches/{id}/files`, `ashley.api.bench_files`), judged and
    kept by `ashley.files.intake.take` and added by an ordinary Add (`ashley.workshop.bench_file.add_file`), so the piece
    is live, logged and undoable like any other. The name and the type the browser gave ride in the headers `X-File-Name`
    (percent-encoded) and `X-File-Type`, never in the URL or the logs; the body type is `application/octet-stream`,
    which a cross-site form cannot send (`ashley.api.person.Uploading`). It is read into memory whole (to judge, hash
    and keep it), so the size is bounded: `max_bytes`, 100 MiB, enough for several minutes of phone video; a longer
    request is 413, by `Content-Length` or as its body streams in. Serving has no such bound: `GET /api/files/{token}`
    streams from the store (`ObjectStore.size` and `ObjectStore.stream`, an S3 ranged GET), so a download or a seek
    never holds the file in the pod. Streaming the upload too (the hash names the key, so it would need a staging key)
    is not built.
  - **Content decides the type, not the client** (`ashley.files.sniff`, signatures and limits in
    `ashley/files/files.json`): a signature of the config (PNG, JPEG, GIF, WebP, PDF, zip), else UTF-8 text with no
    control characters (`text/plain`, or `text/csv`, `text/markdown` or `application/json` when the client named it), else
    415. A file that says it is a type the config knows and is another is 415 too. The type stored is the sniffed one, so
    markup uploaded as `text/html` is a `text/plain` file. Rejected: SVG and HTML as images or files, which run script
    when opened; trusting the declared type; a content-sniffing library, which adds a dependency for seven signatures.
  - **A large piece is made only from bytes, and its bytes never change.** `decide` refuses an Add whose body is not a
    stored file of the kind (an image's media type is an image's) and an Edit that changes the body (`bad_file`); the
    commands route and her `bench_add` refuse an Add of a large kind outright, since a body they wrote names bytes no
    one uploaded. An Edit may retitle the piece.
  - **A bench viewer reaches the bytes through a link of the app's own**, `GET /api/files/{token}` (`ashley.files.links`):
    a token signed under the deployment's link key (`ashley.connections.deployment_secrets`), shared by every pod, naming household, hash, media type, whether to show it
    in place and when it ends. It is the only credential, so an `<img>` and a saved download need no session, and it
    carries no file name. A bench read hands out links ending at the end of the next half-`link_ttl_s` window (900 s), so
    the address is stable within a window and the browser keeps the image; the page reads the bench again 30 s before
    the earliest ends. Served with the sniffed type, `nosniff` and `Content-Security-Policy: sandbox`, in place only for
    images, as an attachment otherwise. Rejected: presigned S3 URLs, which point a browser at the NAS; the session
    cookie as the credential, which an `<img>` in another tab, a download manager and later `bench_look` would each need
    to carry; the file name in the token, which the access log would then hold.
  - **She adds and reads files** (`ashley.tools.bench_files.BenchFileTools`, offered while a store is wired):
    `bench_add_file` makes a file piece from text she writes or from what a code piece's latest run gave (its output, or
    a file it left), its type chosen by the name's extension and checked against the bytes like an upload. Her
    `bench_read_piece` on a text file piece reads the file's text in windows; on any large piece `bench_read` gives its
    name, size and type, never its hash. Her edits and moves of a file piece are the ordinary ones.
  - **Logs** carry household, size, media type, copies, counts and durations (`files.stored`, `files.refused`,
    `files.served`, `files.copy_failed`, `files.read_failed`, `files.repaired`, `files.repair_failed`, `files.sweep_started`,
    `files.sweep_store`, `files.swept`, `files.sweep_list_failed`, `files.sweep_delete_failed`, `files.sweep_failed`), never a name,
    a token or a byte.
- **`bench_look` gives her eyes on the bench** (`ashley.tools.bench_look.BenchLookTools`, on a bench's talk while an
  object store is wired): a piece (`piece_id`) or the whole bench, returned as an image in the tool result
  (`ashley.inference.model.ToolResult.images`: an Anthropic `tool_result` holds image blocks; Chat Completions, which
  Gemini and OpenAI share, takes a tool message as text only, so the pictures follow it in a user message, each after a
  line naming its call; a checkpoint keeps them as base64). An image piece is always given from its own bytes, never
  drawn: oriented by its EXIF, cropped to her optional `region` (fractions of the oriented picture, taken from the
  original pixels before the scale), scaled to `max_image_px` on its longest side and re-encoded as a JPEG under
  `max_image_bytes` (`ashley.looks.pictures`, Pillow; a source over `max_image_pixels` is refused `too_large` before it
  is decoded). Everything else (a document, code, a design, a model, the whole bench) is a JPEG screenshot of the bench's page taken by headless Chromium in a pod of the sandbox namespace
  (`ashley.looks.kubernetes.KubernetesLooker`, one pod per look, deleted however it ends, no state on a node, so
  either site takes any look; a warm pod takes it first, below). The pod opens `/look/<token>`, the client's own page (`rooms/workshop/look/`) drawing
  the same piece components read-only, and waits for `body[data-look="ready"]`; its data is `GET /api/look/{token}`.
  The token (`ashley.looks.links`) names household, person, bench and optionally a piece, lasts `link_ttl_s`
  and is the only credential; it is a different purpose from a file link. With no browser wired
  (`LOOK_IMAGE`, `LOOK_APP_URL`) only an image piece can be looked at.
  - **The picture is kept with the turn.** Its bytes go in the object store under `look/<household>/<sha256>`
    (`ashley.looks.keys`), never under the files' `bench/` prefix, so a sweep of files no piece names cannot reach what
    a person's history shows; an image piece's own bytes are copied there for the same reason. The row
    (`ashley.looks.looks.Looks`, table `bench_looks`, unique per turn and call) names it, and the conversation routes
    serve it under her final answer as `ChatTurn.looks` with a picture link (`GET /api/looks/{token}`, a third
    purpose, ending in the files' `link_ttl_s` half-windows like a file link, not the look's own `link_ttl_s`). The files repair singleton keeps both prefixes whole on every site (`ashley.wiring_singletons.REPAIRED_PREFIXES`), so a look taken
    on one site is served after a failover; the sweep lists `bench/` only and never reaches a look.
  - A model piece takes a `view` (`ashley/looks/views.json`, matched by the client's `SIDES`): the look's address carries
    `?view=<side>` and the page draws that one side where it would draw the four-view sheet, which stays the answer
    when she names none. `region` also crops a screenshot, though that holds no more detail than the screenshot.
  - Limits are data (`ashley/looks/looks.json`): the screenshot's size, `max_image_bytes`, `max_looks_per_turn` (counted
    from `bench_looks`, so any pod agrees; a call run again after a resume replaces its row), the pod's deadline and
    limits. A screenshot over `max_image_bytes` is refused (`too_large`) like any look that cannot be taken, and kept nowhere.
    Each look logs `tools.call` with bench, piece, `how` (`piece` or `screenshot`), `region` (0 or 1), `view`, bytes and `px` (the longest side, `-` when unread), and the pod
    logs `looks.pod`; never the picture, the token or the page's content.
  - Rejected: a screenshot of an image piece, which costs a pod to give her bytes already in the store. Rejected:
    pictures in Postgres, which puts them through WAL and both sites' replication. Rejected: rendering the bench in
    Python, which would be a second, drifting copy of the client's piece components. Rejected: extending the code
    sandbox's `Job`, which is a text script with no network and text output; a look needs a browser image and one
    route to the app, so it is its own Strategy beside the sandbox, sharing its API client, namespace and RuntimeClass.
  - **Cluster side** (the cluster repo): a pinned browser image (Python with Playwright and Chromium), a network policy
    letting pods labelled `ashley.yggdrasil.pub/look` resolve DNS and reach the app's Service port only, a quota for
    one 1 CPU and 1 Gi pod beside code runs, and the app's `LOOK_IMAGE` and `LOOK_APP_URL`. The warm pod adds a Service
    `ashley-look-warm` (port 8080, selecting `ashley.yggdrasil.pub/look-warm`), a policy letting the app's pods reach that
    port, the app's `LOOK_WARM_URL`, and a quota for a second look pod beside it.
  - **A warm pod takes the look first.** A cold look spends about 40 s starting its pod, so each cluster keeps one
    (`ashley.looks.warm_pod.WarmPod`, named `look-warm`, the look pod with a server in place of a page: `shooter.serve`).
    `ashley.looks.warm_looker.WarmLooker` sits in front of the same `KubernetesLooker` (an Object Pool of size one, not a
    second looker): it posts the page's address to the pod's Service and gets the same marked line back. The pod takes one
    look at a time; a call that finds it busy (503), missing, unreachable, timed out or broken (`browser`, no picture)
    is taken in a pod of its own as before, so a look is never lost to the warm pod. A page that never drew
    (`not_ready`) or a picture too large is the answer and is not tried again.
    - **Held per site, under the lease.** The pod lives in one cluster, so its keeper is a singleton per site
      (`Lease.run_on_site`, key `look-warm@<site>`), unlike the others, which run on the active site alone: the standby
      site's app pods take looks too and reach only their own cluster's pod. Any app pod on the site uses the pod; the
      holder creates it when there is none, replaces it when it ended, was made for another image or limits (an
      annotation holds a hash of the spec) or is older than `warm_max_age_s`, and otherwise leaves it, so a new holder
      adopts the pod it finds. A look is a request, not a session, so nothing is lost when the holder changes.
    - **Nothing one look held reaches the next.** Each look launches its own browser process and closes it, so
      no cookie, storage or cache outlives the look; whatever a look left in `TMPDIR` is removed before the next is
      taken. The pod opens only addresses under the app's look page (`ASHLEY_LOOK_PREFIX`), judged after resolving the
      address as a browser does (tabs and newlines dropped, `\` as `/`, percent-encoded dot segments removed) and
      handing the browser the resolved address; the cold pod takes the app's own address and checks nothing. It has the look pod's
      account-less, read-only, gVisor spec and the same network policy, and is reached only by the app's pods.
    - **Limits are data** (`looks.json`): `warm_tick_s`, `warm_max_age_s`, `warm_connect_s`. Logs: `looks.warm` (outcome,
      bytes, duration), `looks.warm_fallback` (reason), `looks.warm_started`, `looks.warm_adopted`, `looks.warm_replaced`
      (reason), `looks.warm_failed`; never the page's address or content.
    - Rejected: an etcd lease on the active site for the keeper, which leaves the standby site's pod unkept. Rejected:
      one warm pod for both sites, which every look from the other site would reach across the link. Rejected: reusing
      one browser across looks, which saves about a second and shares a profile between households. Rejected: an
      exec into the pod, which wants `pods/exec` for the app's account.
- **She watches a video and listens to audio** (`ashley.tools.bench_media.BenchMediaTools`, on a bench's talk while a
  store and a media worker are wired).
  - **A video file is a `clip` piece and an audio file an `audio` piece**, large kinds chosen by the bytes' media type
    (`piece` in `files.json`'s `types`: MP4 and QuickTime by their `ftyp` brand, WebM, MP3, M4A, Ogg, WAV, FLAC), played
    by the page's own `<video>` and `<audio>` from the file link, which answers one `Range` (206, else 200; 416 past the
    end) so the controls scrub. `video` stays the embedded provider kind. A cue (`bench_cue`) drives any of the three; the
    page says what she did in a line of text beside the player, which needs no motion.
  - **A transcript is a reader piece beside the recording**, one `[m:ss] text` line per segment, with no address (a
    reader's `url` may be empty: text from no page). `bench_transcribe` takes captions first: a `.srt`/`.vtt` file piece
    she names (`captions_piece`, parsed in the app), else the captions inside the file, else the sound. The sound is cut
    into windows of `window_s` seconds, each sent to the speech service and stamped by its start, so a time is exact to a
    window, not a word; a window of near silence is not sent, since whisper invents words for it.
  - **A transcript names its recording** in the reader body's `recording` (`ashley.workshop.reader.Recording`): the
    recording piece's id and the second each line starts at, written by `bench_transcribe` and served as
    `BenchPiece.reader.recording`. Nothing is read back from the title or the `[m:ss]` text, which stay for people and
    for her. A body whose lines no longer number its starts (it was edited) serves no `recording`, since a time then
    belongs to no line. An older transcript has none and its lines do not play.
  - **A click on a transcript line plays the recording from there, and the line being spoken is marked.** The client's
    cue path is the one mechanism: her `bench_cue` arrives as `BenchCued` and a person's click is `cueBenchPlayer`
    (`app/web/src/session/live.ts`), a seek then a play to the same listeners (`MediaView`'s `driveFile`), tagged by
    whom so the line under the player says only what she did. A person's click is no Command and no network call: a
    cue is no change to the bench, a person's own controls already drive the player directly, and a server round trip
    would add a delay and a log row for a seek. The player reports its place (`model/playhead.ts`, this page only) and
    the transcript marks the line at that second (`model/transcript.ts`, `lineAt`) while it plays and keeps it in view
    inside its own scroll box. Rejected: a person's click as a `Cue` Command, which is hers alone and would put the
    person's seeks in the log. Rejected: parsing the stamps out of the text, which an edit can break.
  - **A piece derived from another is shown inside its source's card** (`app/web/src/rooms/workshop/model/derived.ts`,
    `PairedBody.tsx`): a recording and its transcript are one card on the grid, the recording's body on top and the
    transcript in a panel below it that a person can fold, so the marked line and click-to-seek stay in view together;
    at phone width (the 760px grid breakpoint) the card shows Player / Transcript tabs and keeps the hidden half mounted,
    so a recording plays on under the other tab. This is presentation only: the transcript stays its own reader piece,
    with its own Commands, tools, highlight and undo, and Archive / Remove for it sit in the panel. The one relation is
    `sourceOf(piece)` (piece to source piece id, or null), a table of providers (`RELATIONS`), each reading a structured
    field and naming its panel; today the only provider is a transcript's `reader.recording`, and a second source of
    derivation (page text, a file made from another) is a new row there, never a title or text match. A derived piece is
    grouped only when its source is on the bench and is not itself derived; otherwise it keeps its own card. The merged
    card has the source's slot, size and order, so a drag, a resize and the card's tools act on the source; the derived
    piece's own order is untouched (a drop is mapped to the whole order by `fullIndex`). Her mark and highlight on a
    derived piece show on the merged card, and a new highlight opens a folded panel. The marked line follows a recording
    the page itself plays (a clip or audio piece); a YouTube embed reports no playhead (that is its player API, not built),
    so its transcript lines seek and play it but no line is marked. Rejected: a Transcript tab as the only view, which
    hides the line being spoken from the player. Rejected: a `transcript` field on the recording piece, which makes the
    server store one fact twice. Rejected: grouping by title or by the `[m:ss]` text.
  - **`bench_frames` is one picture, a sheet** of up to `max_frames` frames at the moments she names, left to right
    then down, kept and counted exactly like a look (one row per call), so it needs no new table and the page shows what
    she saw under her answer.
  - **Both run in a media pod, not the app pod**: `ashley.runs.media.Media`, a second use of the sandbox namespace's pod
    machinery beside Code runs and Looks. The code sandbox cannot do it: it is text in and text out, with no network and
    no ffmpeg. The pod resolves names, reaches the app (to fetch the file by a `files` link of `link_ttl_s`, checked
    against the size and sha256 the piece names) and the speech service, and prints one marked line. No bytes pass through
    the app pod and no state is on a node.
  - **Limits are data** (`ashley/runs/media.json`): frames per call, cell width, JPEG qualities, the longest sound
    taken (`max_audio_s`), the window, the silence threshold, each task's pod deadline. Logs: `media.frames` and
    `media.transcribed` with the household, counts, bytes and durations, and `media.pod`; never a link, a picture or a word.
  - Rejected: whisper inside the app pod, which puts ffmpeg and minutes of CPU in the process that serves people.
    Rejected: one row per frame in `bench_looks`, which wants a migration and a changed key for a picture the model
    sees once. Rejected: a `transcript` kind, which would be the reader again. Rejected for now: streaming beyond
    `max_bytes` (open-work, item 11); a range is served from the bytes read whole, so a 25 MiB video is the ceiling.
- **A repo reaches a bench as a snapshot** (a zip, or one file) from the person's own code host connection ("A
  household connects its own services"). Anything beyond a snapshot is item 21's Codebases VM.
- **3D is her work, seen by the person**: she models in code (kind `model`, format `code`, language `build123d`), the
  piece shows its latest run in 3D, STL, 3MF and GLB leave through downloads, and she photographs the view with
  `bench_look` so the person can point out issues. Rejected for now: a
  cooperative editor where the person edits the same model; no embeddable open-source one exists (open-work, item 11).
  - **A model run's meshes come back in the run's line and are kept as objects.** A profile whose `artifact_bytes` is
    above 0 (build123d: 16 MiB, in a log of 8 MiB) lets the runner carry the files ending `.glb`, `.stl` or `.3mf`
    as base64 of deflated bytes, in name order while their sizes fit the budget and the line fits the log; the rest are
    named in `skipped`. The envelope inflates each against what is left of the budget, so a forged line cannot expand
    past it. `ashley.runs.artifacts.keep`, called by `run_once` for a bench run only, judges each by its bytes against
    the type its suffix says (GLB by its `glTF` header and version, binary STL by `84 + 50 × triangles = size`, 3MF as
    a zip holding `3D/3dmodel.model`; the checks are data in `files.json`) and stores it as a file piece's bytes are,
    under `bench/<household>/<sha256>`. The run records `{name, sha256, size, media_type}` for each in
    `code_runs.artifacts`. One that is not what its suffix says, or that the store cannot take, is named in `skipped`,
    and the first store failure ends the keeping. The sweep's references include the artifacts of the runs that
    remain, so pruning a run lets its meshes go; repair mirrors them as it does any file. A chat run keeps none.
    Rejected: the pod uploading its outputs to the app, which would give her script a network route. Rejected:
    keeping the bytes in Postgres.
  - **An existing model is a file piece a model run starts from** (`ashley.workshop.model_inputs`). A person uploads an
    STL, 3MF or STEP as a file piece; a `build123d` run is handed the ones its `bench_run` names in `inputs` (a list
    of piece ids; the person's Run button names none, so it takes every such piece that is not shelved), in layout
    order while the bytes fit the profile's `input_bytes` (768 KiB), as the job's binary `inputs`: deflated
    and cut in environment strings of at most 100,000 characters (`ASHLEY_BLOBNAME_<n>`, `ASHLEY_BLOB_<n>_<k>`), written
    read-only by the runner as `inputs/<piece id>.<ext>` and never carried back as output. The bytes are not recorded
    with the run: its files hold `inputs.json`, the index (piece id, name, path, size, sha256, and `left_out` with why:
    `too_large` or `unavailable`), without the last run's. A script names a piece by id, `ashley_cad.existing(7)`; the
    reply names the ones the run was not given. `inputs` omitted keeps every model file a candidate, and `[]` is none. A
    named piece that is not a model file on the bench, cannot be read, or does not fit the cap together with the other
    named ones refuses the run before it is logged (`bad_inputs`, naming the piece), where an unnamed one is left out.
    The ceiling is therefore on what a script uses, not on what the bench holds, so two versions of one design do not
    shut each other out. Her script text is never read for `existing(...)`. The cap comes from the pod object:
    Kubernetes takes about 1.5 MiB for it, and the environment is where the job already rides. Rejected: mounting from the object store, which needs the pod to
    reach the store or an init container to hold its credentials. Rejected: a field on the model piece naming its
    inputs, a second place beside the pieces for the same fact. Rejected: finding `existing(...)` calls in the script
    text, which is regex over what she wrote.
  - **`existing` makes a mesh into a solid that can be changed.** build123d's `import_stl` gives one face with no volume,
    which nothing can be joined to. An STL (binary, told by its size matching its triangle count, so a binary file whose
    header begins `solid` is read right, or ASCII) is written as a 3MF with shared vertices joined, and `Mesher` reads
    that as a solid of its triangles; a 3MF reads the same way, converted from the unit it declares; a STEP is imported
    as it is. An STL's unit is not in the file, so `existing(piece, unit=)` says it (default `mm`). A mesh that does not
    close, or whose faces point inward, is refused. `joined` and `cut_away` do the boolean and fail when the result
    lost or invented volume, because a boolean on a real IMU mesh returned only the added box.
    Rejected: trusting `+` and `-` on a mesh. Rejected: a mesh boolean library, which the image would have to carry
    for a repair that the person's STEP export avoids.
  - **The page shows the view, the downloads and the checks.** A model piece's card is the latest run's `model.glb`
    drawn with three.js (pinned in `app/web`, imported only by `ModelCanvas`, so it is a chunk no other page loads),
    turned and scaled from glTF's metres and Y-up to build123d's millimetres and Z-up so the frame is the script's, fitted
    to the bounds, and orbitable; the extent in millimetres is written under it. Under that: STL, 3MF and GLB links
    from the run's artifacts, saved under the piece title as a slug; every check with its verdict (a fail outlined,
    an unconfirmed one hatched as a guessed measurement is) and what it rests on; the source folded. A piece never
    run, or whose run kept no model, says which in the picture's place. A browser that cannot draw WebGL, or a file
    that will not load, says so there and keeps the downloads and the checks. The Run button of a model kind offers
    `build123d` alone.
  - **`bench_look` on a model piece is a sheet of four views** (isometric, front, top, right, orthographic) drawn once
    by the same component on one canvas, which the look page's `ready` waits for: it is set after every model on the
    page has drawn its frame, or failed. Headless Chromium draws WebGL with SwiftShader, with no GPU and no new launch
    flag. Rejected: a continuous render loop, which a still photograph and an idle page do not need.
- **Measurements are structured data, each with its source** (kind `measurements`, format `measurements`,
  `ashley.workshop.measurements`). The body is JSON: `{"items": [{"name", "value", "unit", "source", "tolerance",
  "ref", "given"}]}`. `name` is an identifier unique within the piece. `value` is finite. `unit` is `mm`, `deg`,
  `count`, `g`, `ml` or `min`, with lengths always in millimetres, masses in grams, volumes in millilitres and durations
  in minutes (she converts what she is told). `source` is `measured` (the person measured, counted or stated it, or a
  file embodies it), `datasheet`, `accepted` (she asked and the person said to go with the value), `bound` (something
  soft or varying whose true size is the range `value` ± `tolerance`, so a bound row carries a tolerance above 0 and the
  part is built to work over the whole range) or `guessed`; every source but `guessed` is confirmed. `tolerance` is an
  optional ± of 0 or more in the unit. `ref` is optional text up to 200 characters (the datasheet's address, what was
  measured with, the photo piece a form was seen in). `given` optionally names a choice row
  of the same piece the number belongs to (a strap's width is given the strap's form). Anything else is refused
  `bad_measurements`. The room shows a table with each value's source, a guess hatched, a choice
  by its label. Either side edits it like any piece, so a correction is logged and undoable. An edit of hers that changes
  what a confirmed row holds (a number's value, unit or tolerance; a choice's value) while keeping where it came from (a
  number's source and ref; a choice's source, turn and piece) is refused `confirmed_measurement`: a confirmed row
  changes only with a new answer from the person or a new source, and the row says which. The piece goes on any bench:
  the numbers a plan rests on (headcount, amounts, times) are rows too, under the bench guidance every bench gets.
  Rejected: a table of its own, since measurements belong to the project and a piece already gives edit, undo, Live
  and the log. Rejected for now: measurements as memory facts shared across benches, until a second bench wants the
  same object's numbers. Rejected: a source of its own for a size read off a photo; a photo settles what kind of thing an
  object is and its cross-section (a choice row, `seen`), while a size read off it stays guessed until the person gives
  or accepts it.
  - **A choice is a row too** (`"kind": "choice"`; a row with no `kind` is a number, so stored bodies need no
    migration): what kind of thing something is, in plain words (a flat strap or a round cord, gas or electric). It has
    `name`, `label` (up to 60 characters, for the person, since `name` is an identifier), `value` (up to 80), optional
    `options` (2 to 6, `value` one of them), `source` (`stated`, `seen`, `datasheet`, `accepted` or `guessed`; `bound`
    and `measured` are number-only), `turn` only with `stated` or `accepted`, `piece` only with `seen` or `datasheet`,
    and `ref`. A citation is checked where its context is: a choice row she adds or changes as `seen` or `datasheet`
    names a piece on the bench, layout or shelf, of an image, file, reader, site or recipe kind (`decide`), and one as
    `stated` or `accepted` a person's turn on the talk her tools serve (`ashley.tools.bench_citations`, since the talk
    is not the Workshop's); either is refused `bad_citation`. A person's edit needs no citation, since the log says
    who wrote it, and a row kept as it was is not judged again. `measurements.confirmed` is the one test of a confirmed
    row, read by a check's verdict, the guard on her edits and the carry into later turns. Rejected: a form told by
    which rows exist, which is shape-sniffing (one bench's rows flip-flopped and "superseded" lived in a `ref`);
    free-text values code branches on (code keys on `source`, the citation and `rests_on`; a script compares
    `chosen()` only to the row's own `options`). Rejected for now: `piece` on numbers, so that a number of hers whose
    `ref` cites a photo could be refused as `measured`.
  - **Each choice she sets is shown to the person once, by code**, beside her reply and never in it, whatever its
    source, so a wrong form she recorded as seen or stated is in front of the person too. So is a guessed number that
    an unconfirmed check of the turn's own run rests on (`model_report.open_guesses` of the turn's latest bench run of
    each piece, `Runs.bench_runs_of_turn`): by its name read as words, its value and unit (`measurements.shown_value`),
    with no options, so the card shows it and the person answers in the talk. As a bench turn closes with
    a reply that is said, every such row of the bench's measurements pieces that no `Surfaced` names by its current
    name and shown value is recorded shown, one `Surfaced` of hers per piece (`ashley.workshop.surface.surface`), and goes
    into `Receipts.facts` (bench, piece, name, label, value, options), stored with her turn like any receipt and
    carried into her history on the app's line. `Surfaced` is a non-piece Command read back from the log as `Point`
    is (`BenchView.surfaced`): it changes no piece, is never undone, and moves neither the bench's last change, the
    undo walk nor her reactions; a row whose value or name changes is shown again. A turn that stays quiet records
    nothing, so its rows wait for the next reply, and a turn closed again after a steer shows the same ones. The
    card beside her reply offers the row's options as buttons, and a tap is the person's Edit of the row (`PUT
    /api/benches/{id}/pieces/{piece_id}/choices/{name}`, `ashley.workshop.choice_tap.tapped`): a new value
    `stated`, her guess `accepted`, a row whose source changes losing its citation; a value off the options is 422
    and logs nothing. Their own `Surfaced` of the new value follows, so it is not shown back to them. A piece of an
    outside kind or one a tainted turn wrote is never shown (`decide` refuses its Surfaced `bad_rows`): its labels
    and options are not household words, so it gets an ids-only line in the moment layer instead (piece id and its
    count of unconfirmed rows, `ashley.tools.bench_now.now`). A number a run does not rest on is not shown, so the card never lists every guess on the bench; the moment layer
    lists each open number with `shown`, from the log, so a later turn knows what is in front of the person. Rejected:
    her asking in words and marking the row asked, which leaves the person's seeing the row to her words and a flag
    every edit of hers must carry right (the flag is gone, and a migration turned each stored one into a `Surfaced`); a
    Live-only notice, which a reload loses.
- **A diagram is Mermaid source in a stored piece** (kind `diagram`, format `diagram`, up to 20000 characters). The
  server keeps the text as written and checks nothing about it; the client draws it (`DiagramView.tsx`) with Mermaid,
  imported on first use, so a bench with no diagram never loads it, and bundled, because the look pod's browser has no
  internet. Mermaid runs at `securityLevel: 'strict'` with HTML labels off, so a label is text and a click callback
  is dropped. Its colours are read from the house tokens at draw time. A body Mermaid cannot read shows Mermaid's
  message and the source beneath it. The drawing registers with `tracked`, so `bench_look` photographs it drawn.
  Rejected: a diagram kind per chart type, since Mermaid already names its type on the first line, and a drawing
  library of our own.
- **A model is checked against them by the numbers, and the app does the comparing.** A run in `build123d` starts with
  the bench's measurements pieces that are not shelved, merged in layout order as `measurements.json` (a name a later
  piece repeats keeps its first value; none when the bench has none), recorded with the run's files as any input is, and
  without the last run's `measurements.json`, `inputs.json` and `out/report.json`, so a report read back is this run's.
  `ashley.workshop.model_report.report_of` parses `out/report.json` of a run that `ran` with exit 0 into a
  `ModelReport` (parts with bounding box and volume, triangles, checks) and judges each check from its numbers:
  `==` within ±`tolerance`; `<=` and `<` against target + tolerance; `>=` and `>` against target - tolerance. A check
  that holds is `pass`, or `unconfirmed` when a measurement it rests on is `guessed` or is not in the run's
  measurements; one that does not hold is `fail` whatever it rests on. A report not of the shape the helper writes is
  none, never a partial one. `BenchPiece.last_run.run_output` and `RunApplied` carry `artifacts` (with download links
  of the files' kind, ending at the half-`link_ttl_s` window) and `report`; her `bench_run` and `bench_last_run` carry
  the artifacts by name, type and size (no link: her tools hold no link key and a link lasts minutes) and the report.
  Rejected: judging a fit from the picture, which is for the person to point at; trusting a pass flag the script
  printed. Rejected: marking a failing check unconfirmed, which would hide a measured disagreement behind a guess.
  - **A stand-in names its form, and a fit against it rests on that form.** A `reference` part is shown as
    `(name, shape, "reference", form)`, `form` a choice row of the run's measurements; one without it, or naming a row
    that is not a choice, fails the run before anything is written, with a message naming the fix, and the report's
    part carries `form`. `chosen(name)` reads a choice and records the read as `measured` does, and `measured` of a
    number with `given` records that choice too, so a check that leaves out `rests_on` rests on the form. Every pair of
    compared parts with a reference part gets a `parts_apart` check (the volume they share against none), overlapping
    or not, resting on the forms its reference parts name; so on a guessed form the stand-in's fit is `unconfirmed`,
    never a plain pass (one bench read "18/18 checks pass" against a round stand-in for a flat strap). Pairs without a
    reference part still get one only when they overlap. Rejected: making only a formless stand-in's checks
    unconfirmed, a softer signal of the kind she had already read past; a failed run cannot be missed and costs one
    re-run.
- **Her 3D method is the `3d` skill, and whether a model fits the real object is the bench turn's own judgement.** The
  seed `app/ashley/skills/seeds/3d.md` is the method: measurements first, each with its source, the model built from
  them with `ashley_cad`, a `check` for every fit, the report read before anything is said, `bench_look` after, and an
  `unconfirmed` check reported as resting on a guess. It loads as every skill does, for a bench whose kind of work is
  `3d`; the bench guidance (`bench_specs.INSTRUCTIONS`) names the `model` and `measurements` kinds and tells her to set
  that kind. The judgement runs on the model running that bench's turn (`brainstorm`, as the talk is), from the report
  and the sources together; the app has computed each check's verdict from the numbers before she reads it. Rejected: a
  separate "strongest route" call for the fit (it would re-read what the turn already holds, and the verdicts are
  already code); `Reply.escalate` for it (a bench turn does not escalate, "A turn escalates once"); a ledger task for
  fit judgement.
- **A long paste is an attachment captured at paste time**, a structural field of the message and never found by
  reading its text: the composer takes a paste longer than `PASTE_MIN` (`rooms/her/limit.ts`) as a chip
  beside the message, which stays what was typed, and the chip goes with it on send.
  - **On a bench** the person's own Add command puts it up as a `document` piece titled by its first line, so it is
    undoable and shows live, and the message names it by `BenchMessage.piece_id`, checked to be a piece of that bench
    (else 422 `refused`). She is told of it in the turn's `note` (never stored), and reads it with `bench_read_piece`.
    A bench message takes no `attachment`. A refused Add (`full`, `too_long`) sends nothing and the composer keeps the
    chip and says why.
  - **In chat** the `ChatMessage.attachment` (`title`, `text` of at most `ATTACHMENT_MAX_CHARS`) is stored on
    the person's turn (`turns.attachment_title` and `turns.attachment`, null together on every other turn, a person's
    turn only), read back as `ChatTurn.attachment` for the page to fold under the message, and carried to her whole,
    marked and ended, wherever the turn is carried (`channels.prompt`). Memory, which reads `turn.text`, learns only
    what was typed. The kiosk and a bench take none. Logs `respond.attached` with ids and the length, never the text or
    title. Rejected: a table of its own, since a turn has at most one and every read of a turn wants it; the paste
    appended to `text`, which the page could only split by reading it.
