// Removing: the kind's own words for what it costs, and the connection's name typed to confirm. While it is open the rest of
// the room dims.
import { useEffect, useRef, useState } from 'preact/hooks';
import type { ConnectionKindInfo, HouseholdConnection } from '../../../api/types';
import { bringBack, confirmsRemoval, costOf } from './remove.ts';
import { removeConnection, stopRemoving } from './state';

export function RemoveConfirm({ c, kind }: { c: HouseholdConnection; kind: ConnectionKindInfo }) {
  const name = c.label || kind.title;
  const [typed, setTyped] = useState('');
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => field.current?.focus(), []);
  const ok = confirmsRemoval(typed, name);
  return (
    <form class="rr-remove" onSubmit={(e) => { e.preventDefault(); if (ok) void removeConnection(c); }}>
      <h3>Remove {name}?</h3>
      <p>{costOf(kind)} Anything she was doing with it stops. To bring it back, {bringBack(kind)}.</p>
      <label>
        <span class="meta">Type <b>{name}</b> to confirm</span>
        <input ref={field} value={typed} autocomplete="off" onInput={(e) => setTyped(e.currentTarget.value)} />
      </label>
      <div class="dc-act">
        <button class="btn danger" type="submit" disabled={!ok}>Remove {name}</button>
        <button class="btn sm" type="button" onClick={stopRemoving}>Keep it</button>
      </div>
    </form>
  );
}
