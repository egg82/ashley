// One connection as a sentence: what she does with it, where it is, the line of when and by whom, and Manage for the rest.
import type { ConnectionKindInfo, HouseholdConnection } from '../../../api/types';
import { Avatar } from './Avatar';
import { ManagePanel } from './ManagePanel';
import { MetaLine } from './MetaLine';
import { needOf } from './needs.ts';
import { sentenceOf } from './sentence.ts';
import { cutting, opened, removing, toggleRow } from './state';
import { Teeth } from './Teeth';

const CHEVRON = <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M2 4.5 6 8.5l4-4" /></svg>;

export function ReachRow({ c, kind }: { c: HouseholdConnection; kind: ConnectionKindInfo }) {
  const open = opened.value === c.id;
  const attn = needOf(c, kind) !== null;
  const s = sentenceOf(c, kind);
  const state = `${attn ? ' attn' : ''}${open ? ' open' : ''}${removing.value === c.id ? ' removing' : ''}${cutting.value === c.id ? ' cutting' : ''}`;
  return (
    <article class={`rr${state}`} id={`c${c.id}`}>
      <Avatar kind={c.kind} title={s.name} />
      <div class="rr-body">
        <p class="rr-sentence">{s.before}<b>{s.name}</b>{s.after}</p>
        {s.address && <span class="rr-addr">{s.address}</span>}
        <MetaLine c={c} attn={attn} />
        <Teeth c={c} />
      </div>
      <button class="rr-manage" type="button" aria-expanded={open} aria-controls={`m${c.id}`} onClick={() => toggleRow(c.id)}>Manage {CHEVRON}</button>
      {open && <ManagePanel c={c} kind={kind} />}
    </article>
  );
}
