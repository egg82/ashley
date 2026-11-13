// The exact figures behind whatever the flow picture has picked: every count the report holds for it, and the cost to the
// digit. A figure the report does not hold is left out, never written as a zero.
import type { SpendResponse, SpendTotals } from '../../api/types';
import { gapShort, spanOf, usdOf, type Span } from './certainty.ts';
import { callsOf, count, exactMoney } from './format.ts';
import type { FlowGraph, Pick } from './flowModel.ts';
import { sumTotals } from './totals.ts';
import { whenOf, type Win } from './window.ts';

export interface Detail {
  title: string;
  sub: string;
  span: Span;
  lines: [label: string, value: string][];
}

export function linesOf(t: SpendTotals, span: Span): Detail['lines'] {
  const lines: Detail['lines'] = [['Calls', count(t.calls)]];
  if (t.metered_calls !== t.calls) lines.push(['Reported usage', count(t.metered_calls)]);
  const out = gapShort(span);
  if (out) lines.push(['Not in the cost', out]);
  const numbers: [string, number | null, string][] = [
    ['Input tokens', t.input_tokens, ''],
    ['Output tokens', t.output_tokens, ''],
    ['Cache read', t.cache_read_tokens, ''],
    ['Cache write', t.cache_write_tokens, ''],
    ['Audio', t.audio_ms, ' ms'],
    ['Characters', t.characters, ''],
  ];
  for (const [label, n, unit] of numbers) if (n !== null && n > 0) lines.push([label, `${count(n)}${unit}`]);
  const usd = usdOf(span);
  lines.push(['Cost', usd === null ? 'unknown' : `${exactMoney(usd)}${span.kind === 'partial' ? ' or more' : ''}`]);
  return lines;
}

export function detailOf(s: SpendResponse, g: FlowGraph, win: Win, pick: Pick | null): Detail {
  const named = (list: { id: string; label: string }[], id: string) => list.find((n) => n.id === id)?.label ?? id;
  let title = 'All calls';
  let totals = sumTotals(s.providers.map((p) => p.usage[win]));
  if (pick?.kind === 'task') {
    const n = g.tasks.find((x) => x.id === pick.id);
    title = n?.label ?? pick.id;
    totals = n?.totals ?? totals;
  } else if (pick?.kind === 'provider') {
    const n = g.providers.find((x) => x.id === pick.id);
    title = n?.label ?? pick.id;
    totals = n?.totals ?? totals;
  } else if (pick?.kind === 'flow') {
    const f = g.flows.find((x) => x.id === pick.id);
    if (f) {
      title = `${named(g.tasks, f.task)} → ${named(g.providers, f.provider)}`;
      totals = f.totals;
    }
  }
  const span = spanOf(totals);
  return { title, sub: `${callsOf(totals.calls)} ${whenOf(win)}`, span, lines: linesOf(totals, span) };
}
