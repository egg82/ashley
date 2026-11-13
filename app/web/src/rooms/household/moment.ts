// The household's local time as the page shows it: the hand of the 24-hour dial, and the example line of how she says things.
import { hour, locale, type Writing } from '../../household/format.ts';

export interface Moment {
  /** Hours since local midnight, 0 up to 24. */
  hours: number;
  /** The time as the household writes it. */
  text: string;
  /** `UTC-07:00`. */
  offset: string;
}

/** The local time in `zone` at `now`, or null when the browser does not know the zone or the language. */
export function momentIn(now: Date, zone: string, w: Writing): Moment | null {
  try {
    const parts = new Intl.DateTimeFormat('en-US', { timeZone: zone, hourCycle: 'h23', hour: 'numeric', minute: 'numeric',
      timeZoneName: 'longOffset' }).formatToParts(now);
    const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
    const offset = get('timeZoneName').replace('GMT', 'UTC');
    const text = now.toLocaleTimeString(locale(w), { timeZone: zone, hour: hour(w), minute: '2-digit' });
    return { hours: Number(get('hour')) + Number(get('minute')) / 60, text, offset: offset === 'UTC' ? 'UTC+00:00' : offset };
  } catch {
    return null;
  }
}

/** "72°F, 14:05, Thursday" in the household's own writing; the temperature is made up. Null when the browser cannot write it. */
export function sayLine(now: Date, zone: string, w: Writing & { unit_system: 'imperial' | 'metric' }): string | null {
  const when = momentIn(now, zone, w);
  if (!when) return null;
  try {
    const metric = w.unit_system === 'metric';
    const warm = new Intl.NumberFormat(locale(w), { style: 'unit', unit: metric ? 'celsius' : 'fahrenheit' }).format(metric ? 22 : 72);
    const day = now.toLocaleDateString(locale(w), { timeZone: zone, weekday: 'long' });
    return `${warm}, ${when.text}, ${day}`;
  } catch {
    return null;
  }
}
