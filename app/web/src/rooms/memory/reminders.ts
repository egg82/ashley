// What the Reminders tab holds: the signed-in person's reminders as last read, whether they could be read, and
// cancelling one. Every change goes through here, so a row never edits the list itself.
import { signal } from '@preact/signals';
import { ApiError, cancelReminder, getReminders } from '../../api/client';
import type { Reminder } from '../../api/types';
import { load as reloadSession } from '../../session/session';
import type { Load, Outcome } from './memory';
import { note } from './memory';

export const reminders = signal<Reminder[]>([]);
export const remindersState = signal<Load>('loading');

function outcomeOf(error: unknown): Outcome {
  if (error instanceof ApiError) {
    if (error.status === 401) void reloadSession();
    if (error.status === 404) return 'gone';
    if (error.status === 503) return 'unreachable';
    return 'failed';
  }
  return 'unreachable';
}

export async function loadReminders(): Promise<void> {
  remindersState.value = 'loading';
  try {
    reminders.value = (await getReminders()).reminders;
    remindersState.value = 'ready';
  } catch (error) {
    remindersState.value = outcomeOf(error) === 'unreachable' ? 'unreachable' : 'failed';
  }
}

/** Cancels reminder `id` and takes it off the list; one that already fired or was cancelled elsewhere goes too. */
export async function cancel(id: number): Promise<Outcome> {
  try {
    await cancelReminder(id);
    note.value = { text: 'Done. It’s off your list.', forgot: false };
  } catch (error) {
    const outcome = outcomeOf(error);
    if (outcome !== 'gone') return outcome;
    note.value = { text: 'That reminder had already fired or been cancelled.', forgot: false };
    reminders.value = reminders.value.filter((r) => r.id !== id);
    return outcome;
  }
  reminders.value = reminders.value.filter((r) => r.id !== id);
  return 'ok';
}
