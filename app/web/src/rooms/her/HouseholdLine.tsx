// The household speaking as itself (a wake: an event it reported): a quiet line under its own name, never a bubble of
// the person it is about. A live thread carries no name for it, so it reads "Household".
import { moment } from '../memory/facts';

export function HouseholdLine({ id, name, text, at }: { id?: number; name?: string | null; text: string; at: string }) {
  return (
    <div id={id === undefined ? undefined : `turn-${id}`} class="household-line">
      <div class="meta">{name ?? 'Household'} · {moment(at)}</div>
      <p>{text}</p>
    </div>
  );
}
