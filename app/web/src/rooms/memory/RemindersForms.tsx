// The Reminders tab's two forms: setting a reminder, and choosing the method that makes a repeating one a standing errand
// (the household's kind of work her turn follows each time it fires).
import { useEffect, useState } from 'preact/hooks';
import type { Reminder } from '../../api/types';
import { create, kinds, loadKinds, setMethod, type Written } from './reminders';
import type { Outcome } from './memory';

const REPEATS: [NonNullable<Reminder['repeat']> | '', string][] = [
  ['', 'Once'], ['daily', 'Every day'], ['weekly', 'Every week'], ['monthly', 'Every month'], ['yearly', 'Every year'],
];
const NO_METHOD = '';

export function label(method: string): string {
  return kinds.value.find((k) => k.name === method)?.label ?? method;
}

function said(outcome: Written | Outcome): string {
  return outcome === 'refused'
    ? "That can't be set: a standing errand repeats, and its kind of work needs a method written."
    : outcome === 'unreachable' ? "Can't reach her right now. Try again." : "Couldn't save that. Try again.";
}

function KindSelect({ value, onChange, disabled }: { value: string; onChange: (v: string) => void; disabled: boolean }) {
  return (
    <select value={value} disabled={disabled} aria-label="Kind of work" onChange={(e) => onChange(e.currentTarget.value)}>
      <option value={NO_METHOD}>No method: just remind</option>
      {kinds.value.map((k) => <option key={k.name} value={k.name}>{k.label}</option>)}
    </select>
  );
}

/** Sets or clears `r`'s method; closes itself once it is saved. */
export function MethodForm({ r, onDone }: { r: Reminder; onDone: () => void }) {
  const [value, setValue] = useState(r.method ?? NO_METHOD);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  useEffect(() => void loadKinds(), []);
  const save = async () => {
    setBusy(true);
    const outcome = await setMethod(r.id, value === NO_METHOD ? null : value);
    setBusy(false);
    if (outcome === 'ok' || outcome === 'gone') onDone();
    else setFailed(said(outcome));
  };
  return (
    <form class="cn-form rem-form" onSubmit={(e) => { e.preventDefault(); void save(); }}>
      <label><span class="meta">Her method for it</span><KindSelect value={value} onChange={setValue} disabled={busy} /></label>
      <span class="rem-acts">
        <button class="btn sm primary" type="submit" disabled={busy || value === (r.method ?? NO_METHOD)}>Save</button>
        <button class="btn sm ghost" type="button" disabled={busy} onClick={onDone}>Close</button>
      </span>
      {failed && <span class="err" role="alert">{failed}</span>}
    </form>
  );
}

/** Sets a new reminder for the person; with a repeat it can name a method too. */
export function NewReminder({ onDone }: { onDone: () => void }) {
  const [what, setWhat] = useState('');
  const [at, setAt] = useState('');
  const [repeat, setRepeat] = useState('');
  const [method, setMethodKind] = useState(NO_METHOD);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  useEffect(() => void loadKinds(), []);
  const ready = !busy && what.trim().length > 0 && at.length > 0;
  const save = async () => {
    setBusy(true);
    const outcome = await create({
      what: what.trim(), local_at: at, every: 1, repeat: repeat === '' ? null : (repeat as NonNullable<Reminder['repeat']>),
      method: repeat === '' || method === NO_METHOD ? null : method,
    });
    setBusy(false);
    if (outcome === 'ok') onDone();
    else setFailed(said(outcome));
  };
  return (
    <form class="cn-form rem-new" onSubmit={(e) => { e.preventDefault(); if (ready) void save(); }}>
      <label><span class="meta">What to remind you of, or what to do</span>
        <input value={what} maxLength={500} disabled={busy} onInput={(e) => setWhat(e.currentTarget.value)} /></label>
      <label><span class="meta">First time</span>
        <input type="datetime-local" value={at} disabled={busy} onInput={(e) => setAt(e.currentTarget.value)} /></label>
      <label><span class="meta">Repeats</span>
        <select value={repeat} disabled={busy} onChange={(e) => setRepeat(e.currentTarget.value)}>
          {REPEATS.map(([v, text]) => <option key={v} value={v}>{text}</option>)}
        </select></label>
      {repeat !== '' && (
        <label><span class="meta">Standing errand: her method each time</span>
          <KindSelect value={method} onChange={setMethodKind} disabled={busy} /></label>
      )}
      <span class="rem-acts">
        <button class="btn sm primary" type="submit" disabled={!ready}>{busy ? 'Saving' : 'Set it'}</button>
        <button class="btn sm ghost" type="button" disabled={busy} onClick={onDone}>Cancel</button>
      </span>
      {failed && <span class="err" role="alert">{failed}</span>}
    </form>
  );
}
