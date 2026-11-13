// How sure a figure is. One function decides it for every view (the flow, the letter, the ledger, the totals), so the same
// span never reads as measured in one place and unknown in another. The grammar: measured is solid, a lower bound carries
// a "+", unpriced is hatched, no usage is dotted, an estimate is dashed with "≈", unknown is hollow with its reason.
import type { SpendEstimate, SpendTotals } from '../../api/types';
import { callsOf, count, money } from './format.ts';

export type Span =
  | { kind: 'idle' }
  | { kind: 'measured'; usd: number }
  /** A cost that leaves out calls that have no price or reported no usage: at least `usd`. */
  | { kind: 'partial'; usd: number; unpriced: number; noUsage: number }
  /** Usage was reported and no call had a price. */
  | { kind: 'unpriced'; unpriced: number; noUsage: number }
  /** No call reported what it used. */
  | { kind: 'noUsage'; noUsage: number };

export function spanOf(t: SpendTotals): Span {
  if (t.calls === 0) return { kind: 'idle' };
  const noUsage = t.calls - t.metered_calls;
  if (t.metered_calls === 0) return { kind: 'noUsage', noUsage };
  if (t.cost_usd === null) return { kind: 'unpriced', unpriced: t.unpriced_calls, noUsage };
  if (t.unpriced_calls + noUsage > 0) return { kind: 'partial', usd: t.cost_usd, unpriced: t.unpriced_calls, noUsage };
  return { kind: 'measured', usd: t.cost_usd };
}

/** The cost a span states, or null when it states none. */
export function usdOf(s: Span): number | null {
  return s.kind === 'measured' || s.kind === 'partial' ? s.usd : null;
}

/** The calls a span's cost leaves out. */
export function leftOut(s: Span): { unpriced: number; noUsage: number } {
  return s.kind === 'partial' || s.kind === 'unpriced' || s.kind === 'noUsage'
    ? { unpriced: 'unpriced' in s ? s.unpriced : 0, noUsage: s.noUsage }
    : { unpriced: 0, noUsage: 0 };
}

/** How a span is written where there is room for one short figure. */
export function figureText(s: Span): string {
  switch (s.kind) {
    case 'idle': return '—';
    case 'measured': return money(s.usd);
    case 'partial': return `${money(s.usd)}+`;
    case 'unpriced': return 'unpriced';
    case 'noUsage': return 'no usage';
  }
}

/** Which calls a figure leaves out, as the hint beside it; empty when it leaves none. */
export function leftOutText(s: Span): string {
  const { unpriced, noUsage } = leftOut(s);
  const parts: string[] = [];
  if (unpriced > 0) parts.push(`${callsOf(unpriced)} with no known price`);
  if (noUsage > 0) parts.push(`${callsOf(noUsage)} that reported no usage`);
  return parts.join(' and ');
}

/** The same, as the short note under a ledger figure: "8 unpriced", "4 no usage". */
export function gapShort(s: Span): string {
  const { unpriced, noUsage } = leftOut(s);
  return [unpriced > 0 ? `${count(unpriced)} unpriced` : '', noUsage > 0 ? `${count(noUsage)} no usage` : ''].filter(Boolean).join(' · ');
}

/** What a household's monthly budget has left: an estimate from the ledger, not the provider's figure. */
export interface Left {
  usd: number;
  over: boolean;
  /** Calls without a price are not in the spend, so the remainder is an upper bound. */
  atMost: boolean;
}

export function estimateLeft(e: SpendEstimate): Left {
  return { usd: Math.abs(e.remaining_usd), over: e.remaining_usd < 0, atMost: e.unpriced_calls > 0 };
}
