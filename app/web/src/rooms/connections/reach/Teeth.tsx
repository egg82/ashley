// A mail connection's mailboxes as teeth, one each: solid when shared with the household, hatched when kept to its holder.
import type { HouseholdConnection } from '../../../api/types';
import { teethOf, teethSummary } from './teeth.ts';

export function Teeth({ c }: { c: HouseholdConnection }) {
  const teeth = teethOf(c);
  if (teeth.length < 2) return null;
  return (
    <div class="rr-teeth">
      <span class="rr-bitting" aria-hidden="true">{teeth.map((t) => <i key={t.ref} class={t.shared ? 'shared' : 'kept'} />)}</span>
      <span class="meta">{teethSummary(c)}</span>
    </div>
  );
}
