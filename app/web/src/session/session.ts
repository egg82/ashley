// Who is signed in, and whether she answers. Loaded once on start, again on "Try again", cleared on sign-out.
import { signal } from '@preact/signals';
import { getHealth, getMe, signOut as postSignOut } from '../api/client';
import type { HealthResponse, Person } from '../api/types';

/**
 * - `checking`: the first answers are not back.
 * - `signed-out`: `/api/me` said 401.
 * - `signed-in`: a person, and she answered `/api/health`.
 * - `unreachable`: `/api/me` failed other than 401, or it worked and `/api/health` did not.
 */
export type Status = 'checking' | 'signed-out' | 'signed-in' | 'unreachable';

export const status = signal<Status>('checking');
export const person = signal<Person | null>(null);
/** Her health answer; null until it arrives or when it failed. */
export const health = signal<HealthResponse | null>(null);

export async function load(): Promise<void> {
  status.value = 'checking';
  const [me, h] = await Promise.allSettled([getMe(), getHealth()]);
  health.value = h.status === 'fulfilled' ? h.value : null;
  if (me.status === 'rejected') {
    person.value = null;
    status.value = 'unreachable';
    return;
  }
  person.value = me.value?.person ?? null;
  if (!me.value) status.value = 'signed-out';
  else status.value = health.value ? 'signed-in' : 'unreachable';
}

export async function signOut(): Promise<void> {
  await postSignOut();
  person.value = null;
  status.value = 'signed-out';
}
