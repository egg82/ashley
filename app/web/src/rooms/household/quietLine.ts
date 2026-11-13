// How a quiet-hours window reads on the page.
import type { QuietHours } from '../../api/types.ts';

/** The hour as a person reads it on `clock`: `22:00`, or `10 PM`. */
export function hourLabel(hour: number, clock: '12h' | '24h'): string {
  if (clock === '24h') return `${String(hour).padStart(2, '0')}:00`;
  return `${hour % 12 === 0 ? 12 : hour % 12} ${hour < 12 ? 'AM' : 'PM'}`;
}

/** The window as one line, `10 PM to 7 AM (America/Denver)`; the two hours differ, so a window is never empty. */
export function windowLine(w: NonNullable<QuietHours['quiet']>, clock: '12h' | '24h'): string {
  return `${hourLabel(w.start, clock)} to ${hourLabel(w.end, clock)} (${w.timezone})`;
}
