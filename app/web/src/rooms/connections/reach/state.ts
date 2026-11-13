// What the room has open: the connection whose row is opened (kept in the address as `#open-<id>`, so a reload or a shared
// link lands on it), the one being removed, and the one whose spoke is being cut on the map.
import { signal } from '@preact/signals';
import type { HouseholdConnection } from '../../../api/types';
import { pause } from '../../../shell/motion';
import { disconnect } from '../connections';

const CUT_MS = 650;
const HASH = /^#open-(\d+)$/;

function fromAddress(): number | null {
  const m = HASH.exec(location.hash);
  return m ? Number(m[1]) : null;
}

export const opened = signal<number | null>(fromAddress());
export const removing = signal<number | null>(null);
export const cutting = signal<number | null>(null);

function show(id: number | null): void {
  history.replaceState(history.state, '', id === null ? location.pathname + location.search : `${location.pathname}${location.search}#open-${id}`);
}

export function toggleRow(id: number): void {
  const next = opened.value === id ? null : id;
  opened.value = next;
  removing.value = null;
  show(next);
}

export function openRow(id: number): void {
  opened.value = id;
  show(id);
  document.getElementById(`c${id}`)?.scrollIntoView({ block: 'center' });
}

export function startRemoving(id: number): void {
  removing.value = id;
}

export function stopRemoving(): void {
  removing.value = null;
}

/** Cuts its spoke on the map, then removes it: the room settles once the server has answered. */
export async function removeConnection(c: HouseholdConnection): Promise<void> {
  cutting.value = c.id;
  await pause(CUT_MS);
  await disconnect(c);
  cutting.value = null;
  removing.value = null;
  if (opened.value === c.id) {
    opened.value = null;
    show(null);
  }
}
