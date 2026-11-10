import assert from 'node:assert/strict';
import { test } from 'node:test';
import { withUnsent } from './unsent.ts';

test('each thread keeps its own unsent text', () => {
  const both = withUnsent(withUnsent(new Map(), 'person:1:web', 'and the enclosure'), 'bench:4', 'pin 6?');
  assert.deepEqual([...both], [['person:1:web', 'and the enclosure'], ['bench:4', 'pin 6?']]);
  assert.deepEqual([...withUnsent(both, 'bench:4', 'pin 6, then')], [['person:1:web', 'and the enclosure'], ['bench:4', 'pin 6, then']]);
});

test('sending, or emptying the field, keeps nothing for that thread and leaves the others', () => {
  const both = withUnsent(withUnsent(new Map(), 'person:1:web', 'a'), 'bench:4', 'b');
  assert.deepEqual([...withUnsent(both, 'person:1:web', '')], [['bench:4', 'b']]);
});

test('the map it was given is not changed', () => {
  const before = new Map([['bench:4', 'b']]);
  withUnsent(before, 'bench:4', '');
  assert.deepEqual([...before], [['bench:4', 'b']]);
});
