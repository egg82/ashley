// What she may just do: per kind of action, whether she does it or offers it first when she acts on her own. The
// person's own choice; a person asking her directly is always the yes.
import { useEffect } from 'preact/hooks';
import type { TrustRow } from '../../api/types';
import { loadTrust, setTrust, trust, trustSaid, trustSaving, trustState } from './trust';
import { lockedLine } from './trustChoices';

const SAID: Record<NonNullable<typeof trustSaid.value>, string> = {
  saved: 'Saved.',
  failed: "That didn't go through. Nothing changed.",
  changed: 'These changed since you opened them. Showing the latest.',
  refused: "She can't do that one without asking. Nothing changed.",
};
const CHOICES: { value: TrustRow['value']; label: string }[] = [
  { value: 'act', label: 'Just does it' },
  { value: 'offer', label: 'Asks first' },
];

function Row({ row }: { row: TrustRow }) {
  const why = lockedLine(row);
  const busy = trustSaving.value !== null;
  return (
    <div class="hh-trust-row" role="group" aria-label={row.label}>
      <span class="hh-trust-what">{row.label}</span>
      <div class="hh-trust-pick">
        {CHOICES.map((c) => (
          <button key={c.value} type="button" class={row.value === c.value ? 'btn sm primary' : 'btn sm ghost'}
            aria-pressed={row.value === c.value} disabled={busy || (why !== null && c.value === 'act')}
            onClick={() => row.value !== c.value && void setTrust(row.kind, c.value)}>
            {c.label}
          </button>
        ))}
      </div>
      {why && <span class="meta hh-trust-why">{why}</span>}
    </div>
  );
}

export function TrustPanel() {
  useEffect(() => {
    void loadTrust();
    return () => void (trustSaid.value = null);
  }, []);
  const said = trustSaid.value;
  const t = trust.value;
  return (
    <section class="panel hh-trustp" aria-labelledby="hh-trust-h">
      <div class="ph"><h3 id="hh-trust-h">What she may just do</h3></div>
      <div class="dc-body">
        {trustState.value === 'failed' && (
          <p><span class="unk">couldn't read your choices</span>{' '}
            <button class="btn sm ghost" type="button" onClick={() => void loadTrust()}>Try again</button></p>
        )}
        {trustState.value === 'loading' && <span class="meta">Reading your choices…</span>}
        {trustState.value === 'ready' && t && (
          <>
            <p class="meta">When she acts on her own, not when you ask. Anything you ask her for she does.</p>
            {t.rows.map((r) => <Row key={r.kind} row={r} />)}
            {trustSaving.value && <span class="meta" role="status">Saving…</span>}
            {said && <div class={said === 'saved' ? 'dc-note' : 'dc-note bad'} role={said === 'saved' ? 'status' : 'alert'}><span>{SAID[said]}</span></div>}
          </>
        )}
      </div>
    </section>
  );
}
