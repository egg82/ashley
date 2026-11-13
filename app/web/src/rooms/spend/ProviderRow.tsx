// One provider's section of the ledger: its name and total, a hairline table of its tasks in the window, and its margin.
import type { SpendProvider } from '../../api/types';
import { Figure } from './Cells';
import { spanOf } from './certainty';
import { columnsOf, rowsOf, type Row, type Used } from './ledger';
import { callsOf, count } from './format';
import { Margin } from './Margin';
import { taskName } from './routeChoice';
import { whenOf, type Win } from './window';

const KIND: Record<SpendProvider['kind'], string> = { paid: 'Paid', local: 'Local', unlisted: 'Not in the catalog' };

function UsedCells({ used, columns, noUsage }: { used: Used; columns: 'tokens' | 'media'; noUsage: boolean }) {
  if (used.kind === 'tokens') {
    return (
      <>
        <span class="sp-n" data-l="in">{used.input}</span>
        <span class="sp-n" data-l="out">{used.output}</span>
        <span class="sp-n" data-l="cache read">{used.cacheRead}</span>
        <span class="sp-n" data-l="cache write">{used.cacheWrite}</span>
      </>
    );
  }
  const span = columns === 'tokens' ? 4 : 1;
  return (
    <span class={`sp-n sp-wide span-${span}`}>{used.kind === 'media' ? used.text : noUsage ? <span class="sp-tag sp-dots">no usage reported</span> : '—'}</span>
  );
}

function TaskRow({ r, columns }: { r: Row; columns: 'tokens' | 'media' }) {
  return (
    <div class="sp-tr" role="row">
      <span class="sp-tn" role="cell">{taskName(r.task)}</span>
      <div class="sp-nums" role="presentation">
        <span class="sp-n" role="cell" data-l="calls">{count(r.totals.calls)}</span>
        <UsedCells used={r.used} columns={columns} noUsage={r.span.kind === 'noUsage'} />
      </div>
      <span class="sp-cost" role="cell">{r.span.kind === 'noUsage' ? <span class="meta">—</span> : <Figure span={r.span} note />}</span>
    </div>
  );
}

export function ProviderRow({ p, win, now, zone }: { p: SpendProvider; win: Win; now: Date; zone: string }) {
  const totals = p.usage[win];
  const rows = rowsOf(p, win);
  const columns = columnsOf(rows);
  const noUsage = totals.calls - totals.metered_calls;
  return (
    <section class="sp-prov" aria-label={p.label}>
      <div class="sp-prov-main">
        <header class="sp-prov-head">
          <div>
            <h3>{p.label}</h3>
            <span class="meta">
              {totals.calls === 0 ? `No calls ${whenOf(win)}` : `${callsOf(totals.calls)}${noUsage > 0 ? `, ${count(noUsage)} reported no usage` : ''}`}
            </span>
          </div>
          <span class="pill">{KIND[p.kind]}</span>
          <span class="sp-prov-total"><Figure span={spanOf(totals)} /></span>
        </header>
        {rows.length > 0 && (
          <div class={`sp-table ${columns}`} role="table" aria-label={`${p.label} by task`}>
            <div class="sp-th" role="row">
              <span class="label" role="columnheader">Task</span>
              <span class="label sp-r" role="columnheader">Calls</span>
              {columns === 'tokens' ? (
                <>
                  <span class="label sp-r" role="columnheader">Input</span>
                  <span class="label sp-r" role="columnheader">Output</span>
                  <span class="label sp-r" role="columnheader">Cache read</span>
                  <span class="label sp-r" role="columnheader">Cache write</span>
                </>
              ) : (
                <span class="label sp-r" role="columnheader">Used</span>
              )}
              <span class="label sp-r" role="columnheader">Cost</span>
            </div>
            {rows.map((r) => <TaskRow key={r.task} r={r} columns={columns} />)}
          </div>
        )}
      </div>
      <Margin p={p} now={now} zone={zone} />
    </section>
  );
}
