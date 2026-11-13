// The top of the room: which span is shown, and its total. The total carries a "+" when it is a lower bound, with the
// counts of what it leaves out beside it.
import type { SpendResponse } from '../../api/types';
import { Figure } from './Cells';
import { leftOut, spanOf } from './certainty';
import { count, day } from './format';
import { sumTotals } from './totals';
import { startsAt, whenOf, WINDOWS, type Win } from './window';

export function WindowSwitch({ win, onPick }: { win: Win; onPick: (w: Win) => void }) {
  return (
    <div class="sp-switch" role="group" aria-label="Span">
      {WINDOWS.map((w) => (
        <button key={w.id} type="button" class={win === w.id ? 'on' : ''} aria-pressed={win === w.id} onClick={() => onPick(w.id)}>{w.label}</button>
      ))}
    </div>
  );
}

export function Hero({ s, win }: { s: SpendResponse; win: Win }) {
  const total = sumTotals(s.providers.map((p) => p.usage[win]));
  const span = spanOf(total);
  const out = leftOut(span);
  const since = startsAt(s, win);
  return (
    <div class="sp-hero">
      <div class="sp-total" aria-label={`Total ${whenOf(win)}`}>
        {span.kind === 'idle' ? <span class="sp-none">No calls {whenOf(win)}</span> : <TotalFigure span={span} />}
      </div>
      {span.kind !== 'idle' && (
        <div class="sp-counts">
          <span><b>{count(total.calls)}</b> {total.calls === 1 ? 'call' : 'calls'}</span>
          {out.unpriced > 0 && <span class="sp-c-hatch"><b>{count(out.unpriced)}</b> unpriced</span>}
          {out.noUsage > 0 && <span class="sp-c-dots"><b>{count(out.noUsage)}</b> no usage</span>}
        </div>
      )}
      {since && <span class="meta sp-since">since {day(since, s.zone)} · {s.zone} time</span>}
    </div>
  );
}

function TotalFigure({ span }: { span: ReturnType<typeof spanOf> }) {
  if (span.kind === 'measured') return <span class="sp-big"><Figure span={span} /></span>;
  if (span.kind === 'partial') {
    return (
      <span class="sp-big">
        <Figure span={{ kind: 'measured', usd: span.usd }} />
        <sup class="sp-plus" title="At least this much" tabindex={0}>+</sup>
      </span>
    );
  }
  return <span class="sp-big sp-big-unk"><Figure span={span} /></span>;
}
