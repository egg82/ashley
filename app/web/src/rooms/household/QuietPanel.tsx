// The signed-in person's own quiet hours: a daily window in their own zone in which nothing she says on her own
// initiative reaches them. A reply to something they said is never held.
import { useEffect, useState } from 'preact/hooks';
import { household } from '../../household/household';
import { loadQuiet, quiet, quietSaid, quietState, saveQuiet } from './quiet';
import { hourLabel, windowLine } from './quietLine';

const HOURS = Array.from({ length: 24 }, (_, h) => h);
const SAID: Record<NonNullable<typeof quietSaid.value>, string> = {
  hours: 'Pick two different hours.',
  timezone: "That isn't a time zone she knows.",
  saved: 'Saved.',
  failed: "That didn't go through. Nothing changed.",
};

function Form({ clock, zone }: { clock: '12h' | '24h'; zone: string }) {
  const now = quiet.value;
  const [start, setStart] = useState(now?.start ?? 22);
  const [end, setEnd] = useState(now?.end ?? 7);
  const [timezone, setTimezone] = useState(now?.timezone ?? zone);
  const same = start === end;
  const hours = (id: string, value: number, set: (h: number) => void) => (
    <select id={id} value={value} onChange={(e) => set(Number(e.currentTarget.value))}>
      {HOURS.map((h) => <option key={h} value={h}>{hourLabel(h, clock)}</option>)}
    </select>
  );
  return (
    <form class="cn-form hh-quiet" onSubmit={(e) => { e.preventDefault(); void saveQuiet({ start, end, timezone: timezone.trim() }); }}>
      <label><span class="meta">From</span>{hours('hh-quiet-from', start, setStart)}</label>
      <label><span class="meta">Until</span>{hours('hh-quiet-to', end, setEnd)}</label>
      <label>
        <span class="meta">Time zone</span>
        <input type="text" value={timezone} maxLength={64} autocomplete="off" onInput={(e) => setTimezone(e.currentTarget.value)} />
      </label>
      <div class="hh-quiet-acts">
        <button class="btn primary" type="submit" disabled={same || !timezone.trim()}>{now ? 'Save' : 'Turn on'}</button>
        {now && <button class="btn ghost" type="button" onClick={() => void saveQuiet(null)}>Turn off</button>}
      </div>
    </form>
  );
}

export function QuietPanel() {
  useEffect(() => {
    void loadQuiet();
    return () => void (quietSaid.value = null);
  }, []);
  const h = household.value;
  const said = quietSaid.value;
  return (
    <section class="panel hh-quietp" aria-labelledby="hh-quiet-h">
      <div class="ph"><h3 id="hh-quiet-h">Your quiet hours</h3></div>
      <div class="dc-body">
        {quietState.value === 'failed' && (
          <p><span class="unk">couldn't read your quiet hours</span>{' '}
            <button class="btn sm ghost" type="button" onClick={() => void loadQuiet()}>Try again</button></p>
        )}
        {quietState.value === 'loading' && <span class="meta">Reading your quiet hours…</span>}
        {quietState.value === 'ready' && h && (
          <>
            <p>{quiet.value ? <>She keeps to herself from <b>{windowLine(quiet.value, h.clock)}</b>.</> : 'None set. She may speak up at any hour.'}</p>
            <Form key={quiet.value ? windowLine(quiet.value, h.clock) : 'none'} clock={h.clock} zone={h.timezone} />
            {said && <div class={said === 'saved' ? 'dc-note' : 'dc-note bad'} role={said === 'saved' ? 'status' : 'alert'}><span>{SAID[said]}</span></div>}
            <p class="meta">Inside them nothing she does on her own reaches you: remarks, greetings, house and watch notices. An answer to something you said still comes.</p>
          </>
        )}
      </div>
    </section>
  );
}
