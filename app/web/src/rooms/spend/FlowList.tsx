// The flow picture on a phone: the same flows as a ranked list of task to provider, each with a bar drawn in the
// certainty grammar. A row opens in place to its exact figures.
import { Figure } from './Cells';
import { linesOf } from './detail';
import { cableKind, type FlowGraph } from './flowModel';
import { usdOf } from './certainty';
import { taskName } from './routeChoice';

export function FlowList({ g }: { g: FlowGraph }) {
  return (
    <ol class="sp-rank" aria-label="Calls from each task to the provider that answered, biggest first">
      {g.flows.map((f) => {
        const usd = usdOf(f.span);
        const kind = cableKind(f.span);
        const share = usd !== null && g.peak > 0 ? Math.max(3, (usd / g.peak) * 100) : 100;
        return (
          <li key={f.id}>
            <details>
              <summary>
                <span class="sp-rank-name">
                  <b>{taskName(f.task)}</b>
                  <span class="meta">{g.providers.find((p) => p.id === f.provider)?.label}</span>
                </span>
                <Figure span={f.span} />
                <span class={`sp-bar ${kind}`} aria-hidden="true"><i style={{ width: `${share}%` }} /></span>
              </summary>
              <dl class="sp-lines">
                {linesOf(f.totals, f.span).flatMap(([k, v]) => [<dt key={`k${k}`}>{k}</dt>, <dd key={`v${k}`}>{v}</dd>])}
              </dl>
            </details>
          </li>
        );
      })}
    </ol>
  );
}
