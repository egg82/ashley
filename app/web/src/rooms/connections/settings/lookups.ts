// The one choice a script or action offers, and how it is stored. Home Assistant lets her run a thing as a question only
// when it is in `reads` (or Home Assistant itself says it only returns data), and an answer counts as trusted only for
// such a thing, so the stored lists and the choice map like this:
//   makes changes: in neither; finds something out: in `reads`; finds something out and trusted: in `reads` and `service_reads`.
// A thing Home Assistant says only returns data (`fixed`) needs no `reads` entry, so only the trust is stored for it.
export type Choice = 'changes' | 'finds_out' | 'finds_out_trusted';

/** The stored `reads` and `service_reads` (ids of scripts and actions). */
export interface Stored {
  reads: readonly string[];
  service: readonly string[];
}

export const CHOICES: Record<Choice, string> = {
  changes: 'Makes changes',
  finds_out: 'Finds something out',
  finds_out_trusted: 'Finds something out, and I trust the answer',
};

export function choiceOf(id: string, stored: Stored, fixed: boolean): Choice {
  const looksUp = fixed || stored.reads.includes(id);
  if (!looksUp) return 'changes';
  return stored.service.includes(id) ? 'finds_out_trusted' : 'finds_out';
}

function without(ids: readonly string[], id: string): string[] {
  return ids.filter((i) => i !== id);
}

function with_(ids: readonly string[], id: string): string[] {
  return ids.includes(id) ? [...ids] : [...ids, id];
}

/** `stored` with `id` set to `choice`. A trusted answer is never stored without the look-up that makes it count, unless Home Assistant itself makes the thing a look-up (`fixed`, which cannot be set to makes changes). */
export function withChoice(id: string, choice: Choice, stored: Stored, fixed: boolean): Stored {
  const wanted = fixed && choice === 'changes' ? 'finds_out' : choice;
  const reads = wanted === 'changes' ? without(stored.reads, id) : fixed ? [...stored.reads] : with_(stored.reads, id);
  const service = wanted === 'finds_out_trusted' ? with_(stored.service, id) : without(stored.service, id);
  return { reads, service };
}
