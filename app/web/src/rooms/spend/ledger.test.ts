import assert from 'node:assert/strict';
import { test } from 'node:test';
import { NONE, priced, provider, response } from './fixtures.ts';
import { budgetOf, columnsOf, leftPct, quietOf, rowsOf, shown, unused, usedOf } from './ledger.ts';

test('a row used tokens, characters and audio, or reported nothing', () => {
  assert.deepEqual(usedOf(priced(2, 1, { input_tokens: 1306776, output_tokens: 10, cache_read_tokens: null, cache_write_tokens: 4 })), {
    kind: 'tokens', input: '1,306,776', output: '10', cacheRead: '—', cacheWrite: '4',
  });
  assert.deepEqual(usedOf({ ...NONE, calls: 1, metered_calls: 1, input_tokens: 0, output_tokens: 0, characters: 867 }), { kind: 'media', text: '867 characters' });
  assert.deepEqual(usedOf({ ...NONE, calls: 1, metered_calls: 1, audio_ms: 92_500 }), { kind: 'media', text: '1 min 33 s of audio' });
  assert.deepEqual(usedOf({ ...NONE, calls: 3 }), { kind: 'none' });
  assert.deepEqual(usedOf(NONE), { kind: 'none' });
});

test('rows are the tasks with calls in the window, heaviest first, and the columns follow what they used', () => {
  const p = provider('g', 'Gemini', {
    chat: { month: priced(5, 0.8) },
    idle: { month: NONE },
    tidy: { month: priced(9, 0.07) },
    look: { month: { ...NONE, calls: 2 } },
  });
  const rows = rowsOf(p, 'month');
  assert.deepEqual(rows.map((r) => r.task), ['chat', 'tidy', 'look']);
  assert.equal(columnsOf(rows), 'tokens');
  assert.equal(columnsOf(rowsOf(provider('e', 'E', { speak: { month: { ...NONE, calls: 1, metered_calls: 1, characters: 5 } } }), 'month')), 'media');
  assert.deepEqual(rowsOf(p, 'today'), []);
});

test('a quiet provider gets a section only when it says what is left', () => {
  const quiet = provider('q', 'Quiet', { chat: { month: NONE } });
  const reads = provider('r', 'Reads', {}, { balance: { state: 'read', quota: { unit: 'characters', used: 1, limit: 10, remaining: 9, resets_at: null }, read_at: null, why: null, docs_url: null } });
  const budget = provider('b', 'Budget', {}, { estimate: { budget_usd: 5, spent_usd: 0, remaining_usd: 5, unpriced_calls: 0 } });
  const busy = provider('x', 'Busy', { chat: { month: priced(1, 1) } });
  assert.deepEqual([quiet, reads, budget, busy].map((p) => shown(p, 'month')), [false, true, true, true]);
  assert.deepEqual(quietOf(response([quiet, reads, busy]), 'month'), ['Quiet']);
});

test('the room is unused only when no provider has had a call this month', () => {
  assert.equal(unused(response([provider('q', 'Quiet', { chat: { month: NONE } })])), true);
  assert.equal(unused(response([])), true);
  assert.equal(unused(response([provider('x', 'Busy', { chat: { month: priced(1, 1) } })])), false);
});

test('a budget is none until one is set, and then an estimate of what is left', () => {
  assert.deepEqual(budgetOf(provider('a', 'A', {})), { kind: 'none' });
  const b = budgetOf(provider('a', 'A', {}, { estimate: { budget_usd: 60, spent_usd: 70, remaining_usd: -10, unpriced_calls: 0 } }));
  assert.deepEqual(b, { kind: 'estimate', budgetUsd: 60, left: { usd: 10, over: true, atMost: false } });
});

test('what is left of an allowance stays between none and all', () => {
  assert.equal(leftPct({ remaining: 25, limit: 100 }), 25);
  assert.equal(leftPct({ remaining: 5, limit: 0 }), 0);
  assert.equal(leftPct({ remaining: -3, limit: 10 }), 0);
});
