// What the person card lists, from the facts and voiceprints read: pure, so the order is checked without a screen.
import type { MemoryFact, Voiceprint } from '../../api/types';
import { isNew, KINDS, tabOf } from '../../rooms/memory/facts.ts';

export interface PersonView {
  /** About the person and new this week, newest first: what to check first. */
  fresh: MemoryFact[];
  /** The rest of theirs, grouped by kind, the newest first within a kind. */
  yours: MemoryFact[];
  /** The household's, newest first, so what is new leads. */
  household: MemoryFact[];
}

const newest = (a: MemoryFact, b: MemoryFact) => Date.parse(b.valid_from) - Date.parse(a.valid_from);
const byKind = (a: MemoryFact, b: MemoryFact) => KINDS.indexOf(a.kind) - KINDS.indexOf(b.kind) || newest(a, b);

export function personView(facts: readonly MemoryFact[], now: number): PersonView {
  const mine = facts.filter((f) => tabOf(f) === 'you');
  return {
    fresh: mine.filter((f) => isNew(f, now)).sort(newest),
    yours: mine.filter((f) => !isNew(f, now)).sort(byKind),
    household: facts.filter((f) => tabOf(f) === 'household').sort(newest),
  };
}

/** The voiceprints oldest first, as the voice tab lists them. */
export function printsOldestFirst(prints: readonly Voiceprint[]): Voiceprint[] {
  return [...prints].sort((a, b) => Date.parse(a.enrolled_at) - Date.parse(b.enrolled_at));
}
