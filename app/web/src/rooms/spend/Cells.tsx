// The cells of a usage row: what a span cost and used, and what a provider has left. Every state of every cell says what
// it is: an amount, "no calls", or a hatched reason, never a zero standing in for a value that was not measured.
import type { SpendBalance, SpendProvider, SpendTotals } from '../../api/types';
import { ago, costOf, count, day, money, usedLine } from './format';

const UNREPORTED = 'These calls reported no usage, so there is nothing to price.';
const UNPRICED = 'Usage was reported, but prices.json has no price for this model.';

export function UsageCell({ label, t }: { label: string; t: SpendTotals }) {
  const cost = costOf(t);
  return (
    <div class="sp-cell" role="cell">
      <span class="sp-lab">{label}</span>
      {cost.kind === 'none' && <span class="meta">no calls</span>}
      {cost.kind === 'unreported' && <span class="unk" title={UNREPORTED} tabindex={0}>no usage reported</span>}
      {cost.kind === 'unpriced' && <span class="unk" title={UNPRICED} tabindex={0}>unpriced</span>}
      {cost.kind === 'amount' && (
        <span class="sp-amt">
          <b>{money(cost.usd)}</b>
          {cost.unpriced > 0 && <span class="meta" title={`${count(cost.unpriced)} calls have no price and are not in this amount`}> + {count(cost.unpriced)} unpriced</span>}
        </span>
      )}
      {t.calls > 0 && <span class="meta">{usedLine(t)}</span>}
    </div>
  );
}

function Quota({ b, now, zone }: { b: SpendBalance; now: Date; zone: string }) {
  const q = b.quota!;
  const left = q.limit > 0 ? Math.min(100, (q.remaining / q.limit) * 100) : 0;
  return (
    <>
      <span class="sp-amt"><b>{count(q.remaining)}</b> <span class="meta">of {count(q.limit)} {q.unit} left</span></span>
      <span class="sp-meter" role="img" aria-label={`${Math.round(left)} percent left`}><i style={{ width: `${left}%` }} /></span>
      <span class="meta">
        {q.resets_at ? `resets ${day(q.resets_at, zone)} · ` : ''}read {b.read_at ? ago(b.read_at, now, zone) : ''}
      </span>
    </>
  );
}

function Balance({ b, now, zone }: { b: SpendBalance; now: Date; zone: string }) {
  switch (b.state) {
    case 'read':
      return <Quota b={b} now={now} zone={zone} />;
    case 'failed':
      return (
        <>
          <span class="unk" title="The provider did not answer this read, or refused it.">couldn't read</span>
          <span class="meta">tried {b.read_at ? ago(b.read_at, now, zone) : ''}</span>
        </>
      );
    case 'free':
      return <span class="meta">local, costs nothing</span>;
    case 'unknown':
      return <span class="unk" title={b.why ?? 'unknown'} tabindex={0}>unknown</span>;
  }
}

export function RemainingCell({ p, now, zone }: { p: SpendProvider; now: Date; zone: string }) {
  const e = p.estimate;
  return (
    <div class="sp-cell sp-rem" role="cell">
      <span class="sp-lab">Remaining</span>
      <Balance b={p.balance} now={now} zone={zone} />
      {e && (
        <span class="sp-est" title={e.unpriced_calls > 0 ? `${count(e.unpriced_calls)} calls this month have no price, so this is an upper bound` : undefined}>
          <span class="pill">estimate</span>
          <b>{e.remaining_usd >= 0 ? money(e.remaining_usd) : `${money(-e.remaining_usd)} over`}</b>
          <span class="meta">of {money(e.budget_usd)} budget{e.unpriced_calls > 0 ? ' at most' : ''}</span>
        </span>
      )}
    </div>
  );
}
