// The "what she may just do" panel with no server behind it: `fetch` answers /api/trust from a fixture and applies a
// save to it. Query: `read=fail` fails the read, `put` is ok (default), `slow` (a save that stays pending), `fail` (a
// save that fails) or `stale` (a 409, after which the fixture has changed); `click` a selector to click once it has
// read. Built by `node harness/trust/build.mjs <outdir>`, never into the app's bundle.
import { render } from 'preact';
import type { TrustSettings } from '../../src/api/types';
import { TrustPanel } from '../../src/rooms/household/TrustPanel';
import '../../src/shell/motion';
import '../../src/styles/fonts';
import '../../src/styles/tokens.css';
import '../../src/shell/shell.css';
import '../../src/rooms/rooms.css';
import '../../src/rooms/devices/devices.css';
import '../../src/rooms/connections/connections.css';
import '../../src/rooms/household/household.css';
import '../../src/rooms/household/household-side.css';

const q = new URLSearchParams(location.search);
const row = (kind: string, label: string, value: 'act' | 'offer', locked: 'asks' | 'irreversible' | null = null) => ({ kind, label, value, locked });
let settings: TrustSettings = {
  revision: 3,
  updated_at: '2026-11-26T18:00:00Z',
  rows: [
    row('house_removals', "Delete or remove things from the house's setup", 'offer', 'irreversible'),
    row('house_setup', 'Change how the house is set up', 'offer'),
    row('reminders', 'Set, change or cancel reminders', 'act'),
    row('lists', 'Edit to-do lists', 'act'),
    row('messages', 'Send email', 'offer'),
    row('money', 'Categorise or note transactions', 'offer', 'asks'),
  ],
};

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
const later = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function answer(path: string, init?: RequestInit): Promise<Response> {
  await later(150);
  if (path !== '/api/trust') return json({ detail: 'not in the harness' }, 404);
  if (!init?.method || init.method === 'GET') return q.get('read') === 'fail' ? json({ code: 'unavailable' }, 503) : json(settings);
  const how = q.get('put') ?? 'ok';
  if (how === 'slow') await later(60_000);
  if (how === 'fail') return json({ code: 'unavailable' }, 503);
  if (how === 'stale') {
    settings = { ...settings, revision: settings.revision + 1, rows: settings.rows.map((r) => (r.kind === 'lists' ? { ...r, value: 'offer' } : r)) };
    q.set('put', 'ok');
    return json({ code: 'version_conflict' }, 409);
  }
  const picks = (JSON.parse(String(init.body)) as { picks: { kind: string; value: 'act' | 'offer' }[] }).picks;
  settings = { ...settings, revision: settings.revision + 1, rows: settings.rows.map((r) => ({ ...r, value: picks.find((p) => p.kind === r.kind)?.value ?? r.value })) };
  return json(settings);
}

window.fetch = (input: RequestInfo | URL, init?: RequestInit) =>
  answer(typeof input === 'string' ? input : input instanceof URL ? input.pathname : new URL(input.url).pathname, init);

const click = q.get('click');
if (click) setTimeout(() => document.querySelector<HTMLElement>(click)?.click(), 600);

render(<div class="set hh" style="max-width:520px;margin:0 auto"><TrustPanel /></div>, document.getElementById('app')!);
