// The person's benches as last read, open and closed, what a bench allows (the kinds and limits, read once), and
// opening, closing and reopening a bench. Every change to either list goes through here.
import { signal } from '@preact/signals';
import { ApiError, closeBench, getBenches, getClosedBenches, getWorkshopKinds, openBench, reopenBench } from '../../../api/client';
import type { BenchSummary, WorkshopKinds } from '../../../api/types';
import { load as reloadSession } from '../../../session/session';
import { roomReached } from '../../../shell/her/state';

/** `unreachable`: a 503 or no answer at all; `failed`: any other error. */
export type Load = 'loading' | 'ready' | 'unreachable' | 'failed';

export const benches = signal<readonly BenchSummary[]>([]);
export const listState = signal<Load>('loading');
/** The closed benches, the most recently closed first; null until read or when the read failed. */
export const closedBenches = signal<readonly BenchSummary[] | null>(null);
/** What a bench allows, once read; null until then. */
export const rules = signal<WorkshopKinds | null>(null);

/** Whether `error` means she could not be reached, rather than that she refused; a 401 reloads the session. */
export function unreachable(error: unknown): boolean {
  if (!(error instanceof ApiError)) return true;
  if (error.status === 401) void reloadSession();
  return error.status === 503;
}

/** Reads what a bench allows, once a visit; a failure leaves it null and the next call tries again. */
export async function loadRules(): Promise<void> {
  if (rules.value) return;
  try {
    rules.value = await getWorkshopKinds();
  } catch (error) {
    unreachable(error);
  }
}

/** Reads the open benches; `quiet` keeps what is shown while it reads. */
export async function loadBenches(quiet = false): Promise<void> {
  if (!quiet) listState.value = 'loading';
  try {
    benches.value = (await getBenches()).benches;
    listState.value = 'ready';
    roomReached(true);
  } catch (error) {
    const down = unreachable(error);
    if (!quiet || listState.value !== 'ready') listState.value = down ? 'unreachable' : 'failed';
    roomReached(!down);
  }
}

/** Opens a bench for `ask` (trimmed, non-empty), which Ashley answers in the bench's talk; answers the bench, or null
 * when it did not open. */
export async function open(ask: string): Promise<BenchSummary | null> {
  try {
    const bench = await openBench({ ask });
    benches.value = [bench, ...benches.value];
    return bench;
  } catch (error) {
    unreachable(error);
    return null;
  }
}

/** Reads the closed benches; a failure leaves the list unread (null). */
export async function loadClosed(): Promise<void> {
  try {
    closedBenches.value = (await getClosedBenches()).benches;
  } catch (error) {
    unreachable(error);
    closedBenches.value = null;
  }
}

/** Closes bench `id`; whether it closed. A closed bench leaves the open list for the closed one. */
export async function close(id: number): Promise<boolean> {
  try {
    const bench = await closeBench(id);
    benches.value = benches.value.filter((b) => b.id !== id);
    if (closedBenches.value) closedBenches.value = [bench, ...closedBenches.value.filter((b) => b.id !== id)];
    return true;
  } catch (error) {
    unreachable(error);
    return false;
  }
}

/** Reopens bench `id`; answers it, or null when it did not reopen. It leaves the closed list for the open one. */
export async function reopen(id: number): Promise<BenchSummary | null> {
  try {
    const bench = await reopenBench(id);
    closedBenches.value = closedBenches.value?.filter((b) => b.id !== id) ?? null;
    void loadBenches(true);
    return bench;
  } catch (error) {
    unreachable(error);
    return null;
  }
}
