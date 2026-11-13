import assert from 'node:assert/strict';
import { test } from 'node:test';
import { whereOf } from './pin.ts';

test('a position is a pin on an equirectangular globe', () => {
  assert.deepEqual(whereOf('0', '0'), { pin: { x: 0.5, y: 0.5 } });
  assert.deepEqual(whereOf('90', '-180'), { pin: { x: 0, y: 0 } });
  assert.deepEqual(whereOf('-90', '180'), { pin: { x: 1, y: 1 } });
});

test('no position, half of one or one out of range is no pin, each for its own reason', () => {
  const none = whereOf('', '');
  const half = whereOf('1', '');
  const far = whereOf('99', '0');
  for (const w of [none, half, far]) assert.ok('unknown' in w);
  assert.equal(new Set([none, half, far].map((w) => ('unknown' in w ? w.unknown : ''))).size, 3);
});
