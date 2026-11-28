// The bench's stage log, a drawer beside the floor: its recent changes newest first, her turns each as one step, and each
// change's way back, the bench's own Undo command (`undoTarget` marks the one the bar's Undo takes next).
import { signal } from '@preact/signals';
import type { BenchDetail, LoggedCommand } from '../../../api/types';
import { moment } from '../../memory/facts';
import { apply, undoWholeTurn } from '../model/bench';
import { DID, stepsOf, turnUndo, undoTarget, type Step } from '../model/log';

export const logOpen = signal(false);

function Row({ c, title, next }: { c: LoggedCommand; title: string | undefined; next: boolean }) {
  return (
    <li class="wlog-row" data-next={next} data-undone={c.undone_by !== null}>
      <span><b>{DID[c.type]}</b> {title ?? (c.piece_id === null ? '' : `piece ${c.piece_id}`)}</span>
      <span class="meta">{moment(c.at)}</span>
      {c.undone_by === null
        ? <button class="btn sm ghost" type="button" onClick={() => void apply({ type: 'undo', seq: c.seq })}>Undo</button>
        : <span class="meta">undone</span>}
    </li>
  );
}

function TurnUndo({ step }: { step: Step }) {
  const turn = turnUndo(step);
  if (!turn) return null;
  return (
    <button class="btn sm ghost" type="button" disabled={turn.off !== null} title={turn.off ?? 'Take back every change of this turn'}
      onClick={() => void undoWholeTurn(turn.seq)}>{turn.off ?? 'Undo this turn'}</button>
  );
}

export function StageLog({ bench }: { bench: BenchDetail }) {
  if (!logOpen.value || bench.bench.closed_at !== null) return null;
  const titles = new Map([...bench.pieces, ...bench.shelf].map((p) => [p.id, p.title]));
  const steps = stepsOf(bench.recent);
  const next = undoTarget(bench)?.seq;
  return (
    <aside class="wlog" aria-label="Changes">
      <h2>Changes</h2>
      {steps.length === 0 && <p class="meta">Nothing has changed yet.</p>}
      {steps.map((s) => (
        <section key={s.rows[0]!.seq} class="wlog-step">
          <h3 class={s.rows[0]!.author === 'ashley' ? 'her-meta' : 'meta'}>
            {s.rows[0]!.author === 'ashley' ? 'Ashley' : 'You'}{s.turn !== null && ` · ${s.rows.length} ${s.rows.length === 1 ? 'change' : 'changes'} in one turn`}
            <TurnUndo step={s} />
          </h3>
          <ul>{s.rows.map((c) => <Row key={c.seq} c={c} title={c.piece_id === null ? undefined : titles.get(c.piece_id)} next={c.seq === next} />)}</ul>
        </section>
      ))}
    </aside>
  );
}
