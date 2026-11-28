// What started something she did on her own, named from data already on the board: the watch, bench or errand its
// `cause` points at when that is in the same list, else what kind of thing it was. Never a guess at more.
import type { WorkItem } from '../../../api/types';

type Cause = NonNullable<WorkItem['cause']>;

const POINTS_AT: Partial<Record<Cause['kind'], readonly WorkItem['kind'][]>> = {
  watch: ['watch'],
  bench: ['bench'],
  open_errand: ['open_errand'],
  standing_errand: ['standing_errand'],
};

const KIND_WORDS: Record<Cause['kind'], string> = {
  wake: 'something happening at home',
  reminder: 'a reminder',
  open_errand: 'an errand',
  standing_errand: 'a standing errand',
  watch: 'a watch',
  bench: 'a bench',
  turn: 'your message, which read words from outside the household',
};

/** The cause in words, or null when the item has none. */
export function causeLine(item: WorkItem, all: readonly WorkItem[]): string | null {
  const cause = item.cause;
  if (!cause) return null;
  const kinds = POINTS_AT[cause.kind];
  const named = kinds && all.find((i) => i.id === cause.id && kinds.includes(i.kind));
  return named ? named.title : KIND_WORDS[cause.kind] ?? null;
}
