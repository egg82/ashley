// A bench's kind of work, which she sets and the person may change, and the method (skill) that kind loads: its text,
// how often it was edited, the changelog with a rollback to any live version, the pin that makes her edits wait for
// approval, and her edit waiting when it does.
import { useEffect, useState } from 'preact/hooks';
import type { BenchDetail, SkillDetail, SkillVersion, WorkshopKinds } from '../../../api/types';
import { day } from '../../memory/facts';
import { change, loadSkill, setWork, skill, slugOf, trouble } from '../model/method';

function who(v: SkillVersion): string {
  return v.author === 'ashley' ? 'hers' : 'yours';
}

function Waiting({ kind, v, body }: { kind: string; v: SkillVersion; body: string | null }) {
  return (
    <div class="ws-m-wait" role="group" aria-label="Her edit waiting">
      <b>Her edit waits for you</b>
      <span class="meta">{v.what} — {v.why}</span>
      {body && <pre class="ws-m-text">{body}</pre>}
      <span class="ws-acts">
        <button class="btn sm primary" type="button" onClick={() => void change(kind, { version: v.skill_version, approve: true })}>Approve</button>
        <button class="btn sm" type="button" onClick={() => void change(kind, { version: v.skill_version, approve: false })}>Decline</button>
      </span>
    </div>
  );
}

function Log({ s }: { s: SkillDetail }) {
  if (s.changelog.length === 0) return <p class="meta">No edits yet. Every edit lands here with what and why.</p>;
  return (
    <ol class="ws-m-log">
      {s.changelog.map((v) => (
        <li key={v.skill_version} data-status={v.status}>
          <span class="ws-m-v">v{v.skill_version}</span>
          <span class="ws-m-what">{v.what}<span class="meta"> — {v.why} · {who(v)} · {day(v.at)}{v.status !== 'live' ? ` · ${v.status === 'proposed' ? 'waiting' : 'declined'}` : ''}</span></span>
          {v.status === 'live' && v.skill_version !== s.skill_version && (
            <button class="btn sm ghost" type="button" onClick={() => void change(s.kind, { rollbackTo: v.skill_version })}>Roll back to this</button>
          )}
        </li>
      ))}
    </ol>
  );
}

function Panel({ s }: { s: SkillDetail }) {
  return (
    <div class="ws-m-panel">
      <label class="ws-m-pin">
        <input type="checkbox" checked={s.pinned} onChange={(e) => void change(s.kind, { pin: e.currentTarget.checked })} />
        Hold her edits for my approval
      </label>
      {s.waiting && <Waiting kind={s.kind} v={s.waiting} body={s.waiting_body} />}
      <pre class="ws-m-text">{s.body}</pre>
      <Log s={s} />
    </div>
  );
}

const NEW = '\u0000new';

function Start({ id, done }: { id: number; done: () => void }) {
  const [label, setLabel] = useState('');
  const slug = slugOf(label);
  const go = async () => {
    if (await setWork(id, slug, label.trim())) done();
  };
  return (
    <span class="ws-ask" role="group" aria-label="Start a kind of work">
      <input type="text" value={label} maxLength={60} placeholder="What to call it" aria-label="Name of the kind of work"
             onInput={(e) => setLabel(e.currentTarget.value)} onKeyDown={(e) => e.key === 'Enter' && slug && void go()} />
      <button class="btn sm primary" type="button" disabled={!slug} onClick={() => void go()}>Start it</button>
      <button class="btn sm ghost" type="button" onClick={done}>Never mind</button>
    </span>
  );
}

interface Props {
  bench: BenchDetail;
  rules: WorkshopKinds | null;
}

export function Method({ bench, rules }: Props) {
  const b = bench.bench;
  const [open, setOpen] = useState(false);
  const [starting, setStarting] = useState(false);
  useEffect(() => void loadSkill(b.work), [b.work, bench]);
  const s = skill.value;
  const here = s && s.kind === b.work ? s : null;
  const kinds = rules?.work_kinds ?? [];
  return (
    <div class="ws-method">
      <label class="ws-m-kind">
        <span class="meta">Kind of work</span>
        <select value={b.work ?? ''} disabled={b.closed_at !== null}
                onChange={(e) => (e.currentTarget.value === NEW ? setStarting(true) : void setWork(b.id, e.currentTarget.value || null))}>
          <option value="">Not set yet</option>
          {kinds.map((k) => <option key={k.name} value={k.name}>{k.label}</option>)}
          <option value={NEW}>Another kind…</option>
        </select>
      </label>
      {starting && <Start id={b.id} done={() => setStarting(false)} />}
      {b.work && (
        <span class="ws-m-sum">
          {here ? <>Method v{here.skill_version} · {here.edits === 1 ? '1 edit' : `${here.edits} edits`}{here.pinned ? ' · held for you' : ''}{here.seeded_from ? ` · from ${here.seeded_from}` : ''}</>
            : <span class="meta">No method written for this yet. She writes one as she learns what works.</span>}
          {here?.waiting && <span class="pill">her edit waits</span>}
        </span>
      )}
      {here && <button class="btn sm ghost" type="button" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? 'Hide method' : 'Read method'}</button>}
      {trouble.value && <span class="meta" role="alert">{trouble.value}</span>}
      {here && open && <Panel s={here} />}
    </div>
  );
}
