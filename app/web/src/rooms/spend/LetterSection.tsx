// The letter: what the report says, in sentences code wrote from it. Figures stand out; the rest recedes.
import type { SpendResponse } from '../../api/types';
import { letterOf } from './letter';
import type { Win } from './window';

export function Letter({ s, win }: { s: SpendResponse; win: Win }) {
  return (
    <section class="sp-letter" aria-label="In words">
      {letterOf(s, win).map((p, i) => (
        <p key={i}>{p.map((r, j) => (r.fig ? <b key={j}>{r.text}</b> : r.text))}</p>
      ))}
    </section>
  );
}
