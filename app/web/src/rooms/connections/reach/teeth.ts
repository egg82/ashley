// A connection's resources (one per mailbox) as teeth: shared with the household, or kept to the holder.
import type { HouseholdConnection } from '../../../api/types';
import { holderOf } from './sentence.ts';

export interface Tooth {
  ref: string;
  name: string;
  shared: boolean;
}

export function teethOf(c: HouseholdConnection): Tooth[] {
  return c.resources.map((r) => ({ ref: r.ref, name: r.name, shared: r.shared }));
}

/** "1 shared with the household, 5 kept to Alex"; empty when it reaches no resources. */
export function teethSummary(c: HouseholdConnection): string {
  const shared = c.resources.filter((r) => r.shared).length;
  const kept = c.resources.length - shared;
  if (c.resources.length === 0) return '';
  const parts = [shared > 0 ? `${shared} shared with the household` : '', kept > 0 ? `${kept} kept to ${holderOf(c)}` : ''];
  return parts.filter(Boolean).join(', ');
}
