// What a receipt line says, from the wire's receipts: pure, so it is tested without a page.
import type { WireAgreed, WireReceipt, WireReceipts } from '../../api/types';
import { copy } from './receiptCopy.ts';

/** The quiet one line for what ran: "Done: <headline>, <headline>"; null when nothing ran. */
export function doneLine(receipts: WireReceipts): string | null {
  return receipts.ran.length ? `${copy.done}: ${receipts.ran.map((r) => r.headline).join(', ')}` : null;
}

/** Whether a receipt has more to show than its headline. */
export function hasMore(receipt: WireReceipt): boolean {
  return receipt.detail != null || receipt.why != null;
}

/** Whether the done note opens to anything: some receipt carries a detail or a reason. */
export function opens(receipts: WireReceipts): boolean {
  return receipts.ran.some(hasMore);
}

/** What the card for held calls shows: each call whole, and the proposal the Agree button sends, which only the turn's
 * own `agree` may supply. Null when nothing was held. */
export function heldCard(receipts: WireReceipts | null | undefined, agree: number | undefined):
  { items: WireReceipt[]; agreeable: boolean; proposal: number | undefined } | null {
  if (!receipts || !receipts.held.length) return null;
  return { items: receipts.held, agreeable: agree !== undefined, proposal: agree };
}

const AGREED: readonly (readonly [WireAgreed['carried'][number]['status'], string])[] = [
  ['ran', copy.done], ['failed', copy.failed], ['not_run', copy.notRun]];

/** The quiet lines beside the person's Agree once it is carried out: one per outcome that some call had, "Done: <summary>,
 * <summary>", then what didn't work, then what can't be done from here; or the one line saying it was interrupted. */
export function agreedLines(agreed: WireAgreed): string[] {
  if (agreed.interrupted) return [copy.interrupted];
  return AGREED.map(([status, label]) => [label, agreed.carried.filter((c) => c.status === status).map((c) => c.summary)] as const)
    .filter(([, summaries]) => summaries.length)
    .map(([label, summaries]) => `${label}: ${summaries.join(', ')}`);
}
