// The three spans the room can show, and which one the address asks for.
import type { SpendResponse } from '../../api/types';

export type Win = 'today' | 'week' | 'month';

export const WINDOWS: { id: Win; label: string; when: string }[] = [
  { id: 'today', label: 'Today', when: 'today' },
  { id: 'week', label: 'This week', when: 'this week' },
  { id: 'month', label: 'This month', when: 'this month' },
];

/** The window a `?w=` value names; the month when it names none. */
export function winOf(value: string | undefined): Win {
  return WINDOWS.find((w) => w.id === value)?.id ?? 'month';
}

export function whenOf(win: Win): string {
  return WINDOWS.find((w) => w.id === win)!.when;
}

/** The instant a window starts, or null when the report names none. */
export function startsAt(s: SpendResponse, win: Win): string | null {
  return s.windows.find((w) => w.name === win)?.starts_at ?? null;
}
