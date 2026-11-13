// What the card of her choices beside her reply shows, from the wire's receipts: pure, so it is tested without a page.
import type { WireFact, WireReceipts } from '../../api/types';

/** One row of the card: what it is about, the value it shows as picked (hers, or the person's tap since), and the
 * options to tap; no options means a row the person reads and cannot tap. */
export interface FactRow {
  fact: WireFact;
  picked: string;
  options: readonly string[];
}

/** The rows of the card, in the order she set them, each picked as `tapped` says (by `piece_id:name`) or as she left
 * it; empty when the turn showed none. */
export function factRows(receipts: WireReceipts | null | undefined, tapped: ReadonlyMap<string, string>): FactRow[] {
  return (receipts?.choice_rows ?? []).map((fact) => ({ fact, picked: tapped.get(keyOf(fact)) ?? fact.value, options: fact.option_values }));
}

export function keyOf(fact: Pick<WireFact, 'piece_id' | 'name'>): string {
  return `${fact.piece_id}:${fact.name}`;
}

/** What a tap that did not go through says, by its status. */
export function whyNotSet(status: number | undefined): string {
  if (status === 404) return "That isn't on the bench any more.";
  if (status === 409) return 'The piece changed just then. Tap again.';
  if (status === 410) return 'This bench is closed. Nothing changed.';
  return "That didn't go through. Nothing changed. Try again.";
}
