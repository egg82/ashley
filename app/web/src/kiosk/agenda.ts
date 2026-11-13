// The glance's calendar as rows: the events of one day, each with its time written as the household writes times.
import { hour, locale } from '../household/format.ts';
import type { KioskGlance } from '../api/types.ts';

export type AgendaEvent = NonNullable<KioskGlance['calendar']>[number];

/** An event's time in the household's locale and clock; "All day" for an all-day one. `time` is the household's own wall
 * clock (`HH:MM`), so it is formatted as a plain time of day and never moved to this screen's zone. */
export function whenOf(time: string | null, wording: string = locale()): string {
  if (time === null) return 'All day';
  const [h = 0, m = 0] = time.split(':').map(Number);
  return new Date(Date.UTC(2000, 0, 1, h, m)).toLocaleTimeString(wording, { hour: hour(), minute: '2-digit', timeZone: 'UTC' });
}

/** The events of `day`, in the order the glance gave them. */
export function ofDay(events: readonly AgendaEvent[], day: AgendaEvent['day']): AgendaEvent[] {
  return events.filter((e) => e.day === day);
}
