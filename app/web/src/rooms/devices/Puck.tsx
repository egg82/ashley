// One device drawn on the plan: rings when it hears and speaks, dots when it shows text, and a mark for who it is for.
import type { ListedDevice } from '../../api/types';
import { select, selected } from './devices';
import { itDoes, kindName, whoMark } from './sentence';

function Glyph({ d }: { d: ListedDevice }) {
  return d.medium === 'spoken' ? (
    <span class="pk-glyph ring" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 10v4M9 7v10M13 4v16M17 7v10M21 10v4" /></svg></span>
  ) : (
    <span class="pk-glyph typing" aria-hidden="true"><i /><i /><i /></span>
  );
}

function Audience({ a }: { a: ListedDevice['audience'] }) {
  return (
    <span class={`pk-who ${a}`}>
      <span class="pk-mark" aria-hidden="true">{a === 'household' ? <><i /><i /><i /></> : <i />}</span>
      {whoMark(a)}
    </span>
  );
}

export function Puck({ d }: { d: ListedDevice }) {
  return (
    <button class={`pk ${d.medium}`} type="button" aria-pressed={selected.value === d.id} onClick={() => select(d.id)}>
      <Glyph d={d} />
      <span class="pk-text">
        <b>{d.name}</b>
        <span class="pk-sub">{kindName(d.form)} · {itDoes(d)}</span>
        <Audience a={d.audience} />
      </span>
    </button>
  );
}
