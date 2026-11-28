// A remembered fact's card, for a fact her reply cited: its words and the day she learned it. A fact that cannot be
// read, or that the person's facts no longer hold, reads as unknown. `FactCard` is pure; `Fact` keeps the read fresh.
import { useEffect } from 'preact/hooks';
import type { MemoryFact } from '../../api/types';
import type { FactSource } from './sources';

/** The fact `ref` names among `facts`; undefined while they are being read or when it is not among them. */
export function factOf(facts: readonly MemoryFact[] | null | undefined, ref: string): MemoryFact | undefined {
  return facts?.find((f) => String(f.id) === ref);
}

export function FactCard({ source, factId }: { source: FactSource; factId: string }) {
  const facts = source.facts.value;
  const found = factOf(facts, factId);
  return (
    <section class="k-fact" aria-label="A remembered fact">
      <h2 class="label">Remembered</h2>
      {found
        ? <p class="k-fact-text">{found.text}</p>
        : <p class="unk">{facts === undefined ? 'Reading…' : 'unknown'}</p>}
      {found && <p class="meta">{new Date(found.valid_from).toLocaleDateString()}</p>}
    </section>
  );
}

/** The card, keeping its source's facts read while it is shown. */
export function Fact({ source, factId }: { source: FactSource; factId: string }) {
  useEffect(() => source.watch(), [source]);
  return <FactCard source={source} factId={factId} />;
}
