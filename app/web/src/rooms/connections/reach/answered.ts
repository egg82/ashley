// The meta line under a sentence, from the connection's own fields: when it last answered, who added it and who holds it.
// A connection whose `checked_at` is its `added_at` was checked once, when it was added, and says so.
import type { HouseholdConnection } from '../../../api/types';
import { holderOf } from './sentence.ts';

const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

function plural(n: number, unit: string): string {
  return `${n} ${unit}${n === 1 ? '' : 's'}`;
}

/** How long ago `iso` was at `now`, in words: "14 minutes ago". */
export function ageText(iso: string, now: number): string {
  const ms = Math.max(0, now - Date.parse(iso));
  if (ms < MIN) return 'just now';
  if (ms < HOUR) return `${plural(Math.round(ms / MIN), 'minute')} ago`;
  if (ms < DAY) return `${plural(Math.round(ms / HOUR), 'hour')} ago`;
  return `${plural(Math.round(ms / DAY), 'day')} ago`;
}

/** The same, short enough to print under a node: "14 min ago". */
export function ageShort(iso: string, now: number): string {
  const ms = Math.max(0, now - Date.parse(iso));
  if (ms < MIN) return 'now';
  if (ms < HOUR) return `${Math.round(ms / MIN)} min ago`;
  if (ms < DAY) return `${Math.round(ms / HOUR)} h ago`;
  return `${Math.round(ms / DAY)} d ago`;
}

export type Band = 'today' | 'week' | 'older';

/** How recently it answered: today, within the week, or longer ago. */
export function bandOf(iso: string, now: number): Band {
  const ms = now - Date.parse(iso);
  return ms < DAY ? 'today' : ms < 7 * DAY ? 'week' : 'older';
}

export interface Meta {
  /** True when it has answered since it was added; false when it was only checked when added. */
  answeredSince: boolean;
  answered: string;
  added: string;
  /** `personal` marks a connection held by one person. */
  holder: { personal: boolean; text: string };
}

/** `day` writes a date the way the household does ("1 Nov"). */
export function metaOf(c: HouseholdConnection, now: number, day: (iso: string) => string): Meta {
  const since = c.checked_at !== c.added_at;
  const age = ageText(c.checked_at, now);
  return {
    answeredSince: since,
    answered: since ? `answered ${age}` : `answered once, ${age}`,
    added: c.added_by ? `added by ${c.added_by.name}, ${day(c.added_at)}` : `carried over from her setup, ${day(c.added_at)}`,
    holder: c.personal ? { personal: true, text: `${holderOf(c)} alone` } : { personal: false, text: 'household' },
  };
}
