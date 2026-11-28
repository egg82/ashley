// The page `bench_look` photographs, with no server behind it: `fetch` answers the look route from the bench fixture
// (`../fixtures.ts`). Query: `n` the bench's size (5, 11, 32), `piece` one piece's id for a look at that piece alone.
// Built by `node harness/look/build.mjs <outdir>`, never into the app's bundle.
import { render } from 'preact';
import { LookPage } from '../../src/rooms/workshop/look/LookPage';
import '../../src/shell/motion';
import '../../src/styles/fonts';
import '../../src/styles/tokens.css';
import '../../src/shell/shell.css';
import '../../src/rooms/rooms.css';
import '../../src/rooms/her/chat.css';
import '../../src/rooms/workshop/workshop.css';
import '../../src/rooms/workshop/canvas/canvas.css';
import { benchOf, KINDS } from '../fixtures';

const q = new URLSearchParams(location.search);
const whole = benchOf(Number(q.get('n') ?? 11));
const only = Number(q.get('piece') ?? 0);
const view = only ? { ...whole, pieces: whole.pieces.filter((p) => p.id === only), links: [], shelf: [], recent: [] } : whole;

window.fetch = () => Promise.resolve(new Response(JSON.stringify({ view, rules: KINDS }), { status: 200, headers: { 'content-type': 'application/json' } }));

render(<LookPage token="harness" />, document.getElementById('app')!);
