// The summary: what is asking for a person, the counts, and a link to each group. On a wide screen it is the room's left
// rail; on a phone it is the top of the room.
import { reduced } from '../../../shell/motion';
import type { Standing } from './standing.ts';

export interface Jump {
  id: string;
  title: string;
}

function go(id: string): void {
  document.getElementById(id)?.scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth', block: 'start' });
}

export function Rail({ standing, jumps }: { standing: Standing; jumps: readonly Jump[] }) {
  return (
    <aside class="rr-rail">
      <p class="rr-lede" role="status"><b>{standing.strong}</b> {standing.rest && <i>{standing.rest}</i>}</p>
      {standing.total > 0 && (
        <dl class="rr-counts">
          <div class={standing.needYou > 0 ? 'attn' : ''}><dt class="meta">need you</dt><dd>{standing.needYou}</dd></div>
          <div><dt class="meta">not flagged</dt><dd>{standing.notFlagged}</dd></div>
          <div><dt class="meta">personal</dt><dd>{standing.personal}</dd></div>
        </dl>
      )}
      {jumps.length > 0 && (
        <nav aria-label="Groups">
          {jumps.map((j) => <button key={j.id} type="button" class="rr-jump" onClick={() => go(j.id)}>{j.title}</button>)}
        </nav>
      )}
    </aside>
  );
}
