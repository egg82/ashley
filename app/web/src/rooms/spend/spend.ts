// What the Usage room shows: the spend report as last read, and whether it could be.
import { signal } from '@preact/signals';
import { getSpend } from '../../api/client';
import type { SpendResponse } from '../../api/types';
import { herRoomLeft, roomReached } from '../../shell/her/state';

export type SpendLoad = 'loading' | 'ready' | 'failed';

export const spend = signal<SpendResponse | null>(null);
export const spendState = signal<SpendLoad>('loading');

export async function loadSpend(): Promise<void> {
  spendState.value = 'loading';
  try {
    spend.value = await getSpend();
    spendState.value = 'ready';
    roomReached(true);
  } catch {
    spendState.value = 'failed';
    roomReached(false);
  }
}

/** The room is left: her state stops answering for it. */
export function leaveRoom(): void {
  herRoomLeft();
}
