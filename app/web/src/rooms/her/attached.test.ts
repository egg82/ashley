import assert from 'node:assert/strict';
import { test } from 'node:test';
import { attachedOn, firstLine, isLongPaste, pastedOn, unattachedOn, withAttached } from './attached.ts';
import { PASTE_MIN } from './limit.ts';

test('a paste is long only past the threshold', () => {
  assert.equal(isLongPaste('x'.repeat(PASTE_MIN)), false);
  assert.equal(isLongPaste('x'.repeat(PASTE_MIN + 1)), true);
});

test('a paste is kept per thread, a second joins it after a blank line, and it clears', () => {
  pastedOn('a', 'one');
  pastedOn('a', 'two');
  assert.equal(attachedOn('a'), 'one\n\ntwo');
  assert.equal(attachedOn('b'), null);
  unattachedOn('a');
  assert.equal(attachedOn('a'), null);
});

test('an empty text leaves nothing held', () => {
  assert.equal(withAttached(new Map([['a', 'x']]), 'a', '').size, 0);
});

test('the title is the first line that has words, cut to the length given', () => {
  assert.equal(firstLine('\n  \n  Assignment brief  \nmore', 60), 'Assignment brief');
  assert.equal(firstLine('abcdef', 3), 'abc');
  assert.equal(firstLine('  \n ', 60), '');
});
