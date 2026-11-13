// The signed-in person's own quiet hours as last read, and what the last save came to.
import { signal } from '@preact/signals';
import { getQuiet, putQuiet } from '../../api/quiet';
import type { QuietHours, QuietRefused } from '../../api/types';

export type QuietLoad = 'loading' | 'ready' | 'failed';

export const quiet = signal<QuietHours['quiet']>(null);
export const quietState = signal<QuietLoad>('loading');
/** What the last save came to; null when there is nothing to say. */
export const quietSaid = signal<QuietRefused['invalid'] | 'saved' | 'failed' | null>(null);

export async function loadQuiet(): Promise<void> {
  quietState.value = 'loading';
  try {
    quiet.value = (await getQuiet()).quiet;
    quietState.value = 'ready';
  } catch {
    quietState.value = 'failed';
  }
}

/** Saves the window (null clears it); whether it was stored. */
export async function saveQuiet(window: QuietHours['quiet']): Promise<boolean> {
  quietSaid.value = null;
  try {
    const got = await putQuiet({ quiet: window });
    if ('invalid' in got) {
      quietSaid.value = got.invalid;
      return false;
    }
    quiet.value = got.quiet;
    quietSaid.value = 'saved';
    return true;
  } catch {
    quietSaid.value = 'failed';
    return false;
  }
}
