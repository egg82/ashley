// The board's lanes from `GET /api/work`: each item under its `lane`, the lanes in the order a person reads them (what
// waits on them first), the server's order kept within a lane. A lane the client does not know yet still shows, last,
// under a name made from its key, so a new lane from the server is never dropped.
import type { WorkItem } from '../../../api/types';

export const LANE_ORDER = ['waiting', 'doing', 'on_her_own', 'would_like', 'done_untold', 'kept_quiet'] as const;

const LANE_NAME: Record<(typeof LANE_ORDER)[number], string> = {
  waiting: 'Waiting on you',
  doing: "She's doing",
  on_her_own: 'On her own',
  would_like: 'Would like to',
  done_untold: 'Done, not yet told',
  kept_quiet: 'Kept quiet',
};

export interface Lane {
  lane: string;
  name: string;
  items: WorkItem[];
}

export function laneName(lane: string): string {
  const known = (LANE_NAME as Record<string, string | undefined>)[lane];
  if (known) return known;
  const words = lane.replace(/_/g, ' ').trim();
  return words ? words[0]!.toUpperCase() + words.slice(1) : 'Other';
}

/** The non-empty lanes, known ones in LANE_ORDER, then any others in the order they first appear. */
export function lanes(items: readonly WorkItem[]): Lane[] {
  const by = new Map<string, WorkItem[]>();
  for (const item of items) {
    const lane = String(item.lane);
    by.set(lane, [...(by.get(lane) ?? []), item]);
  }
  const known: readonly string[] = LANE_ORDER;
  const order = [...LANE_ORDER.filter((l) => by.has(l)), ...[...by.keys()].filter((l) => !known.includes(l))];
  return order.map((lane) => ({ lane, name: laneName(lane), items: by.get(lane)! }));
}
