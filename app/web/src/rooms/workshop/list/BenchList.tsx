// The benches, at `/workshop`: what we're working on, the most recently opened first, each a bench plate that opens
// it, a box to open a new one by asking Ashley for what we want to work on, and the closed benches, folded away, each
// to look at or reopen.
import { useLocation } from 'preact-iso';
import { useEffect, useRef, useState } from 'preact/hooks';
import type { BenchSummary } from '../../../api/types';
import { day, moment } from '../../memory/facts';
import { pickCard } from '../bench/plate';
import { benches, closedBenches, listState, loadBenches, loadClosed, open, reopen } from '../model/benches';

const ASK_MAX = 4000;

function OpenForm() {
  const [ask, setAsk] = useState('');
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const { route } = useLocation();
  const text = ask.trim();
  const submit = async () => {
    if (busy || !text) return;
    setBusy(true);
    setFailed(false);
    const bench = await open(text);
    setBusy(false);
    if (bench) route(`/workshop/${bench.id}?view=talk`);
    else setFailed(true);
  };
  // Enter sends and Shift+Enter breaks the line, as in the chat.
  const key = (e: KeyboardEvent) => {
    if (e.key !== 'Enter' || e.shiftKey || e.isComposing) return;
    e.preventDefault();
    void submit();
  };
  return (
    <form class="ws-open" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
      <textarea value={ask} rows={2} maxLength={ASK_MAX} placeholder="What do you want to work on?"
        aria-label="What do you want to work on?" onInput={(e) => setAsk(e.currentTarget.value)} onKeyDown={key} />
      <button class="btn primary" type="submit" disabled={busy || !text}>Ask Ashley</button>
      {failed && <span class="pedit-err" role="alert">Didn't open. Try again.</span>}
    </form>
  );
}

function countOf(n: number): string {
  return n === 1 ? '1 piece' : n ? `${n} pieces` : 'no pieces';
}

function Card({ bench }: { bench: BenchSummary }) {
  const card = useRef<HTMLAnchorElement>(null);
  return (
    <a ref={card} class="bench ws-card" href={`/workshop/${bench.id}`} onClick={() => card.current && pickCard(bench.id, card.current)}>
      <svg class="glyph" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
        <path d="M3 10h18M5 10v9M19 10v9M7 6h10" />
      </svg>
      <b>{bench.title}</b>
      <span class="meta">{countOf(bench.piece_count)} · {bench.last_changed_at ? `changed ${moment(bench.last_changed_at)}` : `opened ${day(bench.opened_at)}`}</span>
    </a>
  );
}

function Shelf() {
  const state = listState.value;
  if (state === 'loading') return <p class="meta">Reading…</p>;
  if (state !== 'ready') {
    return (
      <div class="panel mem-down" role="alert">
        <div class="mem-down-says">
          <b>{state === 'unreachable' ? "Can't reach Ashley right now." : "Your benches didn't load."}</b>
          <button class="btn" type="button" onClick={() => void loadBenches()}>Try again</button>
        </div>
      </div>
    );
  }
  if (!benches.value.length) return <p class="ws-empty">Nothing we're working on yet. Say what you want to work on above and Ashley opens a bench for it.</p>;
  return <div class="ws-shelf">{benches.value.map((b) => <Card key={b.id} bench={b} />)}</div>;
}

function ClosedRow({ bench }: { bench: BenchSummary }) {
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    setFailed(!(await reopen(bench.id)));
    setBusy(false);
  };
  return (
    <li class="ws-closed-row">
      <a href={`/workshop/${bench.id}`}><b>{bench.title}</b></a>
      <span class="meta">{countOf(bench.piece_count)} · closed {day(bench.closed_at!)}</span>
      {failed && <span class="meta" role="alert">Didn't reopen. Try again.</span>}
      <button class="btn sm" type="button" disabled={busy} onClick={() => void go()}>Reopen</button>
    </li>
  );
}

function Closed() {
  const closed = closedBenches.value;
  if (!closed?.length) return null;
  return (
    <details class="ws-closed">
      <summary><b>Closed benches</b><span class="pill">{closed.length}</span></summary>
      <ul>{closed.map((b) => <ClosedRow key={b.id} bench={b} />)}</ul>
    </details>
  );
}

export function BenchList() {
  useEffect(() => {
    void loadBenches(benches.value.length > 0);
    void loadClosed();
  }, []);
  return (
    <div class="ws-list">
      <div class="mem-head">
        <h1>Workshop</h1>
        <span class="ws-dock" data-dock />
      </div>
      <OpenForm />
      <div class="sec-title"><b>What we're working on</b></div>
      <Shelf />
      <Closed />
    </div>
  );
}
