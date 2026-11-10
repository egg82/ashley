import assert from 'node:assert/strict';
import { test } from 'node:test';
import { movedRefusal } from './moved.ts';

test('each code a move can be refused with is said as itself, and anything else as a failure', () => {
  assert.equal(movedRefusal('forbidden'), 'not_yours');
  assert.equal(movedRefusal('label_taken'), 'move_label_taken');
  assert.equal(movedRefusal('too_many'), 'move_too_many');
  assert.equal(movedRefusal('unavailable'), 'failed');
  assert.equal(movedRefusal(undefined), 'failed');
});
