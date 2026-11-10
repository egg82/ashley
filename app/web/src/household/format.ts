// How the household writes dates, times and numbers: its locale and clock, set on the household page. Every formatter
// in the app takes its locale from `locale()`; the person's pages set `writing` from `GET /api/household`, the kiosk's
// from its glance. Until either answers it holds what a new household starts with.
import { signal } from '@preact/signals';

export type Clock = '12h' | '24h';

export interface Writing {
  /** A BCP 47 tag, as `en-US`. */
  locale: string;
  clock: Clock;
}

export const writing = signal<Writing>({ locale: 'en-US', clock: '24h' });

/** The household's locale with its clock as the Unicode hour-cycle extension (`en-US-u-hc-h23`), for any `Intl` call. A
 * format call must not pass `hourCycle` or `hour12` itself, which would override the household's clock. */
export function locale(w: Writing = writing.value): string {
  return `${w.locale}-u-hc-${w.clock === '12h' ? 'h12' : 'h23'}`;
}

/** The `hour` option every time of day is written with: two digits on a 24-hour clock (`08:05`), none padded on a
 * 12-hour one (`8:05 AM`). */
export function hour(w: Writing = writing.value): '2-digit' | 'numeric' {
  return w.clock === '24h' ? '2-digit' : 'numeric';
}
