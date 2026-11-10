import assert from 'node:assert/strict';
import { test } from 'node:test';
import { lineAt } from './transcript.ts';

test('the spoken line is the latest one started, and none before the first or in an empty transcript', () => {
  const starts = [0, 4.5, 9, 65];
  assert.deepEqual([0, 4.4, 4.5, 8.99, 9, 64, 65, 9000].map((t) => lineAt(starts, t)), [0, 0, 1, 1, 2, 2, 3, 3]);
  assert.equal(lineAt([2, 5], 1), -1);
  assert.equal(lineAt([], 3), -1);
});

test('a repeated start takes the later line, and a start out of order is not mistaken for the latest', () => {
  assert.equal(lineAt([0, 3, 3, 6], 3), 2);
  assert.equal(lineAt([0, 10, 4], 5), 2);
  assert.equal(lineAt([0, 10, 4], 12), 1);
});
