// The board: the person's work from `GET /api/work` in lanes, what waits on them first. It replaces the old work list;
// the list is read by `work.ts`, on the same cues.
import { loadWork, work, workState } from '../work';
import { waiting } from '../workRows';
import { BoardRow } from './BoardRow';
import { causeLine } from './cause';
import { lanes } from './lanes';

export function Board({ open }: { open: number | null }) {
  const state = workState.value;
  const items = work.value;
  if (state === 'loading' && !items.length) return <p class="meta b-quiet">Reading…</p>;
  if (state !== 'ready' && !items.length) {
    return (
      <p class="b-quiet b-down" role="alert">
        <span class="unk">couldn't read</span>
        <button class="btn sm ghost" type="button" onClick={() => void loadWork()}>Try again</button>
      </p>
    );
  }
  if (!items.length) return <p class="meta b-quiet">Nothing open.</p>;
  return (
    <div class="board">
      {(state === 'unreachable' || state === 'failed') && <p class="meta b-stale" role="status">Couldn't read it again. This is how it last stood.</p>}
      {lanes(items).map((l) => (
        <section key={l.lane} class="b-lane" data-lane={l.lane} aria-label={l.name}>
          <h2 class="label b-lh">{l.name} <span class="b-count">· {l.items.length}</span></h2>
          <ul class="b-rows">
            {l.items.map((i) => <BoardRow key={`${i.kind}:${i.id}`} item={i} cause={causeLine(i, items)} open={open} />)}
          </ul>
        </section>
      ))}
    </div>
  );
}

/** The board folded to one line: how many wait on the person, or null while it cannot be read. */
export function boardSummary(): string | null {
  const items = work.value;
  if (workState.value !== 'ready' && !items.length) return null;
  const n = waiting(items);
  return n ? `${n} waiting` : `${items.length} open`;
}
