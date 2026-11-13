import assert from 'node:assert/strict';
import { test } from 'node:test';
import { estimateLeft, figureText, gapShort, leftOut, leftOutText, spanOf, usdOf } from './certainty.ts';
import { NONE, priced } from './fixtures.ts';
import { sumTotals } from './totals.ts';

test('a span with no calls, no reported usage, no price, some missing, or none missing each say which', () => {
  assert.deepEqual(spanOf(NONE), { kind: 'idle' });
  assert.deepEqual(spanOf({ ...NONE, calls: 3 }), { kind: 'noUsage', noUsage: 3 });
  assert.deepEqual(spanOf({ ...NONE, calls: 3, metered_calls: 2, unpriced_calls: 2 }), { kind: 'unpriced', unpriced: 2, noUsage: 1 });
  assert.deepEqual(spanOf(priced(3, 0.5, { metered_calls: 2, unpriced_calls: 1 })), { kind: 'partial', usd: 0.5, unpriced: 1, noUsage: 1 });
  assert.deepEqual(spanOf(priced(3, 0.5)), { kind: 'measured', usd: 0.5 });
});

test('calls that reported no usage make a cost a lower bound even when every metered call was priced', () => {
  assert.equal(spanOf(priced(4, 2, { metered_calls: 3 })).kind, 'partial');
});

test('a priced cost of zero is a measured amount, never an absence', () => {
  const s = spanOf(priced(1, 0));
  assert.deepEqual(s, { kind: 'measured', usd: 0 });
  assert.equal(figureText(s), '$0.00');
});

test('a figure is written as the amount, the amount with a plus, or the reason there is none', () => {
  assert.equal(figureText({ kind: 'idle' }), '—');
  assert.equal(figureText({ kind: 'measured', usd: 44.81477 }), '$44.81');
  assert.equal(figureText({ kind: 'partial', usd: 0.0091, unpriced: 0, noUsage: 1 }), '$0.0091+');
  assert.equal(figureText({ kind: 'unpriced', unpriced: 8, noUsage: 0 }), 'unpriced');
  assert.equal(figureText({ kind: 'noUsage', noUsage: 2 }), 'no usage');
});

test('only a measured or partial span states a cost', () => {
  assert.equal(usdOf({ kind: 'measured', usd: 1 }), 1);
  assert.equal(usdOf({ kind: 'partial', usd: 1, unpriced: 1, noUsage: 0 }), 1);
  assert.equal(usdOf({ kind: 'unpriced', unpriced: 1, noUsage: 0 }), null);
  assert.equal(usdOf({ kind: 'noUsage', noUsage: 1 }), null);
  assert.equal(usdOf({ kind: 'idle' }), null);
});

test('what a figure leaves out is counted and worded', () => {
  assert.deepEqual(leftOut({ kind: 'measured', usd: 1 }), { unpriced: 0, noUsage: 0 });
  assert.equal(leftOutText({ kind: 'measured', usd: 1 }), '');
  assert.equal(leftOutText({ kind: 'partial', usd: 1, unpriced: 1, noUsage: 54 }), '1 call with no known price and 54 calls that reported no usage');
  assert.equal(leftOutText({ kind: 'noUsage', noUsage: 2 }), '2 calls that reported no usage');
});

test('the short note under a figure counts only what it leaves out', () => {
  assert.equal(gapShort({ kind: 'measured', usd: 1 }), '');
  assert.equal(gapShort({ kind: 'partial', usd: 1, unpriced: 8, noUsage: 4 }), '8 unpriced · 4 no usage');
  assert.equal(gapShort({ kind: 'noUsage', noUsage: 2 }), '2 no usage');
});

test('summing spans keeps unknown unknown', () => {
  const sum = sumTotals([NONE, NONE]);
  assert.equal(sum.cost_usd, null);
  assert.equal(sum.input_tokens, null);
  const mixed = sumTotals([NONE, priced(2, 1.5), priced(1, 0.25, { metered_calls: 0, input_tokens: null, output_tokens: null })]);
  assert.equal(mixed.calls, 3);
  assert.equal(mixed.cost_usd, 1.75);
  assert.equal(mixed.input_tokens, 200);
  assert.equal(spanOf(mixed).kind, 'partial');
});

test('a budget estimate is an upper bound while calls lack a price, and says when it is overspent', () => {
  assert.deepEqual(estimateLeft({ budget_usd: 60, spent_usd: 44, remaining_usd: 16, unpriced_calls: 0 }), { usd: 16, over: false, atMost: false });
  assert.deepEqual(estimateLeft({ budget_usd: 5, spent_usd: 7, remaining_usd: -2, unpriced_calls: 3 }), { usd: 2, over: true, atMost: true });
});
