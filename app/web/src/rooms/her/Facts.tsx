// The rows she set on a bench, shown beside her reply once each (`WireReceipts.choice_rows`): a choice with what it is about
// and its options as buttons, hers pressed; a tap sets the row as the person's, and the bench reads back as for any
// change of theirs. A guessed number a check rests on has no options, so it is read here and answered in the talk.
import { useId, useState } from 'preact/hooks';
import type { WireReceipts } from '../../api/types';
import { ApiError } from '../../api/client';
import { setChoice } from '../../api/choices';
import { load as reloadSession } from '../../session/session';
import { copy } from './receiptCopy.ts';
import { factRows, keyOf, whyNotSet, type FactRow } from './facts.ts';

function Row({ row, tap, busy }: { row: FactRow; tap: (value: string) => void; busy: boolean }) {
  const label = useId();
  if (!row.options.length) {
    return <li><span class="receipt-head">{row.fact.label}</span><span class="fact-value">{row.picked}</span></li>;
  }
  return (
    <li>
      <span class="receipt-head" id={label}>{row.fact.label}</span>
      <span class="fact-options" role="group" aria-labelledby={label}>
        {row.options.map((o) => (
          <button key={o} type="button" class="fact-option" aria-pressed={o === row.picked} disabled={busy}
            onClick={() => o !== row.picked && tap(o)}>{o}</button>
        ))}
      </span>
    </li>
  );
}

export function Facts({ receipts }: { receipts: WireReceipts }) {
  const [tapped, setTapped] = useState<ReadonlyMap<string, string>>(new Map());
  const [busy, setBusy] = useState<string | null>(null);
  const [why, setWhy] = useState<string | null>(null);
  const rows = factRows(receipts, tapped);
  if (!rows.length) return null;
  const tap = async (row: FactRow, value: string) => {
    const key = keyOf(row.fact);
    setBusy(key);
    setWhy(null);
    try {
      await setChoice(row.fact, value);
      setTapped(new Map(tapped).set(key, value));
    } catch (error) {
      const status = error instanceof ApiError ? error.status : undefined;
      if (status === 401) void reloadSession();
      setWhy(whyNotSet(status));
    }
    setBusy(null);
  };
  return (
    <div class="receipt receipt-facts" role="group" aria-label={copy.facts}>
      <div class="receipt-title">{copy.facts}</div>
      <ul class="receipt-list">
        {rows.map((r) => <Row key={keyOf(r.fact)} row={r} busy={busy === keyOf(r.fact)} tap={(v) => void tap(r, v)} />)}
      </ul>
      {why && <span class="m-err" role="alert">{why}</span>}
    </div>
  );
}
