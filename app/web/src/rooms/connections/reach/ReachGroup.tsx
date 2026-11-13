// One group of the room: a heading for what it gives her, then its connections as sentences.
import type { ConnectionKindInfo } from '../../../api/types';
import { ReachRow } from './ReachRow';
import type { Group } from './groups.ts';

export function ReachGroup({ group, kinds }: { group: Group; kinds: readonly ConnectionKindInfo[] }) {
  return (
    <section class="rr-group" id={`g-${group.id}`}>
      <h2 class="rr-head">{group.title}</h2>
      {group.items.map((c) => {
        const kind = kinds.find((k) => k.name === c.kind);
        return kind ? <ReachRow key={c.id} c={c} kind={kind} /> : null;
      })}
    </section>
  );
}
