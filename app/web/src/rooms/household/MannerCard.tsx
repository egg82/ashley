// One section of how she talks: the text she uses now, and an editor that opens in place with its reason, its way back and its changelog.
import { useState } from 'preact/hooks';
import type { PersonaChange, PersonaSection } from '../../api/types';
import { locale } from '../../household/format';
import { personaSaid, revertPersona, savePersona } from './personaSections';
import type { PersonaSaid } from './personaSections';
import { differs, inForce } from './personaText';

const SAID: Record<PersonaSaid, [string, 'ok' | 'bad']> = {
  saved: ['Saved. She talks this way from her next reply.', 'ok'],
  reverted: ['Brought back. She talks this way from her next reply.', 'ok'],
  stale: ['Someone changed this section meanwhile, so nothing was saved. It now shows their version.', 'bad'],
  unchanged: ['That is what she already uses, so nothing changed.', 'bad'],
  no_such_version: ['That version has no text to bring back.', 'bad'],
  bad_body: ['The text is empty or too long, so nothing was saved.', 'bad'],
  bad_note: ['Say why in a line, so nothing was saved yet.', 'bad'],
  locked: ['This part of her is not one a household changes.', 'bad'],
  failed: ["That didn't go through. Nothing changed.", 'bad'],
};

function Said({ id }: { id: string }) {
  const s = personaSaid.value;
  if (!s || s.section !== id) return null;
  const [text, tone] = SAID[s.said];
  return <div class={`dc-note ${tone}`} role={tone === 'bad' ? 'alert' : 'status'}><span>{text}</span></div>;
}

function Change({ c, section, why }: { c: PersonaChange; section: PersonaSection; why: string }) {
  const at = new Date(c.at).toLocaleString(locale(), { dateStyle: 'medium', timeStyle: 'short' });
  return (
    <li>
      <span class="meta">v{c.persona_version} · {at} · {c.what}: {c.why}</span>
      {c.body !== null && c.persona_version !== section.persona_version && (
        <button class="btn sm ghost" type="button" disabled={!why.trim()}
          onClick={() => void revertPersona(section, c.persona_version, why)}>Bring back</button>
      )}
    </li>
  );
}

function Editor({ section, limits, done }: { section: PersonaSection; limits: { body: number; note: number }; done: () => void }) {
  const [draft, setDraft] = useState(inForce(section));
  const [why, setWhy] = useState('');
  const save = (e: Event) => {
    e.preventDefault();
    void savePersona(section, draft, why).then((ok) => ok && setWhy(''));
  };
  return (
    <form class="cn-form hh-edit" onSubmit={save}>
      <textarea class="hh-text" aria-label={section.label} value={draft} maxLength={limits.body} rows={5}
        onInput={(e) => setDraft(e.currentTarget.value)} />
      <span class="meta hh-count">{draft.length.toLocaleString(locale())} of {limits.body.toLocaleString(locale())}</span>
      <label>
        <span class="meta">Why</span>
        <input type="text" value={why} maxLength={limits.note} placeholder="A line on why it changes" onInput={(e) => setWhy(e.currentTarget.value)} />
      </label>
      <div class="dc-act">
        <button class="btn sm primary" type="submit" disabled={!differs(section, draft) || !why.trim()}>Save</button>
        <button class="btn sm ghost" type="button" onClick={done}>Keep as is</button>
        {section.override !== null && (
          <button class="btn sm ghost" type="button" disabled={!why.trim()} onClick={() => void revertPersona(section, 0, why)}>
            Back to the shipped text
          </button>
        )}
      </div>
      {section.history.length > 0 && (
        <ul class="hh-log">{section.history.map((c) => <Change key={c.persona_version} c={c} section={section} why={why} />)}</ul>
      )}
    </form>
  );
}

export function MannerCard({ section, limits }: { section: PersonaSection; limits: { body: number; note: number } }) {
  const [editing, setEditing] = useState(false);
  const mine = section.override !== null;
  return (
    <article class="panel hh-card">
      <header>
        <h3>{section.label}</h3>
        <span class="label">{mine ? `Your version ${section.persona_version}` : 'As shipped'}</span>
      </header>
      {editing ? <Editor section={section} limits={limits} done={() => setEditing(false)} /> : (
        <>
          <p class="hh-prose">{inForce(section)}</p>
          <div class="dc-act">
            <button class="btn sm" type="button" onClick={() => setEditing(true)}>Edit</button>
            {section.history.length > 0 && <span class="meta">{section.history.length} earlier {section.history.length === 1 ? 'change' : 'changes'}</span>}
          </div>
        </>
      )}
      <Said id={section.section} />
    </article>
  );
}
