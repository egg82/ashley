// The bench's bar: back to the benches, its title, the two of you (her mark docks here), Talk and Pieces on a phone,
// and its own actions: undo the last change (saying what and whose), add a piece, close the bench; a closed one reopens.
import { useLocation } from 'preact-iso';
import { useLayoutEffect, useState } from 'preact/hooks';
import type { BenchDetail, LoggedCommand, WorkshopKinds } from '../../../api/types';
import { person } from '../../../session/session';
import { redock } from '../../../shell/her/dock';
import { day } from '../../memory/facts';
import { apply, refresh } from '../model/bench';
import { close, reopen } from '../model/benches';
import { undoTarget } from '../model/log';
import { herAt } from '../pieces/marks';
import { UploadButton } from './Upload';

export type View = 'talk' | 'pieces';

const DID: Record<LoggedCommand['type'], string> = { add: 'add', edit: 'edit', move: 'move', remove: 'remove', run: 'run', propose: 'proposal', install: 'install', archive: 'archive', restore: 'restore', undo: 'undo', rename: 'rename', cue: 'cue', point: 'point', surfaced: 'choices shown' };

function Undo({ bench }: { bench: BenchDetail }) {
  const target = undoTarget(bench);
  const did = target?.command;
  return (
    <button class="btn sm" type="button" disabled={!target} onClick={() => target && void apply({ type: 'undo', seq: target.seq })}>
      Undo
      {did && <span class="meta">{DID[did.type]} · {did.author === 'ashley' ? 'hers' : 'yours'}</span>}
    </button>
  );
}

function Close({ id }: { id: number }) {
  const [asking, setAsking] = useState(false);
  const [failed, setFailed] = useState(false);
  const { route } = useLocation();
  if (!asking) return <button class="btn sm ghost" type="button" onClick={() => setAsking(true)}>Close</button>;
  const confirm = async () => {
    if (await close(id)) route('/workshop');
    else setFailed(true);
  };
  return (
    <span class="ws-ask" role="group" aria-label="Close this bench">
      <span class="meta">{failed ? "Didn't close. Try again." : "It's kept, but leaves your benches."}</span>
      <button class="btn sm" type="button" onClick={() => void confirm()}>Close it</button>
      <button class="btn sm ghost" type="button" onClick={() => setAsking(false)}>Keep it open</button>
    </span>
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
    <span class="ws-acts">
      {failed && <span class="meta" role="alert">Didn't reopen. Try again.</span>}
      <button class="btn sm primary" type="button" onClick={() => void go()}>Reopen</button>
    </span>
  );
}

interface Props {
  bench: BenchDetail;
  rules: WorkshopKinds | null;
  view: View;
  setView: (v: View) => void;
  add: () => void;
}

export function BenchBar({ bench, rules, view, setView, add }: Props) {
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
      <div class="seg ws-views" role="group" aria-label="Show">
        <button type="button" aria-pressed={view === 'talk'} onClick={() => setView('talk')}>Talk</button>
        <button type="button" aria-pressed={view === 'pieces'} onClick={() => setView('pieces')}>Pieces</button>
      </div>
      {closed && <Reopen id={b.id} />}
      {!closed && (
        <span class="ws-acts">
          <Undo bench={bench} />
          <UploadButton bench={b.id} disabled={!rules || full} />
          <button class="btn sm primary" type="button" disabled={!rules || full} onClick={add}>
            {full ? 'Bench full' : 'Add a piece'}
          </button>
          <Close id={b.id} />
        </span>
      )}
    </div>
  );
}
