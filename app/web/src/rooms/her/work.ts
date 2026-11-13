// What the work list holds: the signed-in person's open errands and benches as last read, and whether they could be
// read. Read when her room is shown and again whenever something it lists may have moved: a turn on their thread (an
// ask is made or answered there), a change to one of their benches (a job's piece included), or the feed (re)opening.
// An errand's own checks and a one-shot errand's source answering publish no event, so those show on the next of these.
import { signal } from '@preact/signals';
import { ApiError, getWork } from '../../api/client';
import type { WorkItem } from '../../api/types';
import { onBenchChanged, onResync, onThreadTurn } from '../../session/live';
import { load as reloadSession } from '../../session/session';

export type WorkState = 'loading' | 'ready' | 'unreachable' | 'failed';

export const work = signal<WorkItem[]>([]);
export const workState = signal<WorkState>('loading');

let reading = 0;

export async function loadWork(): Promise<void> {
  const mine = ++reading;
  try {
    const items = (await getWork()).entries;
    if (mine !== reading) return;
    work.value = items;
    workState.value = 'ready';
  } catch (error) {
    if (mine !== reading) return;
    if (error instanceof ApiError && error.status === 401) void reloadSession();
    workState.value = error instanceof ApiError && error.status !== 503 ? 'failed' : 'unreachable';
  }
}

/** Reads the list now and again on each cue above; returns the unsubscribe. */
export function watchWork(): () => void {
  void loadWork();
  const off = [onThreadTurn(() => void loadWork()), onBenchChanged(() => void loadWork()), onResync(() => void loadWork())];
  return () => off.forEach((o) => o());
}
