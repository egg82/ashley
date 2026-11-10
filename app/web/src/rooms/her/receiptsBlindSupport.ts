// Support for the blind tests of how a turn's receipts render (`~/scratch/ashley/receipts/spec.txt`, decision 3, web chat
// and kiosk). The spec names no web module, so every guess is here and only here; a reconciler rewires this one file.
//
// G1  A pure module `./receipts.ts` beside the components holds what the components show, as functions of the wire's
//     `receipts` (`ChatConversationTurn.receipts`) and the turn's `agree`: `doneNote` is the quiet one-line note for what
//     was done ("Done: <headline>, <headline>"), null when nothing was; `doneItems` is what one tap opens, the same
//     receipts with their detail and why; `heldCard` is the Agree card, null when nothing was held.
// G2  `heldCard(receipts, agree)` is `{ items, agreeable, proposal }`: `items` each held call's headline, detail and why in
//     order, whole; `agreeable` is true exactly when `agree` (the turn's own, as now) is a number, and `proposal` is that
//     number, so the button is enabled by the rule that enables it today; false keeps the card, greyed, with no button.
import { doneLine, heldCard } from './receipts.ts';

export type WireReceipt = { headline: string; detail: string | null; why: string | null };
export type WireReceipts = { ran: WireReceipt[]; held: WireReceipt[]; proposal_id: number | null };
export type Card = { items: WireReceipt[]; agreeable: boolean; proposal: number | undefined } | null;

export const note = (r: WireReceipts | null | undefined): string | null => (r ? doneLine(r) : null);
export const items = (r: WireReceipts | null | undefined): WireReceipt[] => (r ? r.ran : []);
export const card = (r: WireReceipts | null | undefined, agree: number | undefined): Card => heldCard(r, agree);

export const receipt = (headline: string, detail: string | null = null, why: string | null = null): WireReceipt => ({ headline, detail, why });
export const wire = (ran: WireReceipt[], held: WireReceipt[] = [], proposal_id: number | null = null): WireReceipts => ({ ran, held, proposal_id });
