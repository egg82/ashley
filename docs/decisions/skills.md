# Skills and taste

Her method documents per kind of work, and what a household may override.

## Her skills are method documents she edits

- **A skill is data**: a method document (Type Object), not code, one per kind of work. **Kinds of work are hers**: a
  kind is a household's row (`skill_kinds`: a slug and a label), started by her or the person when they set a bench's
  work to a name the household has none for, and its first skill version is written the same way. A slug is checked by
  shape (`app/ashley/skills/skills.json`: pattern and length), never against a list, so she is never handed a gap
  ("electronics", "garden planning") to give back.
  Rejected: a fixed list of kinds in `skills.json` (a kind a bench needs and the list lacks would be hers to ask a
  person for). A bench carries its kind, `benches.work`; she sets it with `bench_work` (a new kind needs its `label`)
  and the person may change it in the bench's bar, which can also start a kind. It is a bench field changed by an operation outside
  the command log, as closing is, not a Command: a label the person overwrites needs no replay or undo.
  Rejected: a Command (a dozen files of codec, decide and effects, for a label replay and undo have nothing to do with), a `skill`
  piece kind (a piece is bench-scoped and a person's; a skill outlives the bench and serves every bench of that kind).
- **A household's skills are the household's.** Versions are stored per household and kind
  (`skill_versions`), so what she learns in one household never reaches another and any person of the household sees the
  same method. Until the household first edits a kind, the skill is the seed that ships (`ashley.skills.seeds`,
  `app/ashley/skills/seeds/<kind>.md`, whose front matter names the kind, its label and the source skill it was
  `seeded_from`; a seed's kind exists for every household). The seeds are code, 3d, research and writing, each rewritten
  for a bench from a personal Claude Code skill with every host, path, name, dated incident and Claude Code mechanic removed
  (`tests/test_skill_seeds.py` scans for those shapes). They are loaded once when the process wires and read at each
  use, never copied into a household's rows, so a household's edit is never touched by a seed that changes later; the
  first edit replaces it for that household only, and a rollback to version 0 is the seed again. Rejected: one global
  skill she edits for everyone (one household's conversations would rewrite another's method); copying the seeds into
  every household's rows at creation (an improved seed would never reach an unedited kind); a skill per person (method
  is not personal, and each person would teach her again).
- **The skill loads beside the bench tools' instructions, in the stable layer.** `ashley.tools.bench_skills.BenchSkillTools`
  puts the bench's skill in its catalogue's instructions, which `persona.system` places in `stable`, before the moment
  and the history (the cache layers in "Every channel shares one turn loop"). It is read when a turn's tools are built, so a kind she
  sets or a skill she edits reaches the prompt of the person's next message (setting the kind gives her the skill as
  the tool's result meanwhile), and a conversation pays one cache write when a skill changes, which is rare. Each load logs `skills.loaded` with the bench, kind and version. Rules that must always hold
  stay in her fixed guidance, never in a skill; the tool guidance says a skill never overrides them.
- **She edits skills freely and an edit is live at once.** `skill_edit` replaces the whole body from the version she
  read (`stale` otherwise) with a line each of what and why; `skill_rollback` makes an earlier body (0 is the seed)
  the next version. Versions are append-only, so a rollback is a new version and the changelog (what, why, which bench,
  who) never loses an edit. The edit count per skill is the number of live versions. A person's rollback, pin and
  approvals are on the bench's bar (`app/ashley/api/skills.py`); her `skill_read` gives her the changelog.
- **Approval applies only to a skill the person pins.** Her edit of a pinned kind is stored `proposed` and loads only
  when a person approves it; an approval is refused `stale` once the live version has moved past the one she
  proposed against. Rejected: approval of every edit, since routine edits are too frequent for it to mean anything.

## A household may override her taste, never her contract

- **Units follow `Household.unit_system` by field, in three places.** The persona's locked text carries
  `{thermostat_step}`, written by code as the size of a thermostat change she asks before making (`ashley.persona.facts.in_units`;
  five degrees imperial, three metric); the `# This household` section says the units. The house tools' description names
  the temperature's shape and no number, since the specs are built once for every household and a quoted number becomes
  the template. A recipe piece's amounts lead with a line's metric equivalent for a metric household
  (`ashley.people.units.metric_of`, `workshop.recipe.scaled`), a line without one being scaled as it was written.
- **The household's language follows `Household.locale` by field, in two places.** `ashley.people.language.language_of`
  reads the subtag before the first dash against `people/languages.json` (Whisper's ISO 639-1 languages, which is what
  Wyoming's faster-whisper and OpenAI transcription accept); a locale outside it has no language and every caller keeps
  its shipped default. Speech-to-text: where the household is known (a satellite's device, the page's signed-in person
  or kiosk device) the call's `Heard.language` carries the code, and each `Transcriber` sends it in place of its route's
  `language` param (Wyoming `Transcribe.language`, OpenAI `language`), so `routes.json` keeps its default for a
  household that cannot be read. Reply: for a household whose language is not English, `# This household` adds one
  line naming the language (`ashley.persona.facts.LANGUAGE`); an English household's prompt is unchanged. A person who writes or speaks to her in another language is answered in theirs, the household's language
  being the default; that is a rule in the prompt, never code over their words. Spoken audio is still transcribed in
  the household's language, so another language works in a chat, not aloud. Rejected: detecting the spoken
  language per utterance, since the household has already said which it speaks.

- **The persona's taste is the household's; its contract ships.** The shipped register, wit and examples are one
  household's taste, so a household replaces them from the Household room's persona panel. Which sections are taste is
  an explicit field on each section's marker line in `app/ashley/persona/ashley.md`
  (`<!-- section id=wit override=allowed label="…" -->`, `ashley.persona.sections`), never the words of a heading.
  Everything `locked` stays the shipped text: her reply's fields and their rules, the rules that hold whatever anyone
  asks, acting on the house, memory, and every kind file and the errand section, which carry no markers and are wholly
  locked. A heading belongs to the text before the section it heads, so an override replaces a body and never a heading.
- **Fits into Skills, as a second family in its changelog.** An override is a versioned document per household and
  key, which is what a skill is: `skill_versions` has a `family` (`skill` or `persona`, in the key), and a persona
  section's id goes in `kind`. Versions are append-only and a revert is a new version, as a skill's rollback is; the
  writes take an advisory lock per household and section. What differs is held by the table: a `persona` row is
  always a person's and `live` (no proposals, no bench), and its body may be null, meaning "the shipped text", so a
  household that reverts follows the persona as it improves instead of keeping a copy of the old one. A household
  with no rows gets the shipped persona.
- **The lock is enforced twice, in code.** `PersonaWriter` refuses an id that is not an `allowed` section (`locked`),
  and `sections.render` applies an override only to an `allowed` section of the text it renders, so a row for a
  locked id, however it got there, never reaches a prompt. A section a later release renames, removes or locks keeps
  its rows but stops applying; the persona page lists it as orphaned.
- **Only a person writes them.** Overrides change how she talks and judges, so they are written only through the
  persona route: the writer is its own service (`ashley.skills.persona_write`), imported only by `app/ashley/api/persona.py`
  and the wiring (`tests/test_settings_boundary.py`), as the household's own fields are. Channels read through
  `ashley.skills.persona.PersonaOverrides`, which cannot write.
- **Read for every reply, never cached.** The reply and errand paths read the household's heads from the database
  with the rest of the turn's reads and render them into the stable layer, so a change saved on any pod reaches the next
  reply on every pod of both sites, and costs a conversation one cache write. When they cannot be read the reply uses
  the shipped persona and logs `persona.overrides_unreachable`.
- Rejected: a separate table for persona versions (a second versioning store that would drift from the skills'
  semantics); overrides as skills of a reserved kind (her `skill_edit` reaches every kind of a household, and a
  prefix in `kind` is shape-sniffing); choosing the overridable sections by their headings (behaviour keyed on
  words); a whole-file override (it would carry the contract with it, unlocked); a per-pod cache (one indexed read per
  reply is cheap, and a cache needs a staleness bound that a person saving and then talking would notice).
