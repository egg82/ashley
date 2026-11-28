import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';
import { clearPointing, hovered, marked, takePointing, tapped, typing } from './pointing.ts';

const bench = new Set([1, 2, 3]);
beforeEach(() => { clearPointing(); typing.value = false; });

test('the piece under the cursor wins over the last one tapped', () => {
  tapped.value = 1;
  hovered.value = 2;
  assert.equal(takePointing(bench), 2);
});

test('with the cursor on no piece, it is the last one tapped', () => {
  tapped.value = 3;
  assert.equal(takePointing(bench), 3);
});

test('a tap is spent by the send, and nothing is pointed at after it', () => {
  tapped.value = 1;
  assert.equal(takePointing(bench), 1);
  assert.equal(takePointing(bench), null);
});

test('a piece that is no longer on the bench is not pointed at', () => {
  tapped.value = 9;
  assert.equal(takePointing(bench), null);
});

test('the mark shows only while typing, on the piece a send would point at', () => {
  tapped.value = 1;
  assert.equal(marked.value, null);
  typing.value = true;
  assert.equal(marked.value, 1);
  hovered.value = 2;
  assert.equal(marked.value, 2);
});
