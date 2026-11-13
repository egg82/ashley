// What a connection reaches, one line each (a mailbox): its holder's own get a switch between shared with the household and
// kept; a household's are only named.
import { useId } from 'preact/hooks';
import type { ConnectionResource, HouseholdConnection } from '../../../api/types';
import { share } from '../connections';
import { sharedFor, whoOf } from '../who';
import { holderOf } from './sentence.ts';

function Switch({ c, r }: { c: HouseholdConnection; r: ConnectionResource }) {
  const id = useId();
  return (
    <label class="rr-switch" for={id}>
      <input id={id} type="checkbox" role="switch" checked={whoOf(r.shared) === 'household'} disabled={!c.can_change}
        onChange={(e) => { const to = sharedFor(r.shared, e.currentTarget.checked ? 'household' : 'me'); if (to !== null) void share(c, r.ref, to); }} />
      <span class="meta">{r.shared ? 'Shared with household' : `Kept to ${holderOf(c)}`}</span>
    </label>
  );
}

export function Resources({ c }: { c: HouseholdConnection }) {
  if (c.resources.length === 0) return null;
  return (
    <ul class="rr-boxes">
      {c.resources.map((r) => (
        <li key={r.ref}>
          <span class="rr-box-name">{r.name}</span>
          {c.personal ? <Switch c={c} r={r} /> : null}
        </li>
      ))}
    </ul>
  );
}
