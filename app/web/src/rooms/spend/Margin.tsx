// A provider's margin: what it has left, as itself reports it or as unknown with the reason, and the household's monthly
// budget as an estimate or "None set". Beside the table on a wide screen, under it on a phone.
import type { SpendBalance, SpendProvider } from '../../api/types';
import { budgetOf, leftPct } from './ledger';
import { ago, count, day, money } from './format';

function Quota({ b, now, zone }: { b: SpendBalance; now: Date; zone: string }) {
  const q = b.quota!;
  const pct = leftPct(q);
  return (
    <>
      <span class="sp-left"><b>{count(q.remaining)}</b> {q.unit}</span>
      <span class="meta">of {count(q.limit)}, {count(q.used)} used{q.resets_at ? `. Renews ${day(q.resets_at, zone)}.` : '.'}</span>
      <span class="sp-meter" role="img" aria-label={`${Math.round(pct)} percent left`}><i style={{ width: `${pct}%` }} /></span>
      {b.read_at && <span class="meta">Read {ago(b.read_at, now, zone)}</span>}
    </>
  );
}

function Left({ p, now, zone }: { p: SpendProvider; now: Date; zone: string }) {
  const b = p.balance;
  switch (b.state) {
    case 'read':
      return b.quota ? <Quota b={b} now={now} zone={zone} /> : null;
    case 'failed':
      return (
        <>
          <span class="sp-down-tag">couldn't read</span>
          <span class="meta">Tried {b.read_at ? ago(b.read_at, now, zone) : 'just now'}; the provider didn't answer or refused.</span>
        </>
      );
    case 'free':
      return <span class="meta">Runs here, nothing to run out of.</span>;
    case 'unknown':
      return (
        <>
          <span class="sp-tag sp-hollow">unknown</span>
          {b.why && <span class="sp-why">{b.why}</span>}
          {b.docs_url && <a class="meta" href={b.docs_url} target="_blank" rel="noopener noreferrer">Billing documentation</a>}
        </>
      );
  }
}

function Budget({ p }: { p: SpendProvider }) {
  const b = budgetOf(p);
  if (b.kind === 'none') return <span class="meta">None set</span>;
  const { left } = b;
  return (
    <>
      <span class="sp-est-line">
        <span class="sp-est-tag">≈ {left.over ? `${money(left.usd)} over` : `${left.atMost ? 'at most ' : ''}${money(left.usd)} left`}</span>
        <span class="meta">estimate</span>
      </span>
      <span class="meta">of {money(b.budgetUsd)} a month{left.atMost ? '; calls with no price are not counted' : ''}</span>
    </>
  );
}

export function Margin({ p, now, zone }: { p: SpendProvider; now: Date; zone: string }) {
  return (
    <aside class="sp-margin" aria-label={`${p.label}: what is left`}>
      <div class="sp-m-block">
        <span class="label">Left with {p.label}</span>
        <Left p={p} now={now} zone={zone} />
      </div>
      {p.kind !== 'local' && (
        <div class="sp-m-block">
          <span class="label">Monthly budget</span>
          <Budget p={p} />
        </div>
      )}
    </aside>
  );
}
