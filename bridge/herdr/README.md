# Ashley herdr bridge

A small HTTPS service that lets Ashley see and drive your Claude Code sessions. It runs on the machine where your
herdr runs, as you, and calls the `herdr` CLI. It lists your Claude sessions, reads their screens,
sends a prompt to one that is ready, starts a new one in an allowed directory, and closes one. It can also put files into
a session's `in/` folder and hand back the files the session left in `out/`, and nothing else of the session's directory.
It cannot send keys, type into a pane, or run a command.

One bridge serves one person. The first call that reaches it names the person, and any other person is refused with
`wrong_person` until you run `init` again. Ashley reaches it with mutual TLS: she presents a client certificate from
the `ashley-bridges` CA, and the bridge accepts no other.

## You need

- Python 3.11 or newer (`python3.11 -m venv`; the system `python3` on AlmaLinux 9 is 3.9) and `openssl`
- `herdr` 0.9 installed as your user in `~/.local/bin` (the install below runs its server as a service)
- the public certificate of the `ashley-bridges` CA, as a PEM file (the deployment's owner hands it over)
- user lingering, so the service runs without a login: `sudo loginctl enable-linger $USER`

## Install

From a checkout of this repository:

```bash
python3.11 -m venv ~/.local/share/ashley-herdr-bridge/venv
~/.local/share/ashley-herdr-bridge/venv/bin/pip install ./bridge/herdr
```

Set it up. `--root` is a directory sessions may be started under (repeat it for several); a start request for anything
outside the roots is refused, and one under them that does not exist yet is created.

```bash
~/.local/share/ashley-herdr-bridge/venv/bin/herdr-bridge init \
  --root ~/work --client-ca ~/ashley-bridges-ca.pem
```

`init` writes `~/.config/ashley-herdr-bridge/config.json`, makes a self-signed certificate (kept in
`~/.local/state/ashley-herdr-bridge/tls/`) and prints, once:

- the certificate **fingerprint** (sha256)
- the **token**. Only its digest is stored; if you lose it, run `init` again, which mints a new token and releases the
  bridge from whoever it was serving.

Start it, with the herdr server beside it. Both are user services, so they come back after a reboot; without
`herdr-server` the bridge still answers `whoami` but every session call fails with `herdr_unavailable`:

```bash
mkdir -p ~/.config/systemd/user
cp bridge/herdr/herdr-server.service bridge/herdr/ashley-herdr-bridge.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now herdr-server ashley-herdr-bridge
herdr session list   # the default session shows running
journalctl --user -u ashley-herdr-bridge -f
```

If you already run herdr from a terminal, stop that server first (`herdr server stop`), so the service owns it.

Open the port (7843/tcp unless you passed `--port`) to the cluster, e.g. `sudo firewall-cmd --permanent
--add-port=7843/tcp && sudo firewall-cmd --reload`.

Then, in Ashley's devices room, add a herdr connection with the address `https://<this machine>:7843`, the fingerprint
and the token. She stores it only after the bridge answers `GET /v1/whoami`.

## The API

Every request carries `Authorization: Bearer <token>` and `X-Ashley-Person: <person id>`. Bodies are JSON, except a file's
bytes; an error is `{"error": <code>}`.

| Call | Body or query | Answer |
|---|---|---|
| `GET /v1/whoami` | | `bridge_version`, `herdr_version`, `person`, `capabilities` (`files` from 0.2.0; absent before) |
| `GET /v1/sessions` | | `sessions` (`id`, `label`, `dir`, `status`, `seq`, `last_typed_at`), `last_typed_at`, `roots` (the absolute paths a start may name) |
| `GET /v1/sessions/{id}/read` | `lines` 1 to 400, default 120 | `text`, `truncated`, `revision` |
| `POST /v1/sessions/{id}/prompt` | `{"text"}`, 1 to 8000 characters | `{"submitted": true}` |
| `POST /v1/sessions` | `{"dir", "label", "model"?}` | the new session |
| `POST /v1/sessions/{id}/close` | | `{"closed": true}` |
| `PUT /v1/sessions/{id}/in/{name}` | the file's bytes, with a `Content-Length` | `{"bytes"}`; written to `in/{name}`, replacing a file of that name |
| `GET /v1/sessions/{id}/out` | | `files`: `name` and `bytes` of each regular file directly in `out/` (none when `out/` is absent) |
| `GET /v1/sessions/{id}/out/{name}` | | the file's bytes, `application/octet-stream` |

`id` is the Claude session id. `status` is `idle`, `working`, `blocked`, `done` or `unknown`. `last_typed_at` is the
ISO time you last typed into the session, and the list's own `last_typed_at` the latest of its sessions' (see Last typed);
`null` when there is none or the transcript cannot be read.

| Code | Status | Meaning |
|---|---|---|
| `bad_request` | 400 | malformed body, label, model or `lines`; a file name that is not flat; an upload with no `Content-Length`, a chunked one, or a body shorter than declared |
| `bad_path` | 400 | `in/` or `out/` is a symlink or not a directory, or the file asked for is not a regular file (a symlink, a folder) |
| `bad_token` | 401 | missing or wrong token |
| `wrong_person` | 403 | another person owns this bridge, or no person was sent |
| `dir_not_allowed` | 403 | the directory is outside the roots (after symlinks and `..` are resolved) or is a file |
| `not_found` | 404 | no such route or session |
| `busy`, `blocked`, `unknown_state` | 409 | the session is `working`, `blocked` or `unknown`; nothing was sent |
| `label_taken` | 409 | a live agent already has that name |
| `too_many` | 409 | `in/` already holds `max_files` files, or `out/` holds more than that |
| `too_large` | 413 | a file over `max_file_bytes`, by its `Content-Length` or as it arrives (or the file asked for) |
| `herdr_unavailable` | 503 | herdr is not running or answered an error |
| `unconfirmed` | 504 | a change may or may not have happened: a prompt or close that timed out, or a started session that never reported a state (its tab is closed again) |

A `label` is a herdr agent name: a lowercase letter, then up to 31 of `a-z`, `0-9`, `_`, `-`.

### Files

A file `name` is flat: a letter or digit, then up to 99 of letters, digits, `.`, `_`, `-`. There is no slash and no
leading dot, so a name cannot point out of the folder. The session must be listed and its directory under a root
(otherwise `dir_not_allowed`). `in/` and `out/` sit directly in that directory and are opened without following a
symlink; a file is only ever written to `in/` (to a temporary name, then renamed) and only ever read from `out/`, so the
rest of the directory, `.env` included, is out of reach in both directions. `in/` is created by the first upload.

`max_file_bytes` (default 26214400) and `max_files` (default 32, per folder) are keys in `config.json`; edit the file
and restart the service to change them.

### Job folders

A Claude Code job Ashley hands off runs in `<root>/ashley-jobs/j<job id>`, which the bridge creates when the job starts.
For a session started in a folder of exactly that shape, and no other, the bridge writes `.ashley-job-settings.json`
beside `in/` and `out/` and starts Claude Code with `--settings` pointing at it:

```json
{"permissions": {"allow": ["Read(//<folder>/**)", "Edit(//<folder>/**)", "Write(//<folder>/**)"]}}
```

`<folder>` is the folder's real path, and `//` is Claude Code's spelling of a path from the filesystem root. The session
reads, writes and edits anything inside its own folder without asking, and nothing else is allowed: a file outside it, a
Bash command or a fetch still stops on Claude Code's permission prompt, which shows as `blocked` and waits for you. No
bypass or skip-permissions mode is used. The file is passed with `--settings` and not left as `.claude/settings.json`
because Claude Code ignores a project's allow rules until you have trusted the folder, and a new job folder is never
trusted. A folder whose path holds a character a rule would read as a pattern (a space, `*`, `[`, `(`) is refused with
`dir_not_allowed`.

The bridge keeps the newest 20 job folders (`keep_job_dirs` in `config.json`, an integer; the default applies when the key
is absent) and, each time it starts a job session, removes the older ones, by job number. It never removes a folder a
listed session runs in, or anything in `ashley-jobs` that is not named `j<digits>` and a real directory. Ashley collects a
job's `out/` and closes its session before its folder is old enough to go. The line `call=job_dirs_pruned removed=<n>`
records a removal.

### Last typed

The bridge reads Claude Code's own transcript for each listed session (`<claude dir>/projects/<project>/<session id>.jsonl`;
the claude dir is `$CLAUDE_CONFIG_DIR`, else `~/.claude`) and reports the time of the latest message you typed. A message
counts when it is a user record that is not a tool result, not `isMeta`, `isCompactSummary` or `isSidechain`, whose `origin`
is absent or `human`, and whose `promptSource` is absent, `typed` or `queued`. Messages from peer sessions, task
notifications and `claude -p` do not count.

herdr pastes a prompt Ashley sends, and Claude Code records the paste as it records typing, so the bridge keeps a ledger of
what it sent: `sent-prompts.jsonl` in the state directory, one line per prompt holding the session, a sha256 of the text
(never the text) and the time. A transcript message with the same text in that session within 300 seconds after a send
(5 before) is hers. The ledger keeps 7 days and at most 2000 prompts. Only the bytes a transcript gained since the last
list are read. Typing into a session herdr does not list is not seen.

## Upgrading

0.4.0 answers `last_typed_at`. Nothing about the other calls changed, and the settings file needs no edit. From a checkout
of this repository at the new version:

```bash
~/.local/share/ashley-herdr-bridge/venv/bin/pip install --upgrade ./bridge/herdr
systemctl --user restart ashley-herdr-bridge
~/.local/share/ashley-herdr-bridge/venv/bin/pip show ashley-herdr-bridge | grep '^Version'   # 0.4.0
journalctl --user -u ashley-herdr-bridge -n 3                                                  # call=serve status=listening
```

The token, fingerprint and recorded person are kept, herdr and its sessions are not touched, and the service files did not
change. Prompts sent before the upgrade are not in the ledger.

## Logs

One logfmt line per call to the journal: `call`, `session` (the first 8 hex digits of a sha256 of the session id),
`status`, `ms`, `bytes`, and `error` when refused. Never prompt text, screen text, file names, paths, labels, the token
or the person id. A file call is `upload`, `outputs` or `download`, and its `bytes` is the file's size.
