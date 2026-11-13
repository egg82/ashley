// Builders for the room's tests: a payload shaped like the API's, with only what a test names set.
import type { SpendBalance, SpendProvider, SpendResponse, SpendTotals } from '../../api/types.ts';

export const NONE: SpendTotals = {
  calls: 0, metered_calls: 0, unpriced_calls: 0, input_tokens: null, output_tokens: null, cache_read_tokens: null,
  cache_write_tokens: null, audio_ms: null, characters: null, cost_usd: null,
};

/** A span of calls that all reported usage and were all priced. */
export function priced(calls: number, usd: number, over: Partial<SpendTotals> = {}): SpendTotals {
  return { ...NONE, calls, metered_calls: calls, input_tokens: calls * 100, output_tokens: calls * 10, cost_usd: usd, ...over };
}

export const UNKNOWN: SpendBalance = { state: 'unknown', quota: null, read_at: null, why: 'It has no read.', docs_url: null };

type Spans = { today?: SpendTotals; week?: SpendTotals; month?: SpendTotals };

export function provider(id: string, label: string, tasks: Record<string, Spans>, over: Partial<SpendProvider> = {}): SpendProvider {
  const spans = (pick: 'today' | 'week' | 'month') => Object.values(tasks).map((s) => s[pick] ?? NONE);
  const sum = (list: SpendTotals[]): SpendTotals => list.reduce((a, b) => ({
    ...a, calls: a.calls + b.calls, metered_calls: a.metered_calls + b.metered_calls, unpriced_calls: a.unpriced_calls + b.unpriced_calls,
    cost_usd: b.cost_usd === null ? a.cost_usd : (a.cost_usd ?? 0) + b.cost_usd,
    input_tokens: b.input_tokens === null ? a.input_tokens : (a.input_tokens ?? 0) + b.input_tokens,
    output_tokens: b.output_tokens === null ? a.output_tokens : (a.output_tokens ?? 0) + b.output_tokens,
  }), NONE);
  return {
    provider: id, label, kind: 'paid', balance: UNKNOWN, estimate: null,
    usage: { today: sum(spans('today')), week: sum(spans('week')), month: sum(spans('month')) },
    tasks: Object.entries(tasks).map(([task, s]) => ({ task, usage: { today: s.today ?? NONE, week: s.week ?? NONE, month: s.month ?? NONE } })),
    ...over,
  };
}

export function response(providers: SpendProvider[]): SpendResponse {
  return {
    zone: 'UTC', as_of: '2026-11-13T12:00:00Z',
    windows: [
      { name: 'today', starts_at: '2026-11-13T00:00:00Z' },
      { name: 'week', starts_at: '2026-11-07T00:00:00Z' },
      { name: 'month', starts_at: '2026-11-01T00:00:00Z' },
    ],
    providers,
  };
}
