// Which of the room's groups a connection belongs to: what it gives her. Driven by the connection's kind, never by its text.
import type { HouseholdConnection } from '../../../api/types';
import data from './groups.json' with { type: 'json' };

export interface Group {
  id: string;
  title: string;
  items: HouseholdConnection[];
}

/** The groups that hold at least one of `connections`, in the room's order; kinds no group names fall into the last. */
export function groupsOf(connections: readonly HouseholdConnection[]): Group[] {
  const named = data.groups.map((g): Group => ({ id: g.id, title: g.title, items: connections.filter((c) => g.kinds.includes(c.kind)) }));
  const known = new Set(data.groups.flatMap((g) => g.kinds));
  const rest: Group = { ...data.other, items: connections.filter((c) => !known.has(c.kind)) };
  return [...named, rest].filter((g) => g.items.length > 0);
}
