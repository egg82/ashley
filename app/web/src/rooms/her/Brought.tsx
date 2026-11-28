// What her tools brought up on a line of hers, each drawn through the parts registry under her words. Once the talk has
// moved on (a later line exists) each folds to a chip that opens on a tap; which are open is this page's alone.
import { useState } from 'preact/hooks';
import type { BroughtUp } from '../../api/types';
import { chipOf, drawPart } from '../../components/parts/registry';
import { PERSON_SOURCES } from '../../session/parts';

function Folded({ item }: { item: BroughtUp }) {
  const [open, setOpen] = useState(false);
  return (
    <div class="brought-item">
      <button type="button" class="brought-chip" aria-expanded={open} onClick={() => setOpen(!open)}>
        {chipOf(item.kind, PERSON_SOURCES, item.ref)}
      </button>
      {open && <div class="brought-card">{drawPart(item.kind, PERSON_SOURCES, item.ref)}</div>}
    </div>
  );
}

export function Brought({ items, folded }: { items: readonly BroughtUp[]; folded: boolean }) {
  return (
    <div class={`brought${folded ? ' folded' : ''}`}>
      {items.map((item) => folded
        ? <Folded key={`${item.kind}:${item.ref}`} item={item} />
        : <div key={`${item.kind}:${item.ref}`} class="brought-card">{drawPart(item.kind, PERSON_SOURCES, item.ref)}</div>)}
    </div>
  );
}
