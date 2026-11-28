// What needs the person: things waiting on them, a house that isn't answering, printer faults. A part that could not be
// read shows as unknown beside its name.
import { attentionView } from './attentionView';
import type { AttentionSource } from './sources';

export function Attention({ source }: { source: AttentionSource }) {
  const read = source.attention.value;
  const view = attentionView(read);
  return (
    <section class="k-attention" aria-label="Needs attention">
      <h2 class="label">Needs attention</h2>
      {read === undefined ? <span class="meta">Reading…</span> : (
        <ul class="k-attn">
          {view.needs.map((l) => <li key={l.key} class="k-attn-needs">{l.text}</li>)}
          {view.unknown.map((l) => <li key={l.key} class="k-attn-unk">{l.text} <span class="unk">unknown</span></li>)}
          {view.clear && <li class="k-attn-clear">Nothing needs you</li>}
        </ul>
      )}
    </section>
  );
}
