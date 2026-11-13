import assert from 'node:assert/strict';
import { test } from 'node:test';
import { penOf } from './pen.ts';

test('the pen fills toward the limit and turns near in the last tenth', () => {
  assert.deepEqual(penOf(0, 8000), { fraction: 0, near: false });
  assert.deepEqual(penOf(967, 8000), { fraction: 967 / 8000, near: false });
  assert.equal(penOf(7199, 8000).near, false);
  assert.equal(penOf(7200, 8000).near, true);
  assert.deepEqual(penOf(8000, 8000), { fraction: 1, near: true });
});
