// The settings page's state: one connection's settings as read, the draft being edited, and what its service offers for
// a setting to pick from. Every change goes through here.
import { signal } from '@preact/signals';
import { ApiError } from '../../../api/client';
import { getCatalogue, getSettings, putSettings } from '../../../api/connectionSettings';
import type { ConnectionCatalogue, ConnectionSettings } from '../../../api/types';
import { draftOf, entriesOf, same, type Draft } from './draft';

/** `missing`: no such connection, or one with no settings. */
export type SettingsLoad = 'loading' | 'ready' | 'missing' | 'failed';
export type SettingsSaid = 'saved' | 'conflict' | 'refused' | 'failed' | null;
/** What the service has: not read yet, read at `read_at`, or not answering. */
export type Offer = { state: 'loading' } | { state: 'unavailable' } | { state: 'ready'; catalogue: ConnectionCatalogue };

export const settings = signal<ConnectionSettings | null>(null);
export const loaded = signal<SettingsLoad>('loading');
export const draft = signal<Draft>({});
export const saving = signal(false);
export const said = signal<SettingsSaid>(null);
export const house = signal<Offer>({ state: 'loading' });

export function dirty(): boolean {
  const read = settings.value;
  return read !== null && !same(draft.value, draftOf(read.values));
}

function take(read: ConnectionSettings): void {
  settings.value = read;
  draft.value = draftOf(read.values);
}

export async function loadSettings(id: number): Promise<void> {
  loaded.value = 'loading';
  said.value = null;
  try {
    take(await getSettings(id));
    loaded.value = 'ready';
  } catch (error) {
    loaded.value = error instanceof ApiError && error.status === 404 ? 'missing' : 'failed';
  }
}

export function edit(next: Draft): void {
  draft.value = next;
  said.value = null;
}

export function discard(): void {
  if (settings.value) take(settings.value);
  said.value = null;
}

export async function save(id: number): Promise<void> {
  const read = settings.value;
  if (!read || saving.value) return;
  saving.value = true;
  said.value = null;
  try {
    const got = await putSettings(id, { revision: read.revision, values: entriesOf(draft.value) });
    if ('reason' in got) {
      said.value = 'refused';
    } else {
      take(got);
      said.value = 'saved';
    }
  } catch (error) {
    said.value = error instanceof ApiError && error.status === 409 ? 'conflict' : 'failed';
  } finally {
    saving.value = false;
  }
}

/** Reads what the connection's service has now: everything it lists, once per opening of the page. */
export async function loadHouse(id: number): Promise<void> {
  house.value = { state: 'loading' };
  try {
    house.value = { state: 'ready', catalogue: await getCatalogue(id, []) };
  } catch {
    house.value = { state: 'unavailable' };
  }
}
