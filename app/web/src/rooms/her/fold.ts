// What a message folds away: everything under her reply that is detail, not a decision. Pure, so it is tested without a
// page. A held card waits for the person to agree, so it is never folded.
import type { WireReceipts } from '../../api/types';
import { doneLine } from './receipts.ts';

/** What the fold holds: how many pictures she was given and whether the note of what ran is in it. */
export interface Folded {
  pictures: number;
  note: boolean;
}

/** The fold of a message, null when it has nothing to fold. */
export function foldOf(receipts: WireReceipts | null | undefined, looks: readonly unknown[] | undefined): Folded | null {
  const folded = { pictures: looks?.length ?? 0, note: receipts != null && doneLine(receipts) !== null };
  return folded.pictures || folded.note ? folded : null;
}

/** The one small line a fold shows closed: "2 pictures · details". */
export function foldLine(folded: Folded): string {
  const parts = [];
  if (folded.pictures) parts.push(folded.pictures === 1 ? '1 picture' : `${folded.pictures} pictures`);
  if (folded.note) parts.push('details');
  return parts.join(' · ');
}
