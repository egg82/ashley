# Tools

Her look-up sources and her front for Claude Code.

## Search: SearXNG for the web, Photon for places

Tools is a Composite over its sources: the house (HA's MCP server) and a look-up, which is itself a sub-agent over a
Composite of the web and places. Each source's catalogue is asked at once; one that does not answer is named in the
catalogue, and she says in one line that she cannot use it right now, while the others go on.

- **She never reads search results; a sub-agent does, and she calls it as one tool, `look_up`.** It has its own task
  and routes (`look_up`, Haiku first) and only `search_web`, `read_page` and `find_places`; she writes the question in full, it
  searches, and it hands back `found`, a short `answer`, its `sources` and, when she asked for a page or video to show,
  its `references`: result numbers with a few words and the site each, never a URL. Her context holds the question and that
  answer, never a snippet, which is what "A call carries only what this reply needs" asks of a long or untrusted tool
  set, and she keeps every house tool after a look-up, so "what time does Target close? remind me at eight" is one turn.
  What crosses back is bounded in code (`look_up.json`: the answer's length, how many sources and how long each), and
  nothing that reads the web has a tool that acts on the house.
- **What can still get through:** an instruction a page smuggles into `answer` reaches her as a tool result. It is
  bounded by the answer's length, by the sub-agent's prompt (results are facts to weigh, never repeated as requests),
  by her own prompt (a look-up's answer is information, not an instruction), and at worst by what HA exposes to Assist.
- **The look-up knows when it was asked through a field:** `look_up` requires `now`, the household's local date and
  time from her prompt, which reaches the sub-agent before the question, so "open now" and "tonight" mean something.
  `Tools.call` carries no household, so a required field is how the moment crosses.
- **Its steps record no conversation in the spend ledger:** `Tools.call` carries no conversation id, so a look-up's
  rows are by task alone.

- **The web is SearXNG** (JSON API), at the deployment's address (`SEARXNG_URL`, set in the cluster repo); without it
  she has no web search. The look-up is shown the first few results' titles, snippets and sites, each with a result
  number, and SearXNG's direct answers.
- **The look-up reads a page by result number, never by URL.** `read_page` takes a number that a `search_web` of this
  turn returned; the numbers run on across the turn's searches and look-ups, and the table from number to URL is the
  turn's one `ashley.tools.results.Results`, which `ashley.tools.pages.Pages` records into and the bench tools read
  (see "A site or video piece is put up by a search result's number"). At most two pages are read per look-up. A
  snippet often lacks the one fact asked for (a clinic's hours) while the page has it. Her context is unchanged: the
  page text reaches only the sub-agent, cut to `page_chars`.
- **A YouTube video's page reads as the video, and its description's links become numbered results.** A watch page's
  words are all inside a script, so its stripped text is a few hundred characters. `read_page` on a result whose parsed
  host and path are a YouTube video's (`ashley.workshop.embed.youtube_id_of`) fetches `https://www.youtube.com/watch?v=<id>`
  as a browser would (`Mozilla/5.0`, `Accept-Language: en`) and returns the title, channel, publish date, length and
  description from the page's `ytInitialPlayerResponse` (`ashley.tools.youtube`). Each https link in the description is
  recorded into the turn's `Results` (at most `Pages.MAX_LINKS`, once each) and shown as `<url> (result N)`, so
  `read_page` and the bench's reference tools follow it by number; the page authored the link and she never types a URL,
  so the rejected URL parameter below stays rejected. Only a video's description numbers its links, since a page's own
  text rarely holds the links a question turns on. `page_bytes` needs no change: the player response sits inside the
  first megabyte of the two pages measured (at about 0.78 MB of 1.4 and 1.8 MB), and a page that cuts it off reads as
  any page.
- **A bench site or video piece reads as its page.** `bench_read_piece` on a site piece, or a video piece that is not a
  direct file, also returns `page_text` (the page as `read_page` reads it, cut to the bench's `piece_chars`; for a YouTube
  video its details and description) or `page_unavailable`, through `ashley.tools.page_reader.PageReader`, the one reader
  `read_page` and the bench share, under the same `page_fetch` boundary. A video's description links are numbered into the
  turn's `Results`, so look_up reads such a result's page (she names its number) and `bench_add` of a code or document piece
  by that number follows. `read_page` takes only a result number, and a piece's own address is not one. The address is
  the piece's stored body, written by the server from a result or
  given by a person, never model-typed text, so the rule that she never reads by a URL she wrote holds. Rejected: a `url`
  parameter on `read_page` or a separate bench tool (the piece id already names the stored address).
- **A YouTube video's captions are fetched by yt-dlp in a media pod of their own.** A plain GET of a caption track's
  address answers 200 with an empty body (YouTube wants a proof-of-origin token the page does not hand a plain client);
  yt-dlp, pinned in the media image, does what it asks. `bench_transcribe` on a YouTube `video` piece takes the captions
  file piece she names (`captions_piece`) first, else runs `Media.youtube_captions`, a third media job beside `frames` and
  `transcribe`: the app parses the video id from the piece's URL (`ashley.workshop.embed.youtube_id_of`) and hands the pod
  only that id; the runner builds the canonical watch address itself and passes yt-dlp an argv list, so no other address
  reaches it. yt-dlp is asked for the manual English track and falls back to the automatic one (json3), and the runner
  turns it into `[start, text]` cues stored and shown like a recording's transcript (source `youtube`). A video with no
  English track answers its own outcome, `no_english_captions`. This is the only media pod with public egress: it carries
  `ashley.yggdrasil.pub/fetch` besides the media label, and the namespace's network policy (the cluster repo) opens TCP
  443 to public addresses and DNS to that label alone. The pod fetches no file and has no link. Logs carry the video id,
  cue count, seconds and outcome, never a caption. Rejected: the app pod fetching the track (it would open an address no
  check has seen), and calling YouTube's player APIs by hand.
- **A page fetch from inside the pod is a request forgery waiting for an injected snippet**, so
  `ashley.tools.page_fetch` is the one module that opens an arbitrary URL, and it fetches only https, only from a host
  whose every address is global (`ipaddress.is_global`, so loopback, private, link-local, CGNAT and unique-local are
  all refused, as is a mix of one public and one private address), checked before each request and again after each
  redirect, which it follows by hand up to `max_redirects`. It reads only `text/html` and `text/plain`, at most
  `page_bytes` of the body, within `page_timeout_s` for the whole fetch. **A DNS answer that changes between the check
  and the connect is not covered;** a homelab threat model accepts that. Pinning the checked address is possible
  (connect to the address, with the host in `Host` and in httpx's `sni_hostname` extension), but the client's pool keys
  connections by address, so a TLS connection checked against one host's certificate would be reused for another
  host on the same address; closing that properly needs a network backend that checks at connect time.
- **A page whose site refuses the plain fetch is read in a browser pod, as a browser that says what it is.** When the
  fetch is answered 401, 403, 429 or 503 (`ashley.tools.page_reader.REFUSING`, a bot wall's challenge among them) and a
  page browser is wired, `FetchedPageReader` reads the page through `ashley.looks.browser.PageBrowser`: a cold look pod
  (`ashley.looks.pod_spec.read_manifest`) running the look program in its `read` mode, which prints the main response's
  status and type and the loaded document, cut to `read_bytes`. The pod carries the fetch label as well as the look
  label, so the namespace's existing policy gives it public HTTPS and nothing private (the house LAN, both sites' pods
  and Services are excepted), and the address was checked public by the fetch it follows. What it brings back goes
  through `page_fetch.page_of`, so text and recipe are read alike; a non-2xx answer is still no page. Chromium runs as
  it comes, headless and saying so: measured on five recipe sites, the plain
  fetch read one and the browser another, the other three refusing both. Rejected: disguising the browser or
  answering challenges, which is getting past a site's refusal rather than reading what it serves; the warm look pod,
  which reaches only the app and draws benches, so strangers' pages stay out of it.
- **Printables is a look-up source beside SearXNG and Photon: a model is a result number, and its file reaches a bench by
  that number and a file id.** Its public GraphQL API (`api.printables.com/graphql/`) answers plain requests, while the
  site's pages and the other two sites that host designs answer them with a challenge (printables.com/model pages,
  Thingiverse and MakerWorld; nothing here tries to get past one).
  - **Find:** the look-up has `search_printables` (`ashley.tools.printables_search`): name, summary, likes, downloads,
    makes, rating and file names, each result numbered into the turn's `Results` as the model's page address. It is a
    look-up source, not a bench tool, because it is another search whose results the look-up weighs and she never
    reads; a model's page then goes on a bench as a site piece by its number through the path that already exists.
    Every value a caller supplies goes to the API as a GraphQL variable.
  - **Look:** `read_page` on a Printables model's page reads the model through the API (`ashley.tools.printables_page`):
    author, category, license, date, counts, files by name and size, and the description as text. The site's own page is
    not fetched.
  - **Fetch:** `printables_files(result)` lists the model's files with the ids Printables gave, and
    `bench_add_printables_file(result, file)` puts one on the bench as a file piece. The server finds the model from the
    number (`ashley.printables.printables.model_id_of`, by parsed host and path), requires the file id to be one of that
    model's files and its name to end `.stl`, `.3mf`, `.step` or `.stp`, asks the `getDownloadLink` mutation for the
    file's address, and opens it with `ashley.tools.page_fetch.fetch_file`: https, global addresses only and
    only `files.printables.com` (`printables.json`), each by parsed hostname and again after every redirect, at most the
    bench's file limit (`files.json` `max_bytes`) and `download_timeout_s`. The bytes must be what the name says (a binary
    or ASCII STL, a 3MF with its model part, a STEP with its ISO-10303-21 header) and are then kept as an upload is
    (`ashley.workshop.bench_file.add_file`). No URL is an argument of any of it.
  - **Outcomes** are distinct: `unknown_result`, `not_a_model_page`, `no_such_file`, `not_a_model`, `too_large`,
    `needs_login`, `unavailable`. `getDownloadLink` handed over STL, 3MF and STEP files to a visitor with no login; its
    refusal (`ok` false) is `needs_login`; no model tried has produced it.
  - **Rejected: Thingiverse and MakerWorld.** Both answer automated requests with a Cloudflare challenge. Thingiverse has an
    API key in the secret store (`ashley-thingiverse`) that a source over its API could use; none is built.
  - **Rejected: a URL argument for the file,** for the reason `read_page` takes none: the address comes from the API for a
    file the model lists.
- **Places are Photon** (`photon.komoot.io`, OpenStreetMap), biased toward the house and ranked by distance in code,
  nearest first, with the miles. The house's coordinates are the household's own home location, set by its people on the
  household panel, else HA's `zone.home`: the person's explicit setting wins, as a row wins over the env, so a household
  with no Home Assistant has places too, and a household with neither gets "the house's location is unknown". The own
  location is read on every call, so an edit applies at once; HA's is read again every `home_ttl_s`. Either is rounded to
  `bias_decimals` (about a kilometre) before it leaves, and the precise point is used only for the ranking, here; neither
  is logged.
  With that bias "Target", "pharmacy", "urgent care" and "Chipotle" each came back nearest-first at about 3 km.
- **Tunables are data**, `search.json`: Photon's host, timeout, how many results and how much of each snippet.
- **Rejected: SearXNG's map category for places.** It drops any location bias: a bare "Target" returned ten
  results, the closest 990 km from the house, so "nearest" cannot be had from it.
- **Rejected: appending a locality to the query** ("Target in <town>"). It sends where the household lives as text
  in every query, and a town name is a coarse bias that still does not rank by distance.
- **Rejected: narrowing her tools after a search** (only search tools for the rest of the reply, once results were
  read). It kept web text away from house actions but broke searching and then acting in one turn.
- **Rejected: a URL parameter on `read_page`.** Any URL a snippet planted could then be fetched from inside the pod.
- **Rejected, for now: trafilatura or readability for a page's text.** A dependency and an image rebuild for a
  tag-stripper's job; `ashley.tools.page_text.text_of` does it with `html.parser`.
- **Rejected: offering her the search tools directly.** Raw snippets, text anyone can write, would sit in her context
  beside every house tool.

## For code and the cluster she is a front for Claude Code

"Help me out here" reaches the talking person's own Claude Code sessions through a small bridge that the person runs
where their herdr runs (`bridge/herdr/`). The bridge is a narrowing Proxy over herdr: list, read, prompt, start and
close, nothing else. A session she handed work to going `blocked` or finishing is a wake for that person alone.

- **A bridge is a personal Connection** (kind `herdr`, as `gitlab` and `github`): an `https` address, the certificate
  fingerprint and a token the bridge printed once at install, sealed bound to the person. The fingerprint is part of
  the address, `https://host:7843#sha256=<64 hex digits>`, since a row holds an address and one secret and the
  fingerprint is public; an address without it is refused. It is stored only after the bridge answers
  `GET /v1/whoami` with it, called as the connecting person (the bridge's person lock needs the id, so a kind's check
  takes the person's id). She reaches only the speaking person's bridge; an unknown speaker
  reaches none. A bridge registered to one person is reached only by that person's turns.
- **The app pins before it sends.** A connection is opened and the certificate the bridge presents is compared with
  the fingerprint before the request, token included, goes out; a different certificate is `pin_mismatch` and nothing
  is sent. A call that reaches nothing, or whose read gets no answer, is `herdr_unavailable`; a change sent and not
  answered is `unconfirmed`.
- **A bridge serves one person.** The first successful call carries the person id in a header; the bridge records
  it and refuses any other person from then on (`wrong_person`) until it is set up again. A token copied into
  another person's row still opens nothing.
- **Mutual TLS both ways.** The app presents a client certificate issued by the `ashley-bridges` CA in OpenBao; a
  bridge accepts only that CA's clients, over TLS 1.3. The bridge's own certificate is self-signed at install and
  pinned by fingerprint on the connection row, so no public CA or DNS name is needed on a home machine.
- **The bridge calls the `herdr` CLI, not the socket.** The CLI is herdr's stable interface; the socket protocol
  is private and versioned. It runs as the person's user, beside their herdr server, and exposes a typed API: it
  has no way to send keys or text to a pane or to run a command.
- **She may start and close sessions, within bounds.** A start names a directory under a root the person listed
  when setting the bridge up, a label and optionally a model; a folder that does not exist yet beneath a root is
  created (symlinks and `..` resolved first, so nothing is made outside the roots). The session list carries the roots
  as absolute paths, so she starts under one instead of guessing, and a bridge that sends none leaves them unknown
  (`null`). Anything outside the roots is `dir_not_allowed`, and a start whose
  agent does not report a state comes back `unconfirmed` with its tab closed again. A close ends the session's pane.
  She still never answers a blocked dialog: a blocked session refuses a prompt. A voice path into an agent with a
  shell must not be drivable by the TV or a guest, so these tools are offered only when the reply reaches the
  connected person alone.
- **A job session runs unattended inside its own folder.** The folder of a bench job (`<root>/ashley-jobs/j<id>`) is the one
  place the bridge starts a session with permissions already granted: a settings file, passed with `claude --settings`,
  allows Read, Edit and Write on that folder's real path and nothing else. A project `.claude/settings.json` would not do,
  since Claude Code ignores a project's allow rules until the folder is trusted, and a new folder never is. A prompt for
  anything outside the folder stops the session as before, `blocked`, for the person to answer. A bypass or skip-permissions
  mode is never used. A session she starts anywhere else gets no extra permissions.
- **Her tools are `claude_sessions`, `claude_read`, `claude_prompt`, `claude_start` and `claude_close`**
  (`ashley.tools.claude_code`), offered by the gate the code host tools use (`audience.owner_alone`, connections
  openable) and only to a person with a `herdr` connection. Prompt, start and close are not proposed first: the
  bridge's bounds above (a ready session only, a directory under the roots, no way to answer a dialog) are what keep
  them safe, and the person asked for her to drive their sessions. Rejected: a confirmation per prompt, which would
  make handing a session work a two-turn exchange the bridge already makes safe.
- **Prompting refuses rather than interleaves.** A session that is `working`, `blocked` or `unknown` is refused
  (`busy`, `blocked`, `unknown_state`) and nothing is sent; she says so. A timeout after sending is `unconfirmed`:
  she reads before she would say anything about it, and the turn's checkpoint already keeps a resumed turn from
  sending it again. Typing within `typed_quiet_s` will refuse too (`person_typing`) once the bridge reports it.
- **The session sense is a Watches kind, over the sessions she handed work to.** The mechanism, and the `claude_session`
  kind, are "Watches wake her when what a read returns changes"'s. `claude_start` and `claude_prompt` arm it (`Watches.arm`, `armed_by` `handoff`)
  from the status and `state_change_seq` the session was in, with the bench whose talk made the call, and say `watched`
  in their result so she tells the person when it could not be armed. The `watches` singleton wakes her for a
  `blocked` or `done` stop, and for an `idle` one that did not follow a `done` (the kind's `when`): `idle` is a finish someone has already looked at (herdr's seen state),
  so `done` becoming `idle` wakes nothing. A finished session stays watched: Claude Code shows finished once its
  subagents return, while a Monitor or background shell (any command past ten minutes in the foreground becomes one)
  can still wake it. Rejected: forgetting a session at `done` until her next `claude_prompt`, which left a second
  finish unseen until the person asked. Each later finish costs one turn of hers, which Initiative keeps quiet when
  there is nothing to say. The wake's id is the turn's `source`, so nothing replays. Behaviour keys on `status` and `seq`, never on the screen. A hand-off watch ends when the
  session is gone from its bridge's list, or after `handoff_hours`.
- **The woken turn runs where the work was handed over, and she decides what comes of it.** Her unprompted turn is on
  the talk of the bench whose turn made the call, while that bench is open, else on the person's phone thread, with the
  person as the one it is with; the stored message is the household's turn naming the session's label and status, and
  her brief is a note. She has that thread's tools, so she may read the session, edit the bench or prompt it again, and
  whether she tells anyone, and where, is hers (see "Web push", "A woken turn routes itself"). Rejected: holding the turn to
  `promised`, which would force a word out whatever she found; always the phone
  thread, which has none of the conversation that made the promise.
- **The bridge reports when its person last typed**, per session and overall, read from Claude Code's transcript
  (user entries a person typed), minus the prompts the bridge sent itself, since herdr's paste is recorded in the
  transcript exactly as typing is. Only a time crosses the wire. A transcript it cannot read is `null`, and an aside
  treats `null` as focus. The field exists on the wire and is always `null` until the reader is built.
- **Anyone can connect their own Claude Code**, by running the bridge where their sessions live, registered to
  their person. A session's state is that person's to hear, not the household's.
- Rejected: the fingerprint as a second stored field. It would add a column and a panel field to every kind for
  one; the address carries it and `connections.address` is the one place that parses it.
- Rejected: verifying the bridge's certificate against a CA or its name. It is self-signed on a home machine with no
  DNS name; the pin is the whole trust.
- Rejected: exposing herdr's socket, or `herdr --machine` over ssh. Either gives raw send-keys and arbitrary input,
  and ssh gives a shell. Raw send-keys stays out of the bridge for the same reason.
- Rejected: the bridge pushing events to the app. It would need credentials to the app and a reachable address on
  both sites; polling from the lease holder keeps one direction of trust and survives failover with no handoff.
- Rejected: a bridge for the whole household. Sessions run on one person's subscription and see one person's
  repositories.
- Rejected: Claude Code hooks for the focus signal. A pasted prompt fires `UserPromptSubmit` the same as a typed
  one, and the transcript already records the time.
- Rejected: her own coding agent on the API. A worse Claude Code, paid per token from API credits instead of the
  person's Claude Code subscription.
