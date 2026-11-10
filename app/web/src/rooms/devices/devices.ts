// The household's devices as last read, and whether they could be.
import { signal } from '@preact/signals';
import { getDevices } from '../../api/client';
import type { ListedDevice } from '../../api/types';
import { herRoomLeft, roomReached } from '../../shell/her/state';

export type DevicesLoad = 'loading' | 'ready' | 'failed';

export const devices = signal<ListedDevice[]>([]);
export const devicesState = signal<DevicesLoad>('loading');

export async function loadDevices(): Promise<void> {
  devicesState.value = 'loading';
  try {
    devices.value = (await getDevices()).devices;
    devicesState.value = 'ready';
    roomReached(true);
  } catch {
    devicesState.value = 'failed';
    roomReached(false);
  }
}

/** The room is left: her state stops answering for it. */
export function leaveRoom(): void {
  herRoomLeft();
}
