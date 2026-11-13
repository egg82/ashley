// Who holds a connection and whether that can change: the line the opened row says beside "Held by".
import type { ConnectionKindInfo, HouseholdConnection } from '../../../api/types';
import { holderOf } from './sentence.ts';

/** Why a connection cannot be handed over or taken back, or null when the payload lets it move one way or the other. */
export function stayReason(c: HouseholdConnection, kind: ConnectionKindInfo): string | null {
  if (c.can_hand_over || c.can_take_back) return null;
  if (kind.holders.length === 1) return kind.holders[0] === 'person' ? 'This kind is always one person’s.' : 'This kind is always the household’s.';
  if (!c.can_change) return `Only ${holderOf(c)} can change this.`;
  return c.personal ? 'Only the person who added it can take it back.' : null;
}

/** What it means for who may use it, said for the holder it has now. */
export function holdsLine(c: HouseholdConnection): string {
  return c.personal ? `used only in chats that are ${holderOf(c)}’s own` : 'anyone at home can ask her to use it';
}
