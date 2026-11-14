// What the "What we're working on" list shows for each item of `GET /api/work`: pure, so it is tested without a page.
import type { WorkItem } from '../../api/types';

/** One word for where an item stands. */
export const STATE_WORD: Record<WorkItem['state'], string> = {
  running: 'Running',
  waiting_on_you: 'Waiting on you',
  open: 'Open',
  done: 'Done',
  stopped: 'Stopped',
};

/** Where the item lives, for a link: a bench in the workshop, an open-ended or standing errand among her reminders; a one-shot
 * errand lives in the conversation that asked it and has none. */
export function where(item: Pick<WorkItem, 'kind' | 'id'>): string | null {
  if (item.kind === 'bench') return `/workshop/${item.id}`;
  if (item.kind === 'open_errand' || item.kind === 'standing_errand') return '/memory?tab=reminders';
  return null;
}

export const KIND_WORD: Record<WorkItem['kind'], string> = { errand: 'Errand', open_errand: 'Errand, ongoing', standing_errand: 'Errand, standing', bench: 'Bench' };

/** The rows in the order the server sent them, with how many wait on the person (what the closed list says). */
export function waiting(items: readonly WorkItem[]): number {
  return items.filter((i) => i.state === 'waiting_on_you').length;
}
