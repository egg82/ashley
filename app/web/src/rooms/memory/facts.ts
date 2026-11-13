// Pure reads over the facts the API returned: which tab a fact belongs to, what is new this week, and how its dates
// and source read on screen.
import type { FactKind, FactSource, MemoryFact } from '../../api/types';
import { hour, locale } from '../../household/format.ts';

export type Tab = 'you' | 'household';
/** A tab of the room: the facts' two, the person's reminders, and what she did on her own. */
export type RoomTab = Tab | 'reminders' | 'outside';

const WEEK_MS = 7 * 24 * 60 * 60 * 1000;

/** A household fact is about no one and owned by no one (`MemoryFact`'s contract). */
export function tabOf(fact: MemoryFact): Tab {
  return fact.about === null && fact.owner === null ? 'household' : 'you';
}

/** Where the signed-in person (`me`) may move a fact about no one: theirs goes to the household, the household's
 * becomes theirs. A fact about someone stays theirs (the server refuses it too). */
export function moveOf(fact: MemoryFact, me: number | undefined): 'household' | 'mine' | null {
  if (me === undefined || fact.about !== null) return null;
  if (fact.owner === null) return 'mine';
  return fact.owner.id === me ? 'household' : null;
}

/** New this week: it became true to her within the last seven days. */
export function isNew(fact: MemoryFact, now: number): boolean {
  return now - Date.parse(fact.valid_from) < WEEK_MS;
}

export const KINDS: readonly FactKind[] = ['preference', 'routine', 'plan', 'person', 'health', 'finance', 'diet', 'home', 'other'];

const SOURCE_LABEL: Record<FactSource['conversation_kind'], string> = {
  command: 'Command', chat: 'Chat', brainstorm: 'Brainstorm',
};

export function sourceLabel(source: FactSource): string {
  return SOURCE_LABEL[source.conversation_kind];
}

/** Where the conversation started, "on Discord" or "by voice in the kitchen"; null when it was not recorded. */
export function whereLabel(source: FactSource): string | null {
  const place = source.place ? ` in the ${source.place}` : '';
  switch (source.channel) {
    case 'voice': return `by voice${place}`;
    case 'discord': return 'on Discord';
    case 'device': return `on a device${place}`;
    case 'web': return 'on the web';
    default: return null;
  }
}

function sameDay(a: Date, b: Date): boolean {
  return a.toDateString() === b.toDateString();
}

/** "today", "Oct 24", or "Oct 24, 2025" outside this year. */
export function day(iso: string, now = new Date()): string {
  const d = new Date(iso);
  if (sameDay(d, now)) return 'today';
  const year = d.getFullYear() === now.getFullYear() ? undefined : 'numeric';
  return d.toLocaleDateString(locale(), { month: 'short', day: 'numeric', year });
}

/** "08:12" today, else "Oct 24 17:40", on the household's clock. */
export function moment(iso: string, now = new Date()): string {
  const d = new Date(iso);
  const time = d.toLocaleTimeString(locale(), { hour: hour(), minute: '2-digit' });
  return sameDay(d, now) ? time : `${day(iso, now)} ${time}`;
}

/** Facts whose text holds `q`, ignoring case; every fact when `q` is blank. */
export function matching(facts: readonly MemoryFact[], q: string): MemoryFact[] {
  const needle = q.trim().toLowerCase();
  return needle ? facts.filter((f) => f.text.toLowerCase().includes(needle)) : [...facts];
}
