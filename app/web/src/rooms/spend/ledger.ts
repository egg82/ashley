// What the ledger lists per provider: which providers get a section, their task rows heaviest first, what each row used,
// and what its margin says about the budget.
import type { SpendProvider, SpendResponse, SpendTotals } from '../../api/types';
import { estimateLeft, spanOf, type Left, type Span } from './certainty.ts';
import { heavier } from './flowModel.ts';
import { count } from './format.ts';
import type { Win } from './window.ts';

export type Used =
  | { kind: 'tokens'; input: string; output: string; cacheRead: string; cacheWrite: string }
  | { kind: 'media'; text: string }
  /** No call reported what it used. */
  | { kind: 'none' };

const exact = (n: number | null) => (n === null ? '—' : count(n));

/** What a row's calls used, from the ones that reported it. */
export function usedOf(t: SpendTotals): Used {
  if (t.calls === 0 || t.metered_calls === 0) return { kind: 'none' };
  if (t.input_tokens !== null && t.output_tokens !== null && t.input_tokens + t.output_tokens > 0) {
    return { kind: 'tokens', input: exact(t.input_tokens), output: exact(t.output_tokens), cacheRead: exact(t.cache_read_tokens), cacheWrite: exact(t.cache_write_tokens) };
  }
  const parts: string[] = [];
  if (t.characters) parts.push(`${count(t.characters)} characters`);
  if (t.audio_ms) parts.push(audio(t.audio_ms));
  return parts.length > 0 ? { kind: 'media', text: parts.join(' · ') } : { kind: 'none' };
}

function audio(ms: number): string {
  const s = Math.round(ms / 1000);
  return s >= 60 ? `${Math.floor(s / 60)} min ${s % 60} s of audio` : `${s} s of audio`;
}

export interface Row {
  task: string;
  totals: SpendTotals;
  span: Span;
  used: Used;
}

/** A provider's tasks that had calls in the window, heaviest first. */
export function rowsOf(p: SpendProvider, win: Win): Row[] {
  return p.tasks
    .filter((k) => k.usage[win].calls > 0)
    .map((k) => ({ task: k.task, totals: k.usage[win], span: spanOf(k.usage[win]), used: usedOf(k.usage[win]) }))
    .sort((a, b) => heavier(a, b) || a.task.localeCompare(b.task));
}

/** The columns a provider's rows share: token counts when any row has them, otherwise one column of what it used. */
export function columnsOf(rows: Row[]): 'tokens' | 'media' {
  return rows.some((r) => r.used.kind === 'tokens') ? 'tokens' : 'media';
}

/** A provider gets a section when it had calls, or says something about what is left that a quiet window would lose. */
export function shown(p: SpendProvider, win: Win): boolean {
  return p.usage[win].calls > 0 || p.balance.state === 'read' || p.estimate !== null;
}

/** The providers with no section, for the quiet line under the ledger. */
export function quietOf(s: SpendResponse, win: Win): string[] {
  return s.providers.filter((p) => !shown(p, win)).map((p) => p.label);
}

/** Whether no provider has had a call this month, so the room has no ledger to read yet. The month holds the week and the day. */
export function unused(s: SpendResponse): boolean {
  return s.providers.every((p) => p.usage.month.calls === 0);
}

export type Budget = { kind: 'none' } | { kind: 'estimate'; budgetUsd: number; left: Left };

export function budgetOf(p: SpendProvider): Budget {
  return p.estimate ? { kind: 'estimate', budgetUsd: p.estimate.budget_usd, left: estimateLeft(p.estimate) } : { kind: 'none' };
}

/** How much of an allowance is left, 0 to 100. */
export function leftPct(q: { remaining: number; limit: number }): number {
  return q.limit > 0 ? Math.max(0, Math.min(100, (q.remaining / q.limit) * 100)) : 0;
}
