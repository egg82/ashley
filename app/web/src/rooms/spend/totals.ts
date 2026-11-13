// Adding spans together without inventing a figure: a sum is null only when every part is, so a part with no reading never
// counts as zero.
import type { SpendTotals } from '../../api/types';

function add(a: number | null, b: number | null): number | null {
  return a === null ? b : b === null ? a : a + b;
}

const NOTHING: SpendTotals = {
  calls: 0, metered_calls: 0, unpriced_calls: 0, input_tokens: null, output_tokens: null, cache_read_tokens: null,
  cache_write_tokens: null, audio_ms: null, characters: null, cost_usd: null,
};

export function sumTotals(parts: SpendTotals[]): SpendTotals {
  return parts.reduce<SpendTotals>((a, b) => ({
    calls: a.calls + b.calls,
    metered_calls: a.metered_calls + b.metered_calls,
    unpriced_calls: a.unpriced_calls + b.unpriced_calls,
    input_tokens: add(a.input_tokens, b.input_tokens),
    output_tokens: add(a.output_tokens, b.output_tokens),
    cache_read_tokens: add(a.cache_read_tokens, b.cache_read_tokens),
    cache_write_tokens: add(a.cache_write_tokens, b.cache_write_tokens),
    audio_ms: add(a.audio_ms, b.audio_ms),
    characters: add(a.characters, b.characters),
    cost_usd: add(a.cost_usd, b.cost_usd),
  }), NOTHING);
}
