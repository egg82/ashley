// Her room as the Desk with no server behind it, for looking at the columns: `fetch` answers the routes it reads from
// `fixtures.ts`, and the board's and the house's actions go through the real client. Query: `att` needs (default), zero
// or unknown for the glance; `controls=fail`, `work=fail` and `printers=fail` fail those reads; `undo` undone (default), waiting_on_you or
// gone for what an Undo answers; `click` selectors, `|`-separated, to click in turn once it has read. Built by
// `node harness/desk/build.mjs <outdir>`, never into the app's bundle.
import { render } from 'preact';
import { LocationProvider } from 'preact-iso';
import { HerRoom } from '../../src/rooms/her/HerRoom';
import { Account } from '../../src/shell/topbar/Account';
import { person } from '../../src/session/session';
import '../../src/shell/motion';
import '../../src/styles/fonts';
import '../../src/styles/tokens.css';
import '../../src/shell/shell.css';
import '../../src/rooms/rooms.css';
import '../../src/rooms/her/chat.css';
import '../../src/rooms/her/desk.css';
import '../../src/kiosk/kiosk.css';
import '../../src/rooms/memory/memory.css';
import '../../src/components/parts/person.css';
import { FACTS, PRINTS } from '../person/fixtures';
import { CONTROLS, CONVERSATION, CONVERSATION_ID, glanceOf, PRINTERS, WORK } from './fixtures';

const q = new URLSearchParams(location.search);
let work = WORK;

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
const later = (ms: number) => new Promise((r) => setTimeout(r, ms));

function act(path: string, method: string): Response | null {
  const watch = /^\/api\/work\/watches\/(\d+)$/.exec(path);
  if (watch && method === 'DELETE') {
    work = work.filter((i) => !(i.kind === 'watch' && i.id === Number(watch[1])));
    return json({ id: Number(watch[1]) });
  }
  const undo = /^\/api\/work\/actions\/(\d+)\/undo$/.exec(path);
  if (undo && method === 'POST') {
    const how = (q.get('undo') ?? 'undone') as 'undone' | 'waiting_on_you' | 'gone';
    work = work.map((i) => (i.kind === 'action' && i.id === Number(undo[1]) ? { ...i, can_undo: false, undone: { at: new Date().toISOString(), how } } : i));
    return json({ id: Number(undo[1]), how, conversation_id: how === 'waiting_on_you' ? CONVERSATION_ID : null });
  }
  if (path === '/api/chat/agree' && method === 'POST') return json({ detail: 'gone' }, 409);
  return null;
}

async function answer(path: string, init?: RequestInit): Promise<Response> {
  await later(150);
  const method = init?.method ?? 'GET';
  const done = act(path, method);
  if (done) return done;
  if (path === '/api/chat/conversation') return json(CONVERSATION);
  if (path.startsWith('/api/chat/conversations')) return json({ conversations: [], next: null });
  if (path === '/api/work') return q.get('work') === 'fail' ? json({ code: 'unavailable' }, 503) : json({ entries: work });
  if (path === '/api/memory/facts') return json({ items: FACTS });
  if (path === '/api/memory/voice') return json({ prints: PRINTS });
  if (path === '/api/house/glance') return json(glanceOf(q.get('att') ?? 'needs'));
  if (path === '/api/house/controls') return q.get('controls') === 'fail' ? json({ code: 'unavailable' }, 503) : json({ controls: CONTROLS });
  if (path === '/api/house/printers') return q.get('printers') === 'fail' ? json({ code: 'unavailable' }, 503) : json({ printers: PRINTERS });
  if (path.startsWith('/api/house/controls/') && method === 'POST') return json({ done: !path.endsWith('all-off') });
  return json({ detail: 'not in the harness' }, 404);
}

window.fetch = (input: RequestInfo | URL, init?: RequestInit) =>
  answer(typeof input === 'string' ? input : input instanceof URL ? input.pathname : new URL(input.url).pathname, init);

person.value = { id: 1, name: 'Maya', household_id: 1, admin: false };

(q.get('click')?.split('|') ?? []).forEach((selector, i) => setTimeout(() => document.querySelector<HTMLElement>(selector)?.click(), 900 + i * 400));

render(
  <LocationProvider>
    <div id="field" />
    <header class="topbar"><div class="spacer" /><Account person={person.value!} /></header>
    <section class="room on" data-room="her" aria-label="Ashley"><HerRoom /></section>
  </LocationProvider>,
  document.getElementById('app')!,
);
