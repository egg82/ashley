// How she talks in this household: the persona sections a household may replace (her register, wit and examples),
// each with its changelog. What her replies must carry and the rules that always hold are not offered here.
import { useEffect, useState } from 'preact/hooks';
import type { PersonaChange, PersonaSection } from '../../api/types';
import { locale } from '../../household/format';
import { loadPersona, persona, personaSaid, personaState, revertPersona, savePersona } from './personaSections';
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
  const current = c.persona_version === section.persona_version;
  return (
    <li>
      <span class="meta">v{c.persona_version} · {at} · {c.what}: {c.why}</span>
      {c.body !== null && !current && (
        <button class="btn sm ghost" type="button" disabled={!why.trim()}
          onClick={() => void revertPersona(section, c.persona_version, why)}>Bring back</button>
      )}
    </li>
  );
}

function Section({ section, limits }: { section: PersonaSection; limits: { body: number; note: number } }) {
  const [draft, setDraft] = useState(inForce(section));
  const [why, setWhy] = useState('');
  const save = (e: Event) => {
    e.preventDefault();
    void savePersona(section, draft, why).then((ok) => ok && setWhy(''));
  };
  return (
    <form class="cn-form hh-form" onSubmit={save}>
      <label>
        <span class="meta">{section.label}{section.override === null ? ' · as shipped' : ' · this household\'s'}</span>
        <textarea value={draft} maxLength={limits.body} rows={6} onInput={(e) => setDraft(e.currentTarget.value)} />
      </label>
      <label>
        <span class="meta">Why</span>
        <input type="text" value={why} maxLength={limits.note} placeholder="A line on why it changes"
          onInput={(e) => setWhy(e.currentTarget.value)} />
      </label>
      <div class="dc-act">
        <button class="btn primary" type="submit" disabled={!differs(section, draft) || !why.trim()}>Save</button>
        {draft !== inForce(section) && <button class="btn sm ghost" type="button" onClick={() => setDraft(inForce(section))}>Undo</button>}
        {section.override !== null && (
          <button class="btn sm ghost" type="button" disabled={!why.trim()} onClick={() => void revertPersona(section, 0, why)}>
            Back to the shipped text
          </button>
        )}
      </div>
      <Said id={section.section} />
      {section.history.length > 0 && (
        <ul class="hh-log">{section.history.map((c) => <Change key={c.persona_version} c={c} section={section} why={why} />)}</ul>
      )}
    </form>
  );
}

function Body() {
  const p = persona.value;
  if (personaState.value === 'failed' && !p) {
    return (
      <div class="devs-body">
        <span class="unk">couldn't read how she talks</span>
        <button class="btn sm ghost" type="button" onClick={() => void loadPersona()}>Try again</button>
      </div>
    );
  }
  if (!p) return <div class="devs-body"><span class="meta">Reading how she talks…</span></div>;
  const limits = { body: p.body_limit, note: p.note_limit };
  return (
    <>
      {p.sections.map((s) => <Section key={`${s.section}:${s.persona_version}`} section={s} limits={limits} />)}
      {p.orphaned.length > 0 && (
        <p class="meta">Kept but no longer used, since this release changed those parts of her: {p.orphaned.join(', ')}</p>
      )}
    </>
  );
}

export function PersonaPanel() {
  useEffect(() => {
    void loadPersona();
    return () => void (personaSaid.value = null);
  }, []);
  return (
    <div class="panel devs">
      <div class="ph"><h3>How she talks</h3></div>
      <div class="dc-body">
        <p class="meta">Her manner, her wit and her examples are this household's to change. What her replies must carry
          and the rules she keeps whatever anyone asks are not.</p>
        <Body />
      </div>
    </div>
  );
}
