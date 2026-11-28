// The kiosk with no server behind it, for looking at its parts: `fetch` answers the device routes from the fixtures
// below and the live feed is a stub that never speaks. Query: `laid=1` answers a layout she arranged (clock, home,
// controls, conversation), else the fixed page; `click` a selector to click once it has read. Built by
// `node harness/kiosk/build.mjs <outdir>`, never into the app's bundle. It imports only what main's kiosk has, so the same
// file renders an older checkout for comparison.
import { render } from 'preact';
import { Kiosk } from '../../src/kiosk/Kiosk';
import '../../src/styles/fonts';
import '../../src/styles/tokens.css';
import '../../src/rooms/her/chat.css';
import '../../src/kiosk/kiosk.css';
import '../../src/speech/announce.css';
import '../../src/camera/camera.css';

const q = new URLSearchParams(location.search);
const at = (h: number, m = 0) => new Date(Date.UTC(2026, 10, 27, h, m)).toISOString();
const turn = (id: number, author: 'person' | 'ashley', text: string, m: number) =>
  ({ id, author, text, at: at(9, m), follows: false, continued_on: null, attachment: null, runs: [], looks: [], working: false, agree: null, voiced: false, receipts: null, agreed: null, piece_ids: [], brought_up: [] });

const DEVICE = { id: 3, name: 'Hall tablet', place: 'hallway' };
const GLANCE = {
  home: ['Maya', 'Theo'], not_connected: [], locale: 'en-GB', clock: '24h',
  calendar: [{ title: 'Dentist', day: 'today', time: '15:30' }, { title: "Jonah's party", day: 'tomorrow', time: '14:00' }],
};
const CONTROLS = [
  { name: 'living-lights', label: 'Living room', on: true },
  { name: 'porch-light', label: 'Porch', on: false },
  { name: 'movie-night', label: 'Movie night', on: null },
  { name: 'all-off', label: 'Everything off', on: null },
];
const CONVERSATION = { thread: 'device:3', conversation_id: 8, started_at: at(9, 50), turns: [
  turn(1, 'person', 'Is it going to rain Saturday?', 50),
  turn(2, 'ashley', "Dry until about 4. Jonah's party starts at 2, so outside is fine.", 51),
] };
const LAYOUT = { laid_out: true, seq: 4, placed: [
  { id: 1, kind: 'clock', order: 0, size: 'small' }, { id: 2, kind: 'home', order: 1, size: 'medium' },
  { id: 3, kind: 'controls', order: 2, size: 'medium' }, { id: 4, kind: 'conversation', order: 3, size: 'full' },
] };

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

async function answer(path: string, init?: RequestInit): Promise<Response> {
  await new Promise((r) => setTimeout(r, 100));
  if (path === '/api/kiosk/device') return json(DEVICE);
  if (path === '/api/kiosk/glance') return json(GLANCE);
  if (path === '/api/kiosk/conversation') return json(CONVERSATION);
  if (path === '/api/kiosk/layout') return json(q.get('laid') ? LAYOUT : { laid_out: false, seq: 0, placed: [] });
  if (path === '/api/kiosk/controls') return json({ controls: CONTROLS });
  if (path.startsWith('/api/kiosk/controls/') && init?.method === 'POST') return json({ done: !path.endsWith('all-off') });
  if (path === '/api/spoken/limits') return json({ max_ms: 30000 });
  return json({ detail: 'not in the harness' }, 404);
}

window.fetch = (input: RequestInfo | URL, init?: RequestInit) =>
  answer(typeof input === 'string' ? input : input instanceof URL ? input.pathname : new URL(input.url).pathname, init);
class QuietSource extends EventTarget {
  onmessage = null;
  onerror = null;
  onopen = null;
  readyState = 0;
  close() {}
}
(window as unknown as { EventSource: unknown }).EventSource = QuietSource;

const click = q.get('click');
if (click) setTimeout(() => document.querySelector<HTMLElement>(click)?.click(), 900);

render(<Kiosk />, document.getElementById('app')!);
