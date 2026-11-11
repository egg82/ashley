// The household's people as last read, who decides who is an admin, and what the last grant or revoke came to.
import { signal } from '@preact/signals';
import { type AdminRefused, getPeople, putAdmin } from '../../api/people';
import type { PeopleResponse, Person } from '../../api/types';
import { person as me } from '../../session/session';

export type PeopleLoad = 'loading' | 'ready' | 'failed';

export const people = signal<Person[]>([]);
export const adminsFrom = signal<PeopleResponse['admins_from']>('app');
export const peopleState = signal<PeopleLoad>('loading');
/** What the last grant or revoke came to; null when there is nothing to say. */
export const peopleSaid = signal<AdminRefused | 'failed' | null>(null);

export async function loadPeople(): Promise<void> {
  peopleState.value = 'loading';
  try {
    const found = await getPeople();
    people.value = found.people;
    adminsFrom.value = found.admins_from;
    peopleState.value = 'ready';
  } catch {
    peopleState.value = 'failed';
  }
}

/** Whether the signed-in person may grant and revoke here: an admin, while the app decides. */
export function mayGrant(): boolean {
  return Boolean(me.value?.admin) && adminsFrom.value === 'app';
}

/** Grants or revokes admin for `id`; the session's own person follows when it is them. */
export async function setAdmin(id: number, admin: boolean): Promise<void> {
  peopleSaid.value = null;
  try {
    const got = await putAdmin(id, admin);
    if (typeof got === 'string') peopleSaid.value = got;
    else if (me.value?.id === got.id) me.value = { ...me.value, admin: got.admin };
  } catch {
    peopleSaid.value = 'failed';
  }
  await loadPeople();
}
