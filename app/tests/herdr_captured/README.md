Answers captured from the real `herdr` 0.9.5 CLI, replayed by `tests/herdr_bridge_support.py`. Nothing here is hand-written.

Captured with `--version`, `status`, `agent list`, `tab list`, a read-only `agent get`, `agent read`, `agent prompt` and
`tab close` against targets that do not exist (the errors), and, against one throwaway session started for the purpose in a
tab labelled `bridge-capture`: `tab create`, `agent start`, `agent get`, `agent prompt`, `agent read` and `pane close`.
`agent_start_timeout.err` is a real failed start: the first attempt's shell was busy and herdr gave up waiting.

Scrubbed mechanically before commit: the home directory prefix, session UUIDs (remapped one-to-one), terminal titles
(which hold conversation topics), and the labels and directories of the sessions not started for the capture (renamed
`app-2` and `notes`). No `blocked` or `unknown` agent was captured; tests build one by replacing the
`agent_status` of a captured record.
