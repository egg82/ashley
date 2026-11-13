// Beside the flow picture: the exact figures behind what is picked, or behind everything when nothing is.
import type { SpendResponse } from '../../api/types';
import { Figure } from './Cells';
import { detailOf } from './detail';
import type { FlowGraph, Pick } from './flowModel';
import type { Win } from './window';

export function FlowDetail({ s, g, win, pick, onClear }: { s: SpendResponse; g: FlowGraph; win: Win; pick: Pick | null; onClear: () => void }) {
  const d = detailOf(s, g, win, pick);
  return (
    <aside class="sp-detail" aria-label="Exact figures" aria-live="polite">
      <div class="sp-detail-head">
        <h2 class="label">{pick ? 'Picked' : 'Everything'}</h2>
        {pick && <button class="btn sm ghost" type="button" onClick={onClear}>Clear</button>}
      </div>
      <b class="sp-detail-title">{d.title}</b>
      <Figure span={d.span} />
      <span class="meta">{d.sub}</span>
      <dl class="sp-lines">
        {d.lines.flatMap(([k, v]) => [<dt key={`k${k}`}>{k}</dt>, <dd key={`v${k}`}>{v}</dd>])}
      </dl>
    </aside>
  );
}
