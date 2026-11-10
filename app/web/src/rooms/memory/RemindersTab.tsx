// The Reminders tab: what she will remind the person of, soonest first, each with when, how it repeats, whom it is
// for and who set it (a reminder that waits on a deposit says its rule in place of a time), and Cancel, which asks once more before it acts. One that fired and did not reach their phone,
// or could not fire, stays here, marked, until they dismiss it.
import { useState } from 'preact/hooks';
import type { Reminder } from '../../api/types';
import { hour, locale } from '../../household/format';
import { person } from '../../session/session';
import { cancel, loadReminders, reminders, remindersState } from './reminders';

const UNIT: Record<NonNullable<Reminder['repeat']>, [string, string]> = {
  daily: ['day', 'days'], weekly: ['week', 'weeks'], monthly: ['month', 'months'], yearly: ['year', 'years'],
};

/** "Sat 1 Nov, 09:00" from the household's wall-clock `YYYY-MM-DDTHH:MM`, read as written, never shifted by the
 * browser's own zone, in the household's locale and clock. */
export function when(localAt: string): string {
  const [date = '', time = ''] = localAt.split('T');
  const [y, m, d] = date.split('-').map(Number);
  const [hh, mm] = time.split(':').map(Number);
  const at = new Date(Date.UTC(y ?? 0, (m ?? 1) - 1, d ?? 1, hh ?? 0, mm ?? 0));
  const shown = at.toLocaleDateString(locale(), { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' });
  return `${shown}, ${at.toLocaleTimeString(locale(), { hour: hour(), minute: '2-digit', timeZone: 'UTC' })}`;
}

export function repeats(r: Reminder): string {
  if (r.on_deposit) return 'every match';
  if (!r.repeat) return 'once';
  const [one, many] = UNIT[r.repeat];
  return r.every && r.every > 1 ? `every ${r.every} ${many}` : `every ${one}`;
}

const FIRED: Record<Exclude<Reminder['state'], 'scheduled'>, string> = {
  sending: 'Fired just now: sending it to your phone.',
  undelivered: "Fired, but it hasn't reached your phone. She keeps trying for a day; her words are in your conversations.",
  failed: "She couldn't send this one when it was due.",
};

function whose(r: Reminder, me: number | undefined): string {
  const forWhom = r.person.id === me ? 'for you' : `for ${r.person.name}`;
  const by = r.made_by.id === r.person.id ? '' : r.made_by.id === me ? ' · set by you' : ` · set by ${r.made_by.name}`;
  return forWhom + by;
}

function Fired({ r }: { r: Reminder }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  if (r.state === 'scheduled') return null;
  const go = async () => {
    setBusy(true);
    const outcome = await cancel(r.id);
    setBusy(false);
    setFailed(outcome === 'unreachable' || outcome === 'failed');
  };
  return (
    <>
      <span class="rem-acts">
        <button class="btn sm ghost" type="button" disabled={busy} onClick={() => void go()}>Dismiss</button>
      </span>
      <span class={`rem-state ${r.state}`} role="status">{FIRED[r.state]}</span>
      {failed && <span class="err" role="alert">Couldn't dismiss it just now. Try again.</span>}
    </>
  );
}

function Row({ r }: { r: Reminder }) {
  const fired = r.state !== 'scheduled';
  return (
    <div class={`fact rem${fired ? ` fired ${r.state}` : ''}`} data-kind="plan">
      <span class="rem-when">{r.on_deposit ? 'On money moving' : when(r.local_at)}</span>
      <span class="rem-what">{r.what}</span>
      <span class="pill">{repeats(r)}</span>
      <span class="meta rem-whose">{r.on_deposit ? `${r.on_deposit} · ` : ''}{whose(r, person.value?.id)}</span>
      {fired ? <Fired r={r} /> : <Asking r={r} />}
    </div>
  );
}

function Asking({ r }: { r: Reminder }) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const go = async () => {
    setBusy(true);
    const outcome = await cancel(r.id);
    setBusy(false);
    setFailed(outcome === 'unreachable' || outcome === 'failed');
    setAsking(false);
  };
  return (
    <>
      <span class="rem-acts">
        {asking ? (
          <>
            <button class="btn sm" type="button" disabled={busy} onClick={() => void go()}>
              {r.repeat ? 'Cancel all' : 'Cancel it'}
            </button>
            <button class="btn sm ghost" type="button" disabled={busy} onClick={() => setAsking(false)}>Keep</button>
          </>
        ) : (
          <button class="btn sm ghost" type="button" onClick={() => setAsking(true)}>Cancel</button>
        )}
      </span>
      {failed && <span class="err" role="alert">Couldn't cancel it just now. Try again.</span>}
    </>
  );
}

export function RemindersList() {
  const state = remindersState.value;
  if (state === 'loading') return <p class="mem-none meta">Reading her reminders…</p>;
  if (state !== 'ready') {
    return (
      <div class="panel mem-down" role="alert">
        <div class="mem-down-says">
          <b>{state === 'failed' ? "Her reminders didn't load." : "Can't reach her reminders right now."}</b>
          <button class="btn" type="button" onClick={() => void loadReminders()}>Try again</button>
        </div>
      </div>
    );
  }
  if (!reminders.value.length) {
    return (
      <div class="mem-empty">
        <div class="mem-down-says">
          <b>No reminders set.</b>
          <span class="meta">Ask her to remind you of something, and it shows up here until it fires.</span>
        </div>
      </div>
    );
  }
  return (
    <>
      <div class="sec-title"><b>She will remind you</b><span class="label">soonest first</span></div>
      <div class="rows">{reminders.value.map((r) => <Row key={r.id} r={r} />)}</div>
    </>
  );
}
