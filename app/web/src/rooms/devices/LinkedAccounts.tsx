// The person's accounts elsewhere, read-only; linking and unlinking stay in the Connections room.
import type { LinkedAccount } from '../../api/types';
import { linked } from './devices';

const SYSTEM: Record<string, string> = { oidc: 'Your sign-in', discord: 'Discord', home_assistant: 'Home Assistant' };

function Row({ a }: { a: LinkedAccount }) {
  return (
    <li class="la-row">
      <span>{SYSTEM[a.system] ?? a.system}</span>
      {a.handle ? <b class="la-handle">{a.handle}</b> : <span class="meta">Linked by an admin</span>}
    </li>
  );
}

export function LinkedAccounts() {
  const got = linked.value;
  return (
    <div class="panel">
      <div class="ph"><h3>Linked accounts</h3></div>
      <div class="dc-body">
        {got === null && <p class="meta">Reading your accounts…</p>}
        {got === 'unknown' && <span class="unk">Couldn't check</span>}
        {Array.isArray(got) && got.length === 0 && <p class="meta">No accounts are linked to you yet.</p>}
        {Array.isArray(got) && got.length > 0 && <ul class="la">{got.map((a) => <Row key={a.id} a={a} />)}</ul>}
        <a class="btn sm ghost la-manage" href="/connections">Manage in Connections</a>
      </div>
    </div>
  );
}
