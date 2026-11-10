import assert from 'node:assert/strict';
import { test } from 'node:test';
import { charCount, limitOf, MAX_CHARS } from './limit.ts';

test('a short message has no note and may be sent', () => {
  assert.deepEqual(limitOf('hello'), { over: false, note: null });
});

test('near the limit a quiet count shows', () => {
  assert.deepEqual(limitOf('a'.repeat(3800)), { over: false, note: '3,800 / 4,000' });
});

test('exactly the limit is allowed; one past is not, and says by how much', () => {
  assert.equal(limitOf('a'.repeat(MAX_CHARS)).over, false);
  const past = limitOf('a'.repeat(4312));
  assert.equal(past.over, true);
  assert.match(past.note ?? '', /^4,312 \/ 4,000\..*cut 312\./);
});

test('characters are counted as the server counts them, a code point each', () => {
  assert.equal(charCount('a\u{1F600}b'), 3);
  assert.equal(limitOf('\u{1F600}'.repeat(MAX_CHARS)).over, false);
});
