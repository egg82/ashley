// Where the calls went, as a picture on a wide screen and a ranked list on a phone, with the key to how sure each figure is.
import { useMemo } from 'preact/hooks';
import type { SpendResponse } from '../../api/types';
import { CertaintyKey } from './Cells';
import { FlowDetail } from './FlowDetail';
import { FlowList } from './FlowList';
import { FlowPicture } from './FlowPicture';
import { flowGraph } from './flowModel';
import { taskName } from './routeChoice';
import { picked } from './spend';
import { useNarrow } from './useNarrow';
import { whenOf, type Win } from './window';

export function FlowSection({ s, win }: { s: SpendResponse; win: Win }) {
  const g = useMemo(() => flowGraph(s, win, taskName), [s, win]);
  const narrow = useNarrow();
  const pick = picked.value && [...g.tasks, ...g.providers, ...g.flows].some((n) => n.id === picked.value!.id) ? picked.value : null;
  return (
    <section class="panel sp-flows" aria-label="Where the calls went">
      {g.flows.length === 0 ? (
        <p class="meta sp-flows-none">No calls {whenOf(win)}, so there is nothing to draw.</p>
      ) : (
        <div class="sp-flows-grid">
          {narrow ? <FlowList g={g} /> : (
            <div class="sp-pic">
              <FlowPicture g={g} pick={pick} onPick={(p) => (picked.value = p)} />
              <span class="meta">Width is cost. Beads are calls. A ? marks a cable some of whose calls are unknown.</span>
            </div>
          )}
          {!narrow && <FlowDetail s={s} g={g} win={win} pick={pick} onClear={() => (picked.value = null)} />}
        </div>
      )}
      <div class="sp-flows-foot">
        <CertaintyKey />
      </div>
    </section>
  );
}
