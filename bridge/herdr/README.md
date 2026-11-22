# Ashley herdr bridge

A small HTTPS service that lets Ashley see and drive your Claude Code sessions. It runs on the machine where your
herdr runs, as you, and calls the `herdr` CLI. It lists your Claude sessions, reads their screens,
sends a prompt to one that is ready, starts a new one in an allowed directory, and closes one. It can also put files into
a session's `in/` folder and hand back the files the session left in `out/`, and nothing else of the session's directory.
It cannot send keys, type into a pane, or run a command. It also reports what the machine can do (`GET /v1/machine`):
the facts Ashley picks a machine by, each read live from a fixed source.
It lists the machine's USB webcams and takes one still from one when asked (`GET /v1/cameras`).

One bridge serves one person, and runs on one machine: with several machines, run one bridge on each and add each as its own
connection (up to four, each under a label that names the machine, which is what Ashley calls it). The first call that reaches it names the person, and any other person is refused with
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

Start it. Both services are user services, so they come back after a reboot; without a running herdr server the bridge
still answers `whoami` but every session call fails with `herdr_unavailable`.

A machine with no herdr server running installs both units, and the bridge unit starts the server through its `Wants=`:

```bash
mkdir -p ~/.config/systemd/user
cp bridge/herdr/herdr-server.service bridge/herdr/ashley-herdr-bridge.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now herdr-server ashley-herdr-bridge
herdr session list   # the default session shows running
journalctl --user -u ashley-herdr-bridge -f
```

A machine whose herdr already runs from a terminal installs **only** `ashley-herdr-bridge.service`, and leaves its
own server alone. Do not install `herdr-server.service` there: the bridge unit `Wants=` it, so with both present
systemd starts a second server, which exits "already running", and restarts it every five seconds for ever.

```bash
mkdir -p ~/.config/systemd/user
cp bridge/herdr/ashley-herdr-bridge.service ~/.config/systemd/user/
sed -i 's/ herdr-server.service//g' ~/.config/systemd/user/ashley-herdr-bridge.service
systemctl --user daemon-reload
systemctl --user enable --now ashley-herdr-bridge
```

The `sed` drops the unit's `Wants=` and `After=` on `herdr-server.service`, which this machine does not have.

Open the port (7843/tcp unless you passed `--port`) to the cluster, e.g. `sudo firewall-cmd --permanent
--add-port=7843/tcp && sudo firewall-cmd --reload`.

Then, in Ashley's devices room, add a herdr connection with the address `https://<this machine>:7843`, the fingerprint
and the token, labelled with this machine's name (`vm`, `laptop`); repeat the install and this step on each machine. A
laptop needs the cluster to reach its port wherever the laptop is. She stores it only after the bridge answers `GET /v1/whoami`.

## The API

Every request carries `Authorization: Bearer <token>` and `X-Ashley-Person: <person id>`. Bodies are JSON, except a file's
bytes; an error is `{"error": <code>}`.

| Call | Body or query | Answer |
|---|---|---|
| `GET /v1/whoami` | | `bridge_version`, `herdr_version`, `person`, `capabilities` (`files` from 0.2.0, `machine` from 0.5.0; absent before) |
| `GET /v1/machine` | | the machine report (see Machine report) |
| `GET /v1/cameras` | | `cameras`: `id` and `name` of each USB webcam (see Cameras) |
| `GET /v1/cameras/{id}/still` | | one JPEG frame from that camera, `application/octet-stream` |
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
| `camera_busy` | 409 | another program holds the camera |
| `camera_failed` | 502 | `ffmpeg` failed, timed out or gave no frame |
| `ffmpeg_missing` | 503 | `ffmpeg` is not installed on the machine |
| `herdr_unavailable` | 503 | herdr is not running or answered an error |
| `unconfirmed` | 504 | a change may or may not have happened: a prompt or close that timed out, or a started session that never reported a state (its tab is closed again) |

A `label` is a herdr agent name: a lowercase letter, then up to 31 of `a-z`, `0-9`, `_`, `-`.

### Cameras

`GET /v1/cameras` lists the machine's USB webcams from `/sys/class/video4linux`, read live. A camera shows the kernel
two nodes, one for video and one for metadata; the video node is the one whose `index` file reads 0, and only it is listed.
A camera's `id` is its USB `vendor:product` and the sysfs path of its port (`046d_0825_3_3`): it stays the same across a
reboot with the camera in the same socket and is never a serial number. `name` is the device's own product string cut to
printable ASCII. A still is one `ffmpeg` run (`-f v4l2 -i /dev/videoN -frames:v 1`, JPEG to stdout) with fixed arguments, a
10 second limit and a 4 MiB cap; the id is looked up in the listing and never used as a path. A still needs `ffmpeg` on the
machine's `PATH` and a camera no other program is using. The bridge takes a picture only when asked.

### Machine report

`GET /v1/machine` answers what the machine is, read live for each call, so a card plugged in or a session started shows
at the next one:

| Field | Source |
|---|---|
| `hostname`, `os`, `kernel` | `gethostname`, `PRETTY_NAME` in `/etc/os-release`, `/proc/sys/kernel/osrelease` |
| `cpu` (`model`, `cores`) | `/proc/cpuinfo` |
| `memory` (`total_mb`, `available_mb`) | `/proc/meminfo` |
| `gpus` (`model`, `memory_mb` each) | `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits`, 5 second limit; `[]` when it is not installed |
| `busy` | whether herdr lists a session `working` |
| `tools` | those of `bench_tools` found on `PATH` |
| `usb` (`id` as `vendor:product`, `product`) | `idVendor`, `idProduct` and `product` under `/sys/bus/usb/devices`; root hubs left out |

A value the bridge could not read is `null` (`gpus` when `nvidia-smi` failed or timed out, `usb` when the bus cannot be
listed), never `0` or empty. The bridge still cannot run an arbitrary command, and the report does not change that: each
probe is a fixed read of a kernel file, or `nvidia-smi` with fixed arguments and a timeout. A tool in `bench_tools` is only
looked up on `PATH`, never run. No serial number, file content or environment value is read. A USB `product` is text the
device chose, so it is cut to 64 printable ASCII characters and Ashley treats the report as words from outside.

`bench_tools` is a list of program names in `config.json`, default `pio`, `sigrok-cli`, `podman`, `docker`, `python3`.
Extend it with the instruments' tools (`ccx`, `openocd`) and restart the service; a name with a path or a space is refused
at start.

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

0.6.0 adds `GET /v1/cameras` and its stills; nothing else changed, and the settings file is the same. A bridge older than
0.6.0 answers `not_found` to the camera calls, and Ashley shows that machine with no cameras. (0.5.0 added `GET /v1/machine`
and the optional `bench_tools` setting.) From a checkout of this repository at the new version:

```bash
~/.local/share/ashley-herdr-bridge/venv/bin/pip install --upgrade ./bridge/herdr
systemctl --user restart ashley-herdr-bridge
~/.local/share/ashley-herdr-bridge/venv/bin/pip show ashley-herdr-bridge | grep '^Version'   # 0.6.0
journalctl --user -u ashley-herdr-bridge -n 3                                                  # call=serve status=listening
```

The token, fingerprint and recorded person are kept, herdr and its sessions are not touched, and the service files did not
change (a machine that runs its own herdr keeps its one-unit install). Prompts sent before the upgrade are not in the ledger.

## Logs

One logfmt line per call to the journal: `call`, `session` (the first 8 hex digits of a sha256 of the session id),
`status`, `ms`, `bytes`, and `error` when refused. Never prompt text, screen text, file names, paths, labels, the token
or the person id. The machine report is `machine`, the camera list `cameras` and a camera's still `camera_still`. A file call is `upload`, `outputs` or `download`, and its `bytes` is the file's size.
