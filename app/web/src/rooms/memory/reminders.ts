// What the Reminders tab holds: the signed-in person's reminders as last read, whether they could be read, and
// cancelling one. Every change goes through here, so a row never edits the list itself.
import { signal } from '@preact/signals';
import { ApiError, cancelReminder, createReminder, getReminders, getWorkshopKinds, setReminderMethod } from '../../api/client';
import type { Reminder, ReminderRequest } from '../../api/types';
import { load as reloadSession } from '../../session/session';
import type { Load, Outcome } from './memory';
import { note } from './memory';

export const reminders = signal<Reminder[]>([]);
export const remindersState = signal<Load>('loading');
/** The household's kinds of work a standing errand can name, as last read; empty until read or when they cannot be. */
export const kinds = signal<{ name: string; label: string }[]>([]);
/** How a write ended: `refused` is a 422, which says the reminder or the method cannot be set as asked. */
export type Written = Outcome | 'refused';

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

export async function loadKinds(): Promise<void> {
  try {
    kinds.value = (await getWorkshopKinds()).work_kinds;
  } catch (error) {
    outcomeOf(error);
  }
}

function writeOutcome(error: unknown): Written {
  return error instanceof ApiError && error.status === 422 ? 'refused' : outcomeOf(error);
}

/** Sets a reminder for the signed-in person and puts it in the list in time order. */
export async function create(body: ReminderRequest): Promise<Written> {
  try {
    const made = await createReminder(body);
    reminders.value = [...reminders.value, made].sort((a, b) => a.due_at.localeCompare(b.due_at) || a.id - b.id);
    note.value = { text: made.method ? 'Done. She will carry it out each time.' : 'Done. She will remind you.', forgot: false };
    return 'ok';
  } catch (error) {
    return writeOutcome(error);
  }
}

/** Sets reminder `id`'s method, or clears it with null, and shows the reminder as it now is. */
export async function setMethod(id: number, method: string | null): Promise<Written> {
  try {
    const changed = await setReminderMethod(id, method);
    reminders.value = reminders.value.map((r) => (r.id === id ? changed : r));
    note.value = { text: method ? 'Done. It is a standing errand now.' : 'Done. It is an ordinary reminder again.', forgot: false };
    return 'ok';
  } catch (error) {
    const outcome = writeOutcome(error);
    if (outcome === 'gone') reminders.value = reminders.value.filter((r) => r.id !== id);
    return outcome;
  }
}
