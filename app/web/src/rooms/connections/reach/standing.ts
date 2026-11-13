// The summary at the head of the room: how many connections need a person, how many are not flagged, how many are one
// person's, and the sentence that says so. Counted from the same `needs` and `missing_scopes` the cards are made from.
import type { ConnectionKindInfo, HouseholdConnection } from '../../../api/types';
import { needOf } from './needs.ts';

export interface Standing {
  total: number;
  needYou: number;
  notFlagged: number;
  personal: number;
  strong: string;
  rest: string;
}

export function standingOf(connections: readonly HouseholdConnection[], kinds: readonly ConnectionKindInfo[]): Standing {
  const total = connections.length;
  const needYou = connections.filter((c) => {
    const kind = kinds.find((k) => k.name === c.kind);
    return kind !== undefined && needOf(c, kind) !== null;
  }).length;
  const base = { total, needYou, notFlagged: total - needYou, personal: connections.filter((c) => c.personal).length };
  if (total === 0) return { ...base, strong: 'Nothing is connected yet.', rest: '' };
  if (needYou === 0) return { ...base, strong: 'Nothing is asking for you.', rest: 'No reconnects, no missing access.' };
  return { ...base, strong: `${needYou} ${needYou === 1 ? 'needs' : 'need'} you.`, rest: needYou < total ? 'The rest are not flagged.' : '' };
}
