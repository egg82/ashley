import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';
import { focusAsk } from './state.ts';
import { show, NOTHING_HELD, type Held } from './shown.ts';

const LAID = new Set([1, 2, 3, 4]);
let framed: (readonly number[] | 'whole')[];
let held: Held;
const move = { frame: (ids: readonly number[] | 'whole') => void framed.push(ids), hold: (change: (was: Held) => Held) => void (held = change(held)) };

beforeEach(() => {
  framed = [];
  held = NOTHING_HELD;
  focusAsk.value = null;
});

test('one piece to see asks for focus, as a change of hers out of view does, and holds it in full', () => {
  show([3], false, LAID, move);
  assert.equal(focusAsk.value, 3);
  assert.deepEqual(framed, []);
  assert.deepEqual([...held.full], [3]);
});

test('several pieces are framed together and drawn in full, with no focus asked', () => {
  show([2, 4], false, LAID, move);
  assert.deepEqual(framed, [[2, 4]]);
  assert.deepEqual([...held.full], [2, 4]);
  assert.equal(focusAsk.value, null);
});

test('fold puts the pieces away and leaves the camera and focus alone', () => {
  show([1, 2], true, LAID, move);
  assert.deepEqual([...held.away], [1, 2]);
  assert.deepEqual(held.full.size, 0);
  assert.deepEqual(framed, []);
  assert.equal(focusAsk.value, null);
});

test('a later show keeps what an earlier one held, moving a piece from put away to full and back', () => {
  show([1, 2], true, LAID, move);
  show([3, 4], false, LAID, move);
  show([2, 4], true, LAID, move);
  assert.deepEqual([...held.away], [1, 2, 4]);
  assert.deepEqual([...held.full], [3]);
  show([1], false, LAID, move);
  assert.deepEqual([...held.away], [2, 4]);
  assert.deepEqual([...held.full], [3, 1]);
});

test('the whole bench is framed whole, and with fold all of it is put away', () => {
  show([3], false, LAID, move);
  framed = [];
  show([], false, LAID, move);
  assert.deepEqual(framed, ['whole']);
  assert.deepEqual([...held.full, ...held.away], []);
  show([], true, LAID, move);
  assert.deepEqual([...held.away], [1, 2, 3, 4]);
  assert.deepEqual(framed, ['whole', 'whole']);
});

test('pieces that are not laid out are dropped, and with none left nothing moves', () => {
  show([2, 9], false, LAID, move);
  assert.equal(focusAsk.value, 2);
  focusAsk.value = null;
  show([9], false, LAID, move);
  assert.equal(focusAsk.value, null);
  assert.deepEqual(framed, []);
});
