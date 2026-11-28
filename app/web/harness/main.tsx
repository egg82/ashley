// The bench screen with no server behind it, for looking at the canvas: `fetch` answers the bench routes from a fixture
// (`fixtures.ts`) and applies a person's moves to it, so drags, pins and boxes go through the real client. Query:
// `n` the bench's size (5, 11, 32), `refuse=1` refuses every move, `add=<ms>` has her add a piece after that long.
// Built by `node harness/build.mjs <outdir>`, never into the app's bundle.
import { render } from 'preact';
import { LocationProvider } from 'preact-iso';
import type { BenchDetail, BenchPiece, CommandRequest } from '../src/api/types';
import { refresh } from '../src/rooms/workshop/model/bench';
import { BenchView } from '../src/rooms/workshop/bench/BenchView';
import '../src/shell/motion';
import '../src/styles/fonts';
import '../src/styles/tokens.css';
import '../src/shell/shell.css';
import '../src/rooms/rooms.css';
import '../src/rooms/her/chat.css';
import '../src/rooms/workshop/workshop.css';
import '../src/rooms/workshop/canvas/canvas.css';
import { benchOf, KINDS, talkOf } from './fixtures';

const q = new URLSearchParams(location.search);
const n = Number(q.get('n') ?? 11);
let bench: BenchDetail = benchOf(n);
const talk = talkOf(n);
let seq = 1000;

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

function moved(c: Extract<CommandRequest, { type: 'move' }>): BenchDetail {
  const pieces = bench.pieces.map((p): BenchPiece => {
    if (p.id !== c.piece_id) return p;
    const pl = c.placement;
    return { ...p, placement: { ...p.placement, ...(pl.pin !== undefined && { pin: pl.pin }), ...(pl.box !== undefined && { box: pl.box }) } };
  });
  return { ...bench, pieces };
}

async function answer(url: string, init?: RequestInit): Promise<Response> {
  if (url === '/api/workshop/kinds') return json(KINDS);
  if (url === '/api/benches/1') return json(bench);
  if (url === '/api/benches/1/conversation') return json(talk);
  if (url.startsWith('/api/benches/1/conversations')) return json({ conversations: [], next: null });
  if (url === '/api/benches/1/commands' && init?.body) {
    const c = JSON.parse(String(init.body)) as CommandRequest;
    await new Promise((r) => setTimeout(r, 300));
    if (q.get('refuse')) return json({ reason: 'bad_place' }, 409);
    if (c.type === 'move') bench = moved(c);
    (window as unknown as { moves: unknown[] }).moves.push(c);
    return json({ piece_id: 'piece_id' in c ? c.piece_id : null, seq: ++seq });
  }
  return json({ detail: 'not in the harness' }, 404);
}

(window as unknown as { moves: unknown[] }).moves = [];
window.fetch = (input: RequestInfo | URL, init?: RequestInit) => answer(typeof input === 'string' ? input : input instanceof URL ? input.pathname : input.url, init);

const addAfter = Number(q.get('add') ?? 0);
if (addAfter) {
  setTimeout(() => {
    const id = Math.max(...bench.pieces.map((p) => p.id)) + 1;
    const p = { ...bench.pieces[0]!, id, kind: 'note', title: 'Overflow tray', body: 'A tray under each box, 2 cm deep.', changed_by: id, changed_at: new Date().toISOString(), changed_author: 'ashley' as const, placement: { order: bench.pieces.length, size: 'medium' as const, pin: null, box: null } };
    bench = { ...bench, pieces: [...bench.pieces, p], links: [...bench.links, { from_id: id, kind: 'part_of', to_id: 2 }] };
    void refresh();
  }, addAfter);
}

render(
  <LocationProvider>
    <div class="ws"><BenchView id={1} /></div>
  </LocationProvider>,
  document.getElementById('app')!,
);
