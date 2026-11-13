// The household's devices as last read, whether they could be, and which one the room is looking at.
import { signal } from '@preact/signals';
import { ApiError, getAccounts, getDevices } from '../../api/client';
import type { LinkedAccount, ListedDevice } from '../../api/types';
import { herRoomLeft, roomReached } from '../../shell/her/state';
import { firstSelected } from './plan';

/** `unreachable`: a 503 or no answer at all; `failed`: any other error. */
export type DevicesLoad = 'loading' | 'ready' | 'unreachable' | 'failed';

export const devices = signal<ListedDevice[]>([]);
export const devicesState = signal<DevicesLoad>('loading');
export const selected = signal<number | null>(null);
/** Whether the selected device's panel is its controls editor. */
export const editing = signal(false);

export async function loadDevices(): Promise<void> {
  devicesState.value = 'loading';
  try {
    devices.value = (await getDevices()).devices;
    if (!devices.value.some((d) => d.id === selected.value)) {
      selected.value = firstSelected(devices.value);
      editing.value = false;
    }
    devicesState.value = 'ready';
    roomReached(true);
  } catch (error) {
    const down = !(error instanceof ApiError) || error.status === 503;
    devicesState.value = down ? 'unreachable' : 'failed';
    roomReached(!down);
  }
}

export function select(id: number): void {
  if (selected.value !== id) editing.value = false;
  selected.value = id;
}

/** The person's accounts elsewhere, for the read-only list; null until read, and `'unknown'` when they could not be. */
export const linked = signal<LinkedAccount[] | 'unknown' | null>(null);

export async function loadLinked(): Promise<void> {
  try {
    linked.value = (await getAccounts()).accounts;
  } catch {
    linked.value = 'unknown';
  }
}

/** The room is left: her state stops answering for it. */
export function leaveRoom(): void {
  herRoomLeft();
}
