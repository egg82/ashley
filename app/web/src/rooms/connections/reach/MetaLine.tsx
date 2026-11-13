// The line under a sentence: a dot that is filled once it has answered since it was added and hollow when it was only
// checked then, when it answered, who added it, and who holds it.
import type { HouseholdConnection } from '../../../api/types';
import { metaOf } from './answered.ts';
import { dayOf } from './format';

const PERSON = <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.2" aria-hidden="true"><circle cx="6" cy="4" r="2.2" /><path d="M1.8 11c.4-2.4 2-3.4 4.2-3.4s3.8 1 4.2 3.4" /></svg>;
const HOUSE = <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.2" aria-hidden="true"><path d="M1.5 6 6 2l4.5 4M2.8 5.3V10.5h6.4V5.3" /></svg>;

export function MetaLine({ c, attn }: { c: HouseholdConnection; attn: boolean }) {
  const m = metaOf(c, Date.now(), dayOf);
  return (
    <div class="rr-meta meta">
      <span class="rr-answered" title={m.answeredSince ? undefined : 'Checked once, when it was added; nothing has asked it since.'}>
        <i class={`rr-dot${attn ? ' attn' : m.answeredSince ? '' : ' once'}`} />{m.answered}
      </span>
      <span class="sep">·</span>
      <span>{m.added}</span>
      <span class="sep">·</span>
      <span class={`rr-holder${m.holder.personal ? ' mine' : ''}`}>{m.holder.personal ? PERSON : HOUSE}{m.holder.text}</span>
    </div>
  );
}
