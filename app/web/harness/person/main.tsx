// The person card with no server behind it, in a column: `fetch` answers the memory routes from `fixtures.ts` and a
// correction or a forget changes what the next read says. Query: `facts` ok (default), empty or fail; `voice` ok
// (default), empty or fail; `w` the column's width in px. Built by `node harness/person/build.mjs <outdir>`, never into
// the app's bundle.
import { render } from 'preact';
import { Person } from '../../src/components/parts/Person';
import { personSource } from '../../src/session/person';
import '../../src/shell/motion';
import '../../src/styles/fonts';
import '../../src/styles/tokens.css';
import '../../src/shell/shell.css';
import '../../src/rooms/rooms.css';
import '../../src/rooms/memory/memory.css';
import '../../src/components/parts/person.css';
import { FACTS, PRINTS } from './fixtures';

const q = new URLSearchParams(location.search);
let facts = [...FACTS];
let prints = [...PRINTS];

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
const later = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function answer(path: string, init?: RequestInit): Promise<Response> {
  await later(120);
  const method = init?.method ?? 'GET';
  const one = /^\/api\/memory\/facts\/(\d+)$/.exec(path);
  if (one && method === 'DELETE') {
    facts = facts.filter((f) => f.id !== Number(one[1]));
    return json({ id: Number(one[1]) });
  }
  if (path === '/api/memory/facts') {
    const how = q.get('facts') ?? 'ok';
    return how === 'fail' ? json({ code: 'unavailable' }, 503) : json({ items: how === 'empty' ? [] : facts });
  }
  if (path === '/api/memory/voice' && method === 'DELETE') {
    prints = [];
    return json({ forgotten: true });
  }
  if (path === '/api/memory/voice') {
    const how = q.get('voice') ?? 'ok';
    return how === 'fail' ? json({ code: 'unavailable' }, 503) : json({ prints: how === 'empty' ? [] : prints });
  }
  return json({ detail: 'not in the harness' }, 404);
}

window.fetch = (input: RequestInfo | URL, init?: RequestInit) =>
  answer(typeof input === 'string' ? input : input instanceof URL ? input.pathname : new URL(input.url).pathname, init);

render(
  <div style={{ width: `${q.get('w') ?? '420'}px`, maxWidth: '100%', padding: '16px', margin: '0 auto' }}>
    <Person source={personSource} />
  </div>,
  document.getElementById('app')!,
);
