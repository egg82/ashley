// The bench's bar: back to the benches, its title, the two of you (her mark docks here), and its own actions: undo the
// last change (saying what and whose), add a piece, and the ⋯ menu (`BenchMenu.tsx`); a closed one reopens.
import { useLayoutEffect, useState } from 'preact/hooks';
import type { BenchDetail, LoggedCommand, WorkshopKinds } from '../../../api/types';
import { person } from '../../../session/session';
import { redock } from '../../../shell/her/dock';
import { day } from '../../memory/facts';
import { apply, refresh } from '../model/bench';
import { reopen } from '../model/benches';
import { undoTarget } from '../model/log';
import { herAt } from '../pieces/marks';
import { BenchMenu } from './BenchMenu';

const DID: Record<LoggedCommand['type'], string> = { add: 'add', edit: 'edit', move: 'move', remove: 'remove', run: 'run', propose: 'proposal', install: 'install', archive: 'archive', restore: 'restore', undo: 'undo', rename: 'rename', cue: 'cue', point: 'point', surfaced: 'choices shown', link: 'link', unlink: 'unlink' };

function Undo({ bench }: { bench: BenchDetail }) {
  const target = undoTarget(bench);
  const did = target?.command;
  return (
    <button class="btn sm" type="button" disabled={!target} onClick={() => target && void apply({ type: 'undo', seq: target.seq })}>
      ↶ Undo
      {did && <span class="meta">{DID[did.type]} · {did.author === 'ashley' ? 'hers' : 'yours'}</span>}
    </button>
  );
}

function Reopen({ id }: { id: number }) {
  const [failed, setFailed] = useState(false);
  const go = async () => {
    setFailed(false);
    if (await reopen(id)) await refresh();
    else setFailed(true);
  };
  return (
    <>
      {failed && <span class="meta" role="alert">Didn't reopen. Try again.</span>}
      <button class="btn sm primary" type="button" onClick={() => void go()}>Reopen</button>
    </>
  );
}

interface Props {
  bench: BenchDetail;
  rules: WorkshopKinds | null;
  add: () => void;
}

export function BenchBar({ bench, rules, add }: Props) {
  const b = bench.bench;
  const closed = b.closed_at !== null;
  const full = rules !== null && bench.pieces.length >= rules.max_pieces;
  const name = person.value?.name ?? '';
  // The bar is laid out once the bench has been read, after the room was entered: her mark comes to its dock then.
  useLayoutEffect(() => redock(false), []);
  return (
    <div class="bar">
      <a class="btn sm ghost ws-back" href="/workshop" aria-label="Benches">‹ Benches</a>
      <h1>{b.title}</h1>
      <span class="people">
        <span class="who you" aria-label={name}>{name.slice(0, 1)}</span>
        {herAt.value === null && <span class="bar-dock" data-dock />}
      </span>
      {closed && <span class="pill">closed {day(b.closed_at!)}</span>}
      <span class="ws-acts">
        {closed && <Reopen id={b.id} />}
        {!closed && <Undo bench={bench} />}
        {!closed && (
          <button class="btn sm ghost" type="button" disabled={!rules || full} onClick={add}>
            {full ? 'Bench full' : '＋ Add'}
          </button>
        )}
        <BenchMenu bench={bench} rules={rules} full={full} />
      </span>
    </div>
  );
}
