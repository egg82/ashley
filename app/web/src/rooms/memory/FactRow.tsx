// One fact as a row of "Everything she knows". Opening it turns it into its card in place, with Correct and Forget.
import { useState } from 'preact/hooks';
import type { MemoryFact } from '../../api/types';
import { Kind, Vis } from '../../components/FactParts';
import { FactCard } from './FactCard';
import { day } from './facts';
import { selected } from './memory';

export function FactRow({ fact, fresh }: { fact: MemoryFact; fresh: boolean }) {
  const [open, setOpen] = useState(fresh);
  if (open) return <FactCard fact={fact} fresh={fresh} onClose={() => setOpen(false)} />;
  return (
    <div class={`fact row${selected.value === fact.id ? ' sel' : ''}`} data-kind={fact.kind}>
      <Kind kind={fact.kind} named={false} />
      <button
        class="t"
        type="button"
        aria-expanded="false"
        onClick={() => {
          selected.value = fact.id;
          setOpen(true);
        }}
      >
        {fact.text}
        {fact.replaced && (
          <span class="was-inline">
            <s>{fact.replaced.text}</s> until {day(fact.replaced.valid_to)}
          </span>
        )}
      </button>
      <Vis v={fact.visibility} />
      <span class="meta">since {day(fact.valid_from)}</span>
    </div>
  );
}
