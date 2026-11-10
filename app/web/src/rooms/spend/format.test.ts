import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { SpendTotals } from '../../api/types.ts';
import { writing } from '../../household/format.ts';
import { ago, costOf, count, money, usedLine } from './format.ts';

const none: SpendTotals = {
  calls: 0, metered_calls: 0, unpriced_calls: 0, input_tokens: null, output_tokens: null, cache_read_tokens: null,
  cache_write_tokens: null, audio_ms: null, characters: null, cost_usd: null,
};

test('money keeps a cheap call visible and never rounds a real cost to zero', () => {
  assert.equal(money(0.0043), '$0.0043');
  assert.equal(money(0.425), '$0.425');
  assert.equal(money(12.5), '$12.50');
  assert.equal(money(1234.4), '$1,234');
  assert.equal(money(-2), '-$2.00');
});

test('a span with no calls, no reported usage, no price, or a price each say which', () => {
  assert.deepEqual(costOf(none), { kind: 'none' });
  assert.deepEqual(costOf({ ...none, calls: 3 }), { kind: 'unreported' });
  assert.deepEqual(costOf({ ...none, calls: 3, metered_calls: 2, unpriced_calls: 2 }), { kind: 'unpriced' });
  assert.deepEqual(costOf({ ...none, calls: 3, metered_calls: 2, unpriced_calls: 1, cost_usd: 0.5 }), { kind: 'amount', usd: 0.5, unpriced: 1 });
});

test('a priced cost of zero is an amount, not an absence', () => {
  assert.deepEqual(costOf({ ...none, calls: 1, metered_calls: 1, cost_usd: 0 }), { kind: 'amount', usd: 0, unpriced: 0 });
  assert.equal(money(0), '$0.00');
});

test('the used line names only what was reported', () => {
  assert.equal(usedLine({ ...none, calls: 1 }), '1 call');
  assert.equal(usedLine({ ...none, calls: 2, metered_calls: 2, input_tokens: 12_300, output_tokens: 410 }), '2 calls · 12.3K in · 410 out');
  assert.equal(usedLine({ ...none, calls: 2, metered_calls: 1, input_tokens: 0, output_tokens: 0, characters: 1_240 }), '2 calls · 1,240 chars');
});

test('ago says how stale a read is', () => {
  const now = new Date('2026-12-01T03:00:00Z');
  assert.equal(ago('2026-12-01T03:00:00Z', now, 'UTC'), 'just now');
  assert.equal(ago('2026-12-01T02:58:00Z', now, 'UTC'), '2 min ago');
  writing.value = { locale: 'en-US', clock: '12h' };
  assert.equal(ago('2026-12-01T01:30:00Z', now, 'America/Denver'), 'at 6:30 PM');
  writing.value = { locale: 'en-GB', clock: '24h' };
  assert.equal(ago('2026-12-01T01:30:00Z', now, 'America/Denver'), 'at 18:30');
});

test('counts are grouped as the household writes numbers', () => {
  writing.value = { locale: 'de-DE', clock: '24h' };
  assert.equal(count(12345), '12.345');
  writing.value = { locale: 'en-US', clock: '24h' };
  assert.equal(count(12345), '12,345');
});
