// The certainty grammar as markup: a figure drawn by what is known about it, and the key that names each form. The flow,
// the totals and the ledger all draw their figures through here, so one state looks the same everywhere.
import { figureText, gapShort, leftOutText, type Span } from './certainty';

/** A span's cost: an amount, the amount with a "+" when calls are left out of it, or the form that says why there is none. */
export function Figure({ span, note = false }: { span: Span; note?: boolean }) {
  const hint = leftOutText(span);
  switch (span.kind) {
    case 'idle':
      return <span class="meta">—</span>;
    case 'measured':
      return <b class="sp-fig">{figureText(span)}</b>;
    case 'partial':
      return (
        <span class="sp-fig-wrap">
          <b class="sp-fig" title={`At least this much: ${hint} are not in it`} tabindex={0}>{figureText(span)}</b>
          {note && <span class="meta">{gapShort(span)}</span>}
        </span>
      );
    case 'unpriced':
      return (
        <span class="sp-fig-wrap">
          <span class="sp-tag sp-hatch" title="Usage was reported, and none of these calls has a known price." tabindex={0}>unpriced</span>
          {note && <span class="meta">{gapShort(span)}</span>}
        </span>
      );
    case 'noUsage':
      return (
        <span class="sp-fig-wrap">
          <span class="sp-tag sp-dots" title="These calls reported no usage, so there is nothing to price." tabindex={0}>no usage reported</span>
        </span>
      );
  }
}

const KEY: { cls: string; word: string; what: string }[] = [
  { cls: 'sp-solid', word: 'Measured', what: 'priced' },
  { cls: 'sp-hatch', word: 'Unpriced', what: 'no price' },
  { cls: 'sp-dots', word: 'No usage', what: 'reported none' },
  { cls: 'sp-est', word: 'Estimate', what: 'worked out' },
  { cls: 'sp-hollow', word: 'Unknown', what: 'with its reason' },
];

export function CertaintyKey() {
  return (
    <ul class="sp-key" aria-label="How sure each figure is">
      {KEY.map((k) => (
        <li key={k.word}>
          <i class={`sp-sw ${k.cls}`} aria-hidden="true">{k.cls === 'sp-est' ? '≈' : ''}</i>
          <b>{k.word}</b>
          <span class="meta">{k.what}</span>
        </li>
      ))}
    </ul>
  );
}
