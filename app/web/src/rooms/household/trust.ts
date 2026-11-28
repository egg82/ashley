// The signed-in person's trust choices as last read, and what the last save came to. Unread stays unknown: there is no
// default row to show in its place.
import { signal } from '@preact/signals';
import { ApiError } from '../../api/client';
import { getTrust, putTrust } from '../../api/trust';
import type { TrustRow, TrustSettings } from '../../api/types';
import { picksWith } from './trustChoices';

export type TrustLoad = 'loading' | 'ready' | 'failed';
export type TrustSaid = 'saved' | 'failed' | 'changed' | 'refused';

export const trust = signal<TrustSettings | null>(null);
export const trustState = signal<TrustLoad>('loading');
/** The kind being saved, null when none is. */
export const trustSaving = signal<string | null>(null);
export const trustSaid = signal<TrustSaid | null>(null);

export async function loadTrust(): Promise<void> {
  trustState.value = 'loading';
  try {
    trust.value = await getTrust();
    trustState.value = 'ready';
  } catch {
    trust.value = null;
    trustState.value = 'failed';
  }
}

/** Saves one kind's choice; the others keep what was read. A stale revision reloads and says so. */
export async function setTrust(kind: string, value: TrustRow['value']): Promise<void> {
  const now = trust.value;
  if (!now || trustSaving.value) return;
  trustSaving.value = kind;
  trustSaid.value = null;
  try {
    trust.value = await putTrust(now.revision, picksWith(now.rows, kind, value));
    trustSaid.value = 'saved';
  } catch (e) {
    const status = e instanceof ApiError ? e.status : 0;
    trustSaid.value = status === 409 ? 'changed' : status === 422 ? 'refused' : 'failed';
    if (status === 409) await loadTrust();
  } finally {
    trustSaving.value = null;
  }
}
