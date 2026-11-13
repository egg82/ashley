// What the "On her own" tab holds: the signed-in person's outside actions as last read, and whether they could be read.
import { signal } from '@preact/signals';
import { ApiError } from '../../api/client';
import { getOutsideActions } from '../../api/outsideActions';
import type { OutsideAction } from '../../api/types';
import { hour, locale } from '../../household/format';
import { load as reloadSession } from '../../session/session';
import type { Load } from './memory';

export const outside = signal<OutsideAction[]>([]);
export const outsideState = signal<Load>('loading');

export async function loadOutside(): Promise<void> {
  outsideState.value = 'loading';
  try {
    outside.value = (await getOutsideActions()).outside_actions;
    outsideState.value = 'ready';
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) void reloadSession();
    outsideState.value = error instanceof ApiError && error.status !== 503 ? 'failed' : 'unreachable';
  }
}

/** "Sat 1 Nov, 09:00": when she did it, in the household's locale and clock and the browser's zone. */
export function doneAt(iso: string): string {
  const at = new Date(iso);
  const day = at.toLocaleDateString(locale(), { weekday: 'short', day: 'numeric', month: 'short' });
  return `${day}, ${at.toLocaleTimeString(locale(), { hour: hour(), minute: '2-digit' })}`;
}

export const TIER: Record<OutsideAction['tier'], string> = { runs: 'Always runs', judged: 'Judged' };
export const NO_LABEL = 'A change';
export const NO_REASON = 'No reason kept';
