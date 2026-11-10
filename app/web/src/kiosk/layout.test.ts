import assert from 'node:assert/strict';
import { test } from 'node:test';
import { SIZES, validLayout } from './layout.ts';
import { polled, POLL_MS } from './polling.ts';

const whole = {
  laid_out: true,
  seq: 7,
  placed: [
    { id: 4, kind: 'conversation', order: 1, size: 'full' },
    { id: 1, kind: 'clock', order: 0, size: 'small' },
    { id: 3, kind: 'controls', order: 2, size: 'medium' },
  ],
};

test('a whole layout is read with its placed in order', () => {
  const got = validLayout(whole);
  assert.deepEqual(got?.placed.map((p) => p.id), [1, 4, 3]);
  assert.equal(got?.seq, 7);
});

test('nothing is drawn from a layout that was never laid out, or is not an object', () => {
  assert.equal(validLayout({ ...whole, laid_out: false }), null);
  for (const raw of [null, undefined, 'x', 3, [], { placed: [] }]) assert.equal(validLayout(raw), null);
});

test('a gap or a repeat in the orders rejects the layout', () => {
  const at = (orders: number[]) => ({ ...whole, placed: whole.placed.map((p, i) => ({ ...p, order: orders[i]! })) });
  assert.equal(validLayout(at([0, 1, 3])), null);
  assert.equal(validLayout(at([0, 1, 1])), null);
  assert.equal(validLayout(at([1, 2, 3])), null);
  assert.notEqual(validLayout(at([2, 1, 0])), null);
});

test('a repeated id, an unknown kind or size, or no conversation rejects the layout', () => {
  const swap = (change: object, at = 1) => ({ ...whole, placed: whole.placed.map((p, i) => (i === at ? { ...p, ...change } : p)) });
  assert.equal(validLayout(swap({ id: 4 })), null);
  assert.equal(validLayout(swap({ kind: 'weather' }, 0)), null);
  assert.equal(validLayout(swap({ size: 'huge' })), null);
  assert.equal(validLayout({ ...whole, placed: whole.placed.filter((p) => p.kind !== 'conversation').map((p, i) => ({ ...p, order: i })) }), null);
});

test('a piece with a field of the wrong type rejects the layout', () => {
  assert.equal(validLayout({ ...whole, placed: [{ id: '4', kind: 'conversation', order: 0, size: 'full' }] }), null);
  assert.equal(validLayout({ ...whole, placed: [{ id: 4, kind: 'conversation', order: 0.5, size: 'full' }] }), null);
  assert.equal(validLayout({ ...whole, placed: 'x' }), null);
});

test('every size class the server may send is one the page knows', () => {
  assert.deepEqual([...SIZES], ['small', 'medium', 'large', 'full']);
});

test('the layout is read on its timer only while the feed is down, since the feed says when it changes', () => {
  assert.equal(polled('layout', true), false);
  assert.equal(polled('layout', false), true);
  assert.ok(POLL_MS.layout > 0);
});

test('a seq that is not a whole number rejects the layout', () => {
  assert.equal(validLayout({ ...whole, seq: '7' }), null);
  assert.equal(validLayout({ ...whole, seq: 7.5 }), null);
});
