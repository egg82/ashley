// What the app shows beside her reply after a turn that changed something or held a change: a note for what ran,
// opening to how and why (kept in the message's fold, `Fold.tsx`), and for what waits a card that shows each call in full (the person agrees to what
// code wrote, not to her description of it) with Agree. Once nothing waits any more the card stays, greyed, without
// the button. Beside the person's Agree, once it is carried out, a quiet note says what became of each call.
import type { WireAgreed, WireReceipt, WireReceipts } from '../../api/types';
import { AgreeButton } from './AgreeButton';
import { copy } from './receiptCopy.ts';
import { agreedLines, doneLine, hasMore, heldCard, opens } from './receipts.ts';

function Detail({ receipt }: { receipt: WireReceipt }) {
  return (
    <li>
      <span class="receipt-head">{receipt.headline}</span>
      {receipt.detail && <code class="receipt-detail">{receipt.detail}</code>}
      {receipt.why && <span class="receipt-why">{copy.why}: {receipt.why}</span>}
    </li>
  );
}

export function Done({ receipts }: { receipts: WireReceipts }) {
  const line = doneLine(receipts);
  if (line === null) return null;
  if (!opens(receipts)) return <p class="receipt receipt-done">{line}</p>;
  return (
    <details class="receipt receipt-done">
      <summary>{line}</summary>
      <ul class="receipt-list">{receipts.ran.map((r, i) => (hasMore(r) ? <Detail key={i} receipt={r} /> : <li key={i}><span class="receipt-head">{r.headline}</span></li>))}</ul>
    </details>
  );
}

export function Held({ receipts, agree }: { receipts: WireReceipts; agree: number | undefined }) {
  const card = heldCard(receipts, agree);
  if (card === null) return null;
  return (
    <div class={`receipt receipt-held${card.agreeable ? '' : ' gone'}`} role="group" aria-label={copy.held}>
      <div class="receipt-title">{copy.held}</div>
      <ul class="receipt-list">{card.items.map((r, i) => <Detail key={i} receipt={r} />)}</ul>
      {card.proposal !== undefined ? <AgreeButton proposal={card.proposal} /> : <p class="receipt-gone">{copy.gone}</p>}
    </div>
  );
}

export function Agreed({ agreed }: { agreed: WireAgreed }) {
  return (
    <div class="receipt receipt-done receipt-agreed" role="status">
      {agreedLines(agreed).map((l, i) => <span key={i}>{l}</span>)}
    </div>
  );
}
