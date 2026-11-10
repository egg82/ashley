// The detail under her reply, closed to one line the person opens: the pictures she looked at and the note of what
// ran. Native <details>, so it opens from the keyboard. Cards that wait on a decision are not in it.
import type { ChatLook, WireReceipts } from '../../api/types';
import { foldLine, foldOf } from './fold.ts';
import { LookDetails } from './LookDetails';
import { Done } from './Receipts';

export function Fold({ receipts, looks }: { receipts: WireReceipts | null | undefined; looks: readonly ChatLook[] | undefined }) {
  const folded = foldOf(receipts, looks);
  if (folded === null) return null;
  return (
    <details class="run fold">
      <summary>{foldLine(folded)}</summary>
      {receipts && <Done receipts={receipts} />}
      {looks?.map((l) => <LookDetails key={l.id} look={l} />)}
    </details>
  );
}
