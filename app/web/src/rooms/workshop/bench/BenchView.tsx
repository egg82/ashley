// One bench, at `/workshop/<id>`: its bar, a line for a change that didn't go through, and the floor with its talk
// beside its pieces and their shelf (on a phone one or the other, `?view=talk`). Opened from the benches, the plate grows out of the
// card that was picked (`plate.ts`).
import { useLocation } from 'preact-iso';
import { useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks';
import { benchState, detail, enterBench, leaveBench, loadBench, notice } from '../model/bench';
import { loadRules, rules } from '../model/benches';
import { enterTalk, leaveTalk } from '../model/talk';
import { clearMarks } from '../pieces/marks';
import { PieceGrid } from '../pieces/PieceGrid';
import { DropFiles } from './Upload';
import { whyNot } from '../pieces/why';
import { Away } from './Away';
import { BenchBar, type View } from './BenchBar';
import { BenchTalk } from './BenchTalk';
import { Method } from './Method';
import { growFromCard } from './plate';
import { Shelf } from './Shelf';

function Down() {
  const state = benchState.value;
  if (state === 'loading') return <p class="chat-quiet meta">Reading…</p>;
  if (state === 'missing') {
    return (
      <div class="panel mem-down ws-down">
        <div class="mem-down-says"><b>No bench of yours here.</b><a class="btn" href="/workshop">Your benches</a></div>
      </div>
    );
  }
  return (
    <div class="panel mem-down ws-down" role="alert">
      <div class="mem-down-says">
        <b>{state === 'unreachable' ? "Can't reach Ashley right now." : "This bench didn't load."}</b>
        <button class="btn" type="button" onClick={() => void loadBench()}>Try again</button>
      </div>
    </div>
  );
}

function useBench(id: number): void {
  useEffect(() => {
    enterBench(id);
    void loadRules();
    return () => {
      leaveBench();
      leaveTalk();
      clearMarks();
    };
  }, [id]);
  const thread = detail.value?.bench.id === id ? detail.value.bench.thread : null;
  useEffect(() => {
    if (thread) enterTalk(id, thread);
  }, [id, thread]);
}

export function BenchView({ id }: { id: number }) {
  useBench(id);
  const { query, path, route } = useLocation();
  const view: View = query.view === 'talk' ? 'talk' : 'pieces';
  const setView = (v: View) => route(v === 'talk' ? `${path}?view=talk` : path, true);
  const [adding, setAdding] = useState(false);
  const plate = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => growFromCard(plate.current, id), [id]);
  const bench = detail.value?.bench.id === id ? detail.value : null;
  const said = notice.value;
  return (
    <div class="bench wb" ref={plate}>
      {!bench || benchState.value === 'missing' ? <Down /> : (
        <>
          <BenchBar bench={bench} rules={rules.value} view={view} setView={setView} add={() => { setAdding(true); setView('pieces'); }} />
          <div class="ws-sub">
            <Method bench={bench} rules={rules.value} />
            {said && !said.ok && said.why !== 'stale_base' && <p class="ws-notice" role="status">{whyNot(said.why)}</p>}
          </div>
          <div class="floor" data-view={view}>
            <section class="col talk" aria-label="Talk"><BenchTalk thread={bench.bench.thread} closed={bench.bench.closed_at !== null} /></section>
            <DropFiles bench={id} enabled={bench.bench.closed_at === null}>
              <PieceGrid bench={bench} rules={rules.value} adding={adding} doneAdding={() => setAdding(false)} />
              <Shelf bench={bench} rules={rules.value} />
            </DropFiles>
            <Away bench={bench} showPieces={() => setView('pieces')} />
          </div>
        </>
      )}
    </div>
  );
}
