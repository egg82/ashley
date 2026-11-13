// What needs a person, lifted above the rest: each with the one action that fixes it.
import type { ConnectionKindInfo, HouseholdConnection } from '../../../api/types';
import { connecting } from '../connections';
import { ageText } from './answered.ts';
import { runFix } from './fixes.ts';
import { needOf } from './needs.ts';

export function AttentionCards({ connections, kinds }: { connections: readonly HouseholdConnection[]; kinds: readonly ConnectionKindInfo[] }) {
  const cards = connections.flatMap((c) => {
    const kind = kinds.find((k) => k.name === c.kind);
    const need = kind ? needOf(c, kind) : null;
    return kind && need ? [{ c, kind, need }] : [];
  });
  if (cards.length === 0) return null;
  return (
    <section class="rr-cards" id="needs-you" aria-label="Needs you">
      {cards.map(({ c, kind, need }) => (
        <div key={`${c.id}${need.fix}`} class="rr-card" role="group" aria-label={need.title}>
          <h2>{need.title}</h2>
          <p>{need.says}</p>
          <div class="dc-act">
            <button class="btn attn" type="button" disabled={!c.can_change || (need.fix === 'oauth' && (!kind.set_up || connecting.value !== null))}
              onClick={() => runFix(need.fix, c, kind)}>{need.action}</button>
            <span class="meta">{kind.title} · last answered {ageText(c.checked_at, Date.now())}</span>
          </div>
        </div>
      ))}
    </section>
  );
}
